"""
ceo_agent.py — Top-level multi-agent orchestrator for Milestone 17.

The ``CEOAgent`` sits above the existing ``Executive`` layer:

    CEOAgent
      └─ TeamPlanner     → MultiAgentPlan (one assignment per team)
      └─ TeamRunner × N  → TeamResult × N  (one Orchestrator per team)
      └─ MultiAgentResult

Context chaining
────────────────
After each team finishes, its summary is appended to a rolling
``prior_context`` string that is passed to every subsequent team.  This lets
the documentation team reference what the engineering team built, and the QA
team know what the engineering team produced, without any shared state.

Usage::

    ceo = CEOAgent.with_agent(agent)
    result = ceo.execute("Build a FastAPI weather service with OpenWeatherMap")
    print(result.as_display_lines())
"""

from __future__ import annotations

import time
from typing import Any, Optional

from smartagent.logs.logger import get_logger
from smartagent.multi_agent.team import TeamRegistry
from smartagent.multi_agent.team_assignment import MultiAgentPlan
from smartagent.multi_agent.team_planner import TeamPlanner
from smartagent.multi_agent.team_result import MultiAgentResult, TeamResult
from smartagent.multi_agent.team_runner import TeamRunner

logger = get_logger(__name__)


class CEOAgent:
    """
    Multi-agent coordinator: decomposes goals into team assignments and
    runs each team sequentially with context chaining.

    Args:
        team_registry:  Registry of available teams.
        team_planner:   Decomposes goals into ``MultiAgentPlan``.
        services:       AI service dict forwarded to every ``TeamRunner``
                        (keys: model_manager, memory_manager, …).
        use_team_registry: Restrict each team's workers to its task types.
        use_ai:         Enable AI-assisted decomposition in the TeamPlanner.
        show_progress:  Forward to schedulers inside TeamRunners.
    """

    def __init__(
        self,
        team_registry:      TeamRegistry | None = None,
        team_planner:       TeamPlanner | None = None,
        services:           dict[str, Any] | None = None,
        use_team_registry:  bool = True,
        use_ai:             bool = False,
        show_progress:      bool = False,
    ) -> None:
        self._team_registry     = team_registry or TeamRegistry()
        self._services          = services or {}
        self._use_team_registry = use_team_registry
        self._show_progress     = show_progress
        self._team_planner      = team_planner or TeamPlanner(
            team_registry=self._team_registry,
            model_manager=self._services.get("model_manager"),
            use_ai=use_ai,
        )
        self._last_plan:   Optional[MultiAgentPlan]   = None
        self._last_result: Optional[MultiAgentResult] = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_agent(cls, agent: Any) -> "CEOAgent":
        """
        Build a fully-wired ``CEOAgent`` from a live ``SmartAgent`` instance.

        Extracts all services via ``getattr`` — any that are missing are
        silently skipped.
        """
        services = {
            "model_manager":    getattr(agent, "model_manager",    None),
            "memory_manager":   getattr(agent, "memory",           None),
            "knowledge_manager":getattr(agent, "knowledge",        None),
            "settings":         getattr(agent, "settings",         None),
            "tool_engine":      getattr(agent, "tool_engine",      None),
            "event_bus":        getattr(agent, "events",           None),
            "reflection_engine":getattr(agent, "reflection_engine",None),
            "workspace_manager":getattr(agent, "workspace_manager",None),
        }
        return cls(services=services)

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def execute(self, goal: str) -> MultiAgentResult:
        """
        Full pipeline: plan → run all teams → aggregate results.

        Teams run sequentially; each team receives the aggregated output of
        all previous teams as ``prior_context``.

        Returns a ``MultiAgentResult`` even on partial or total failure.
        """
        logger.info("CEOAgent: starting execution  goal=%r", goal[:80])
        plan = self._team_planner.plan(goal)
        self._last_plan = plan
        return self._execute_plan(plan)

    def preview_plan(self, goal: str) -> MultiAgentPlan:
        """
        Decompose *goal* into a ``MultiAgentPlan`` WITHOUT executing it.

        Stores the plan so ``run()`` can use it.
        """
        plan = self._team_planner.plan(goal)
        self._last_plan = plan
        return plan

    def run(self) -> MultiAgentResult:
        """
        Execute the plan from the most recent ``preview_plan()`` call.

        Raises:
            RuntimeError: If no plan has been created yet.
        """
        if self._last_plan is None:
            raise RuntimeError(
                "No plan to run.  Call preview_plan(<goal>) first."
            )
        return self._execute_plan(self._last_plan)

    # ------------------------------------------------------------------
    # Team execution
    # ------------------------------------------------------------------

    def _execute_plan(self, plan: MultiAgentPlan) -> MultiAgentResult:
        t0 = time.monotonic()
        team_results: list[TeamResult] = []
        prior_context = ""

        for assignment in plan.assignments:
            team = self._team_registry.get(assignment.team_name)
            if team is None:
                logger.warning(
                    "CEOAgent: team %r not found — skipping",
                    assignment.team_name,
                )
                team_results.append(TeamResult(
                    team_name=assignment.team_name,
                    goal=assignment.goal,
                    state="failed",
                    summary=f"Team {assignment.team_name!r} is not registered.",
                    error=f"Unknown team: {assignment.team_name}",
                ))
                continue

            runner = TeamRunner(
                team=team,
                services=self._services,
                use_team_registry=self._use_team_registry,
                show_progress=self._show_progress,
            )
            result = runner.run(assignment, prior_context=prior_context)
            team_results.append(result)

            # Chain: give the next team the prior team's summary
            if result.summary:
                prior_context = (
                    prior_context
                    + f"\n\n--- {team.name.title()} Team Results ---\n"
                    + result.summary
                ).strip()

            logger.info(
                "CEOAgent: team %r done  state=%s  %.1fs",
                assignment.team_name, result.state, result.duration,
            )

        duration = time.monotonic() - t0
        result = self._build_result(goal=plan.goal, plan_id=plan.plan_id,
                                    team_results=team_results, duration=duration)
        self._last_result = result
        logger.info(
            "CEOAgent: complete  state=%s  teams=%d/%d  %.1fs",
            result.overall_state, result.completed_teams, result.team_count, duration,
        )
        return result

    # ------------------------------------------------------------------
    # Result aggregation
    # ------------------------------------------------------------------

    def _build_result(
        self,
        goal: str,
        plan_id: str,
        team_results: list[TeamResult],
        duration: float,
    ) -> MultiAgentResult:
        n_completed = sum(1 for r in team_results if r.state == "completed")
        n_failed    = sum(1 for r in team_results if r.state == "failed")
        total       = len(team_results)

        if n_failed == total:
            overall = "failed"
        elif n_failed > 0 or any(r.state == "partial" for r in team_results):
            overall = "partial"
        else:
            overall = "completed"

        # Build a CEO-level prose summary from all team summaries
        summary_parts = [f"Multi-agent execution for: {goal}", ""]
        for r in team_results:
            icon = {"completed": "✓", "partial": "~", "failed": "✗"}.get(r.state, "?")
            summary_parts.append(
                f"{icon} {r.team_name.title()} Team: {r.state} "
                f"({r.completed}/{r.task_count} tasks, {r.duration:.1f}s)"
            )
        summary_parts += [
            "",
            f"Overall: {n_completed}/{total} teams completed in {duration:.1f}s.",
        ]

        return MultiAgentResult(
            goal=goal,
            plan_id=plan_id,
            team_results=team_results,
            overall_state=overall,
            summary="\n".join(summary_parts),
            duration=duration,
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def team_registry(self) -> TeamRegistry:
        return self._team_registry

    @property
    def last_plan(self) -> Optional[MultiAgentPlan]:
        return self._last_plan

    @property
    def last_result(self) -> Optional[MultiAgentResult]:
        return self._last_result
