"""
ReflectionEngine — Milestone 14: orchestrates post-execution reflection.

Called by the Orchestrator after every successful run.  Coordinates:
  1. ExecutionAnalyzer  — build structured ExecutionReport
  2. Critic             — evaluate what worked / failed
  3. ImprovementPlanner — create a concrete improvement plan
  4. ConfidenceEngine   — update per-worker and per-tool stats
  5. PromptRegistry     — store improved prompt versions
  6. LearningStore      — record analytics
  7. MemoryManager      — persist lessons and summaries
  8. KnowledgeManager   — propose new concepts via the inbox

All steps are best-effort: failures are logged and never surface to callers.

Usage::

    engine = ReflectionEngine(
        memory_manager=agent.memory,
        knowledge_manager=agent.knowledge,
        model_manager=agent.model_manager,
        prompt_registry=my_registry,   # shared across runs
        learning_store=my_store,       # shared across runs
    )
    result = engine.reflect(context)
    print(result.critic.summary)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from smartagent.logs.logger import get_logger
from smartagent.reflection.critic import Critic, CriticReport
from smartagent.reflection.execution_analyzer import ExecutionAnalyzer, ExecutionReport
from smartagent.reflection.improvement_planner import ImprovementPlan, ImprovementPlanner
from smartagent.reflection.learning_store import LearningStore
from smartagent.reflection.prompt_registry import PromptRegistry

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext

logger = get_logger(__name__)


@dataclass
class ReflectionResult:
    """All outputs from one reflection cycle."""

    report: ExecutionReport
    critic: CriticReport
    plan: ImprovementPlan
    knowledge_proposals_added: int = 0
    memory_entries_added: int = 0
    prompt_versions_added: int = 0
    error: str = ""


class ReflectionEngine:
    """
    Orchestrates all reflection and learning steps post-execution.

    Args:
        memory_manager:    For persisting lessons and analytics records.
        knowledge_manager: For proposing new concepts to the knowledge inbox.
        model_manager:     For LLM-enriched critic evaluation (optional).
        prompt_registry:   Versioned prompt store (shared across runs).
        learning_store:    Analytics accumulator (shared across runs).
    """

    def __init__(
        self,
        memory_manager: Any | None = None,
        knowledge_manager: Any | None = None,
        model_manager: Any | None = None,
        prompt_registry: PromptRegistry | None = None,
        learning_store: LearningStore | None = None,
    ) -> None:
        self._memory_manager    = memory_manager
        self._knowledge_manager = knowledge_manager
        self._model_manager     = model_manager
        self._prompt_registry   = prompt_registry or PromptRegistry()
        self._learning_store    = learning_store or LearningStore(memory_manager)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def prompt_registry(self) -> PromptRegistry:
        return self._prompt_registry

    @property
    def learning_store(self) -> LearningStore:
        return self._learning_store

    def reflect(self, context: "ExecutionContext") -> ReflectionResult:
        """
        Run the full reflection cycle on *context*.

        Returns a ``ReflectionResult`` regardless of any internal errors.
        Best-effort: individual step failures do not abort the cycle.
        """
        try:
            return self._run_reflection(context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReflectionEngine: reflection aborted: %s", exc)
            # Return a minimal result so callers always get something
            from smartagent.reflection.execution_analyzer import ExecutionReport
            empty_report = ExecutionReport(
                goal=context.goal, plan_id=context.plan_id,
                state=context.state.value, timestamp="",
                task_count=0, completed_count=0, failed_count=0,
                avg_confidence=0.0, total_time=0.0, success_rate=0.0,
            )
            from smartagent.reflection.critic import CriticReport
            from smartagent.reflection.improvement_planner import ImprovementPlan
            return ReflectionResult(
                report=empty_report,
                critic=CriticReport(),
                plan=ImprovementPlan(),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _run_reflection(self, context: "ExecutionContext") -> ReflectionResult:
        logger.info(
            "ReflectionEngine: reflecting on goal=%r  state=%s",
            context.goal, context.state.value,
        )

        # Step 1: Analyze
        report = ExecutionAnalyzer().analyze(context)

        # Step 2: Critique
        critic = Critic(self._model_manager).evaluate(report)
        logger.info(
            "ReflectionEngine: critique complete  score=%.0f%%  "
            "succeeded=%d  failed=%d",
            critic.overall_score * 100,
            len(critic.what_succeeded),
            len(critic.what_failed),
        )

        # Step 3: Plan improvements
        plan = ImprovementPlanner().plan(critic, report)

        # Step 4: Update confidence engine & learning store
        knowledge_count = 0
        try:
            self._learning_store.record_execution(
                report=report,
                critic_report=critic,
                knowledge_proposals=len(plan.knowledge_proposals),
                reflection_done=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("ReflectionEngine: learning_store.record failed: %s", exc)

        # Step 5: Persist memory entries
        memory_count = 0
        for entry in plan.memory_entries:
            try:
                if self._memory_manager:
                    self._memory_manager.remember(
                        content=entry.content,
                        category=entry.category,
                        tags=entry.tags,
                    )
                    memory_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("ReflectionEngine: memory.remember failed: %s", exc)

        # Step 6: Propose knowledge concepts
        for proposal in plan.knowledge_proposals:
            try:
                if self._knowledge_manager:
                    self._knowledge_manager.propose_concept(
                        title=proposal.title,
                        description=proposal.description,
                        category=proposal.category,
                        tags=proposal.tags,
                    )
                    knowledge_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("ReflectionEngine: knowledge.propose failed: %s", exc)

        # Step 7: Update prompt registry
        prompt_count = 0
        for pi in plan.prompt_improvements:
            try:
                # Get the current prompt for this worker (if any)
                current = self._prompt_registry.current_prompt(pi.worker_name)
                new_content = (current or "") + pi.improved_prompt
                self._prompt_registry.add_version(
                    worker_name=pi.worker_name,
                    content=new_content,
                    reason=pi.hint,
                    score_improvement=pi.estimated_gain,
                )
                prompt_count += 1
                logger.info(
                    "ReflectionEngine: improved prompt for '%s' (v%d)",
                    pi.worker_name,
                    self._prompt_registry.version_count(pi.worker_name),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "ReflectionEngine: prompt registry update failed: %s", exc
                )

        # Step 8: Inject improved prompts into future context metadata
        # (done by storing the registry on the context for next run)
        try:
            context.metadata["prompt_registry"] = self._prompt_registry
            context.metadata["system_prompts"] = (
                self._prompt_registry.as_metadata_dict()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("ReflectionEngine: prompt metadata update failed: %s", exc)

        result = ReflectionResult(
            report=report,
            critic=critic,
            plan=plan,
            knowledge_proposals_added=knowledge_count,
            memory_entries_added=memory_count,
            prompt_versions_added=prompt_count,
        )
        logger.info(
            "ReflectionEngine: done  memory=%d  knowledge=%d  prompts=%d",
            memory_count, knowledge_count, prompt_count,
        )
        return result

    # ------------------------------------------------------------------
    # Self-evaluation queries (for console commands)
    # ------------------------------------------------------------------

    def what_did_i_learn(self) -> str:
        """Return a prose answer to 'What did I learn?' from recent executions."""
        records = self._learning_store.execution_history()
        if not records:
            return "No executions recorded yet."
        recent = records[-3:]
        parts = [f"Based on my last {len(recent)} execution(s):\n"]
        for rec in recent:
            parts.append(
                f"  • '{rec.goal[:50]}' — "
                f"{rec.state}, score {rec.overall_score:.0%}"
            )
        trend = self._learning_store.confidence_trend()
        parts.append(f"\nMy confidence is {trend}.")
        return "\n".join(parts)

    def best_worker(self) -> str:
        name = self._learning_store.top_worker()
        if not name:
            return "Not enough data to determine best worker."
        stats = self._learning_store.worker_stats().get(name, {})
        return (
            f"{name} is currently my best worker "
            f"(avg confidence: {stats.get('avg_confidence', 0):.0%}, "
            f"success rate: {stats.get('success_rate', 0):.0%})."
        )

    def failing_tools(self) -> str:
        stats = self._learning_store.tool_stats()
        if not stats:
            return "No tool usage recorded yet."
        failing = [
            f"{tid} ({d.get('success_rate', 0):.0%})"
            for tid, d in stats.items()
            if d.get("success_rate", 1.0) < 0.8
        ]
        if not failing:
            return "All tools are performing reliably (≥80% success rate)."
        return "Tools with below-80% success rate: " + ", ".join(failing) + "."

    def missing_knowledge(self) -> str:
        """Summarise recurring knowledge gaps from recent reflections."""
        records = self._learning_store.execution_history()
        low_conf = [r for r in records if r.avg_confidence < 0.5]
        if not low_conf:
            return "No significant knowledge gaps detected."
        return (
            f"{len(low_conf)} of {len(records)} execution(s) had low confidence "
            "— this may indicate missing domain-specific knowledge. "
            "Check the Knowledge inbox for proposed concepts."
        )
