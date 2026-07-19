"""
smartagent.server.reflection_bridge — wires DevPipeline's real per-mission
results into smartagent.reflection.ReflectionEngine after a mission
completes.

reflection/ReflectionEngine (Critic → ImprovementPlanner → LearningStore →
PromptRegistry → Memory → Knowledge) already exists and already works — it
was sitting unused because it was built for a different, dormant pipeline
(smartagent/executive/), which produces the ExecutionContext/TaskGraph
shape it expects. DevPipeline (the live, dashboard-integrated pipeline)
produces a different shape (PipelineResult/MilestoneResult). This module is
the translation between them — see "MARK Core Reconciliation" (move 3).

The translation is honest, not fabricated: DevPipeline doesn't produce a
graded confidence score per milestone, only the reviewer's pass/fail
verdict, so confidence here is 1.0/0.0, never an invented number in
between. Timing is DevPipeline's own real per-milestone elapsed time.

Scoped to DevPipeline (mission-tier) runs only, not agent_loop's single-shot
simple_agent path — a quick one-step file edit doesn't carry the same kind
of learning signal a multi-milestone mission does, so reflecting on it
would mean fabricating structure DevPipeline doesn't actually have.

Cross-request accumulation: the SmartAgent instance api.py builds is
reconstructed fresh on every /run call, so its own agent.prompt_registry
and agent.learning_store never accumulate anything within a session. This
bridge holds its own PromptRegistry/LearningStore as a process-level
singleton instead, seeded from whichever request's memory_manager reaches
it first, so prompt improvements and analytics actually persist across
requests within one running server — the same discipline
smartagent.server.self_state.py already applies for the self-model.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from smartagent.logs.logger import get_logger
from smartagent.reflection.learning_store import LearningStore
from smartagent.reflection.prompt_registry import PromptRegistry
from smartagent.reflection.reflection_engine import ReflectionEngine, ReflectionResult

if TYPE_CHECKING:
    from smartagent.engineer.dev_pipeline import PipelineResult

logger = get_logger(__name__)


def _build_execution_context(result: "PipelineResult") -> Any:
    """Translate a real PipelineResult into a real ExecutionContext —
    one Task per milestone, status/result/error/timing taken directly
    from that milestone's actual MilestoneResult, nothing invented."""
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.execution_state import ExecutionState
    from smartagent.executive.task import Task, TaskStatus, TaskType
    from smartagent.executive.task_graph import TaskGraph

    graph = TaskGraph()
    timings: dict[str, float] = {}
    confidences: dict[str, float] = {}
    for mr in result.milestone_results:
        status = TaskStatus.COMPLETED if mr.success else TaskStatus.FAILED
        outcome = mr.review or ("Milestone passed." if mr.success else "Milestone failed.")
        task = Task(
            title=mr.milestone,
            description=mr.milestone,
            task_type=TaskType.IMPLEMENTATION,
            status=status,
            result=outcome if mr.success else None,
            error=None if mr.success else outcome,
        )
        graph.add_task(task)
        timings[task.id] = mr.elapsed
        confidences[task.id] = 1.0 if mr.success else 0.0

    return ExecutionContext(
        goal=result.goal,
        task_graph=graph,
        state=ExecutionState.COMPLETED if result.success else ExecutionState.FAILED,
        metadata={"task_timing": timings, "task_confidence": confidences},
    )


class ReflectionBridge:
    """One per process. Holds the persistent prompt registry and learning
    store so reflection accumulates across requests even though the
    SmartAgent handling each request is rebuilt from scratch."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.prompt_registry = PromptRegistry()
        self._learning_store: LearningStore | None = None

    def reflect_on_pipeline_result(
        self,
        result: "PipelineResult",
        memory_manager: Any = None,
        knowledge_manager: Any = None,
        model_manager: Any = None,
    ) -> ReflectionResult | None:
        """Best-effort: never raises. Returns None if reflection couldn't
        run, same contract ReflectionEngine.reflect() already offers."""
        try:
            with self._lock:
                if self._learning_store is None:
                    self._learning_store = LearningStore(memory_manager=memory_manager)
                engine = ReflectionEngine(
                    memory_manager=memory_manager,
                    knowledge_manager=knowledge_manager,
                    model_manager=model_manager,
                    prompt_registry=self.prompt_registry,
                    learning_store=self._learning_store,
                )
            context = _build_execution_context(result)
            reflection = engine.reflect(context)
            logger.info(
                "MARK STATE reflected  goal=%r  score=%.0f%%  memory=%d  knowledge=%d  prompts=%d",
                result.goal[:60], reflection.critic.overall_score * 100,
                reflection.memory_entries_added, reflection.knowledge_proposals_added,
                reflection.prompt_versions_added,
            )
            return reflection
        except Exception as exc:  # noqa: BLE001 — reflection must never break a run
            logger.warning("ReflectionBridge: reflection failed: %s", exc)
            return None


_bridge: ReflectionBridge | None = None


def get_reflection_bridge() -> ReflectionBridge:
    global _bridge
    if _bridge is None:
        _bridge = ReflectionBridge()
    return _bridge
