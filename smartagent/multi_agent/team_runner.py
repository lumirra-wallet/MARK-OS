"""
team_runner.py — Executes one team's assignment via a scoped Orchestrator (M17).

``TeamRunner`` wraps a private ``Orchestrator`` configured with a worker
registry filtered to the team's task types.  It enriches the execution context
with:

  * ``"team"``          — the ``Team`` object
  * ``"team_name"``     — team name string
  * ``"prior_context"`` — aggregated outputs of teams that ran before this one

After the orchestrator returns, ``TeamRunner`` converts the ``ExecutionContext``
into a ``TeamResult`` and hands it back to the ``CEOAgent``.
"""

from __future__ import annotations

import time
from typing import Any

from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.orchestrator import Orchestrator
from smartagent.logs.logger import get_logger
from smartagent.multi_agent.team import Team
from smartagent.multi_agent.team_assignment import TeamAssignment
from smartagent.multi_agent.team_result import TeamResult

logger = get_logger(__name__)


class TeamRunner:
    """
    Executes a single ``TeamAssignment`` through a private ``Orchestrator``.

    Args:
        team:              The ``Team`` that owns this runner.
        services:          Dict of AI services to inject (same keys as the
                           Orchestrator expects: ``model_manager``,
                           ``memory_manager``, ``knowledge_manager``,
                           ``settings``, ``tool_engine``, ``event_bus``,
                           ``reflection_engine``, ``workspace_manager``).
        use_team_registry: If True (default) restrict workers to the team's
                           task types.  If False use the full default registry.
        show_progress:     Forward to the underlying Scheduler.
    """

    def __init__(
        self,
        team: Team,
        services: dict[str, Any] | None = None,
        use_team_registry: bool = True,
        show_progress: bool = False,
    ) -> None:
        self._team = team
        self._services = services or {}
        self._show_progress = show_progress

        # Build a registry filtered to this team's task types
        if use_team_registry:
            from smartagent.executive.worker_registry import WorkerRegistry, build_default_registry
            from smartagent.executive.task import TaskType
            full = build_default_registry()
            registry = WorkerRegistry()
            for tt in team.task_types:
                worker = full.get(tt)
                if worker is not None:
                    registry.register(tt, worker)
            # Always keep GENERIC as a fallback
            generic = full.get(TaskType.GENERIC)
            if generic is not None:
                registry.register(TaskType.GENERIC, generic)
        else:
            from smartagent.executive.worker_registry import build_default_registry
            registry = build_default_registry()

        self._orchestrator = Orchestrator(
            worker_registry=registry,
            model_manager=self._services.get("model_manager"),
            memory_manager=self._services.get("memory_manager"),
            knowledge_manager=self._services.get("knowledge_manager"),
            settings=self._services.get("settings"),
            tool_engine=self._services.get("tool_engine"),
            event_bus=self._services.get("event_bus"),
            reflection_engine=self._services.get("reflection_engine"),
            workspace_manager=self._services.get("workspace_manager"),
        )
        logger.debug(
            "TeamRunner(%r): orchestrator ready with %d worker mappings",
            team.name, registry.count(),
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        assignment: TeamAssignment,
        prior_context: str = "",
    ) -> TeamResult:
        """
        Execute *assignment* and return a ``TeamResult``.

        Args:
            assignment:     The CEO instruction for this team.
            prior_context:  Aggregated output text from teams that ran before
                            this one (injected into context.metadata).
        """
        logger.info(
            "TeamRunner(%r): starting  goal=%r",
            self._team.name, assignment.goal[:80],
        )
        t0 = time.monotonic()

        # Inject extra metadata the orchestrator will forward to workers
        self._orchestrator._extra_metadata = {
            "team":          self._team,
            "team_name":     self._team.name,
            "prior_context": (assignment.context + "\n" + prior_context).strip(),
        }

        try:
            context = self._orchestrator.execute_goal(assignment.goal)
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - t0
            logger.error(
                "TeamRunner(%r): orchestrator raised: %s", self._team.name, exc
            )
            return TeamResult(
                team_name=self._team.name,
                goal=assignment.goal,
                state="failed",
                summary=f"Team run failed: {exc}",
                duration=duration,
                error=str(exc),
            )

        duration = time.monotonic() - t0
        result   = self._build_result(context, duration)
        logger.info(
            "TeamRunner(%r): done  state=%s  tasks=%d/%d  %.1fs",
            self._team.name, result.state,
            result.completed, result.task_count, duration,
        )
        return result

    # ------------------------------------------------------------------
    # Result construction
    # ------------------------------------------------------------------

    def _build_result(self, context: Any, duration: float) -> TeamResult:
        """Convert an ``ExecutionContext`` to a ``TeamResult``."""
        state_val = getattr(context, "state", None)
        exec_state = state_val.value if hasattr(state_val, "value") else str(state_val)

        if exec_state == ExecutionState.COMPLETED.value:
            state = "completed"
        elif exec_state in (ExecutionState.FAILED.value, ExecutionState.CANCELLED.value):
            state = "failed"
        else:
            state = "partial"

        # Collect key task outputs as bullet points
        outputs: list[str] = []
        for task in context.task_graph.all_tasks():
            if task.result:
                preview = task.result[:200]
                outputs.append(f"[{task.task_type.value}] {task.title}: {preview}")

        summary = self._build_summary(context, state)

        return TeamResult(
            team_name=self._team.name,
            goal=context.goal,
            state=state,
            summary=summary,
            outputs=outputs,
            task_count=getattr(context, "task_count", 0),
            completed=getattr(context, "completed_count", 0),
            failed=getattr(context, "failed_count", 0),
            duration=duration,
        )

    def _build_summary(self, context: Any, state: str) -> str:
        """Build a one-paragraph prose summary of what the team produced."""
        lines = [
            f"{self._team.emoji} {self._team.name.title()} Team — {state}",
            f"Goal: {context.goal}",
        ]
        completed = getattr(context, "completed_count", 0)
        total     = getattr(context, "task_count", 0)
        lines.append(f"Completed {completed}/{total} tasks.")
        # Include the result of the last completed task as a representative output
        completed_tasks = [
            t for t in context.task_graph.all_tasks()
            if t.result and t.status.value == "completed"
        ]
        if completed_tasks:
            last = completed_tasks[-1]
            preview = last.result[:300] + "…" if len(last.result) > 300 else last.result
            lines.append(f"Final output: {preview}")
        return "\n".join(lines)
