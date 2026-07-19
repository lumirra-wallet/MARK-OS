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
the translation between them.

The translation is honest, not fabricated: DevPipeline doesn't produce a
graded confidence score per milestone, only the reviewer's pass/fail
verdict, so confidence here is 1.0/0.0, never an invented number in
between. Timing is DevPipeline's own real per-milestone elapsed time.

Scoped to DevPipeline (mission-tier) runs only, not agent_loop's single-shot
simple_agent path — a quick one-step file edit doesn't carry the same kind
of learning signal a multi-milestone mission does, so reflecting on it
would mean fabricating structure DevPipeline doesn't actually have.

This module used to hold its own standalone PromptRegistry/LearningStore,
because the SmartAgent handling each request was rebuilt from scratch and
couldn't accumulate anything itself. Now that smartagent.server.api keeps
ONE persistent SmartAgent for the life of the process (see api.py's
_get_mark_agent), agent.reflection_engine already IS persistent — this
module is just the translation function, not a second place learning
lives.

Known limitation: agent.reflection_engine captured agent.memory/
agent.knowledge by reference when SmartAgent was constructed.
_get_mark_agent rescopes agent.memory/agent.knowledge in place when the
workspace changes, but reflection_engine's own captured references don't
follow that switch — so reflections keep landing in whichever workspace's
vault was active when the agent was first constructed. Not fixed here;
would need memory/knowledge to be dynamic lookups throughout SmartAgent,
not just in this one path — real scope, not something to patch quietly in
passing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from smartagent.logs.logger import get_logger
from smartagent.reflection.reflection_engine import ReflectionResult

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


def reflect_on_pipeline_result(result: "PipelineResult", agent: Any) -> ReflectionResult | None:
    """Run the persistent agent's own ReflectionEngine on a completed
    mission. Best-effort: never raises. Returns None if reflection
    couldn't run, same contract ReflectionEngine.reflect() already offers."""
    try:
        context = _build_execution_context(result)
        reflection = agent.reflection_engine.reflect(context)
        logger.info(
            "MARK STATE reflected  goal=%r  score=%.0f%%  memory=%d  knowledge=%d  prompts=%d",
            result.goal[:60], reflection.critic.overall_score * 100,
            reflection.memory_entries_added, reflection.knowledge_proposals_added,
            reflection.prompt_versions_added,
        )
        return reflection
    except Exception as exc:  # noqa: BLE001 — reflection must never break a run
        logger.warning("reflection_bridge: reflection failed: %s", exc)
        return None
