"""
LongRunningEngine — Milestone 23: Long Running Execution.

Wraps the CEO multi-agent pipeline with:
  - Structured ``CompletionReport`` output (completed / failed / remaining)
  - Per-phase timing
  - Optional progress callback (``on_phase_done``)
  - Optional ProjectMemory context injection
  - Session summary persisted to memory

Usage::

    engine = LongRunningEngine.with_agent(agent)
    report = engine.run("Build SaaS")
    print("\\n".join(report.as_display_lines()))

With a progress callback::

    def on_progress(phase: PhaseResult, report: CompletionReport) -> None:
        print(f"{phase.icon} {phase.name}")

    report = engine.run("Build SaaS", on_phase_done=on_progress)
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from smartagent.logs.logger import get_logger
from smartagent.long_running.completion_report import CompletionReport, PhaseResult

logger = get_logger(__name__)

# Type alias for the optional progress callback
PhaseCallback = Callable[["PhaseResult", "CompletionReport"], None]


class LongRunningEngine:
    """
    Orchestrates a long CEO execution run with rich result tracking.

    Args:
        ceo_agent:       :class:`~smartagent.multi_agent.ceo_agent.CEOAgent` instance.
        memory_manager:  Optional — persists the completion summary.
        project_memory:  Optional — injects project context before execution.
        max_phases:      Cap on team phases to avoid runaway runs.  Default 20.
    """

    def __init__(
        self,
        ceo_agent: Any,
        memory_manager: Any | None = None,
        project_memory: Any | None = None,
        max_phases: int = 20,
    ) -> None:
        self._ceo = ceo_agent
        self._memory = memory_manager
        self._project_memory = project_memory
        self._max_phases = max_phases

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_agent(cls, agent: Any) -> "LongRunningEngine":
        """Build a fully-wired engine from a live ``SmartAgent``."""
        return cls(
            ceo_agent=getattr(agent, "ceo", None),
            memory_manager=getattr(agent, "memory", None),
            project_memory=getattr(agent, "project_memory", None),
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def run(
        self,
        goal: str,
        on_phase_done: Optional[PhaseCallback] = None,
        project_name: str = "",
    ) -> CompletionReport:
        """
        Execute *goal* through the CEO pipeline and return a
        :class:`CompletionReport`.

        Args:
            goal:          Natural-language goal string.
            on_phase_done: Optional callback invoked after each phase.
            project_name:  Load this project profile from ProjectMemory (if set).

        Returns:
            A complete :class:`CompletionReport` — even on failure.
        """
        if self._ceo is None:
            return CompletionReport(
                goal=goal,
                failed=[PhaseResult(name="CEO", success=False, summary="CEOAgent not available.")],
                success=False,
            )

        report = CompletionReport(goal=goal)
        t0 = time.monotonic()

        logger.info("LongRunningEngine: starting  goal=%r", goal[:80])

        # Inject project memory context if available
        if project_name and self._project_memory is not None:
            try:
                profile = self._project_memory.load(project_name)
                enriched_goal = (
                    goal
                    + "\n\n[Project Context]\n"
                    + profile.as_ai_context()
                )
            except Exception:
                enriched_goal = goal
        else:
            enriched_goal = goal

        try:
            multi_result = self._ceo.execute(enriched_goal)
        except Exception as exc:
            logger.exception("LongRunningEngine: CEO execution raised unexpectedly")
            report.failed.append(PhaseResult(
                name="CEO Pipeline",
                success=False,
                summary=str(exc),
            ))
            report.total_elapsed = time.monotonic() - t0
            return report

        # Translate MultiAgentResult → CompletionReport phases
        report = self._build_report(goal, multi_result, t0)
        report.total_elapsed = time.monotonic() - t0

        # Fire callbacks per phase (in order)
        if on_phase_done is not None:
            for phase in report.completed + report.failed:
                try:
                    on_phase_done(phase, report)
                except Exception:
                    pass

        # Persist summary to memory
        self._persist_summary(goal, report)

        logger.info(
            "LongRunningEngine: done  completed=%d  failed=%d  elapsed=%.1fs",
            len(report.completed), len(report.failed), report.total_elapsed,
        )
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_report(
        self,
        goal: str,
        multi_result: Any,
        t0: float,
    ) -> CompletionReport:
        """Translate a ``MultiAgentResult`` into a ``CompletionReport``."""
        report = CompletionReport(goal=goal)

        team_results = getattr(multi_result, "team_results", [])
        for tr in team_results[:self._max_phases]:
            elapsed = getattr(tr, "elapsed", 0.0)
            summary = getattr(tr, "summary", "")
            state = str(getattr(tr, "state", ""))
            team = getattr(tr, "team_name", "")
            name = _team_to_phase_name(team)

            success = state.lower() in ("completed", "success", "done")
            phase = PhaseResult(
                name=name,
                success=success,
                summary=(summary or "")[:200],
                elapsed=elapsed,
                team=team,
            )
            if success:
                report.completed.append(phase)
            else:
                report.failed.append(phase)

        # Carry the last team's summary as the overall report summary
        if team_results:
            last = team_results[-1]
            report.summary = getattr(last, "summary", "") or ""

        report.success = bool(report.completed) and not report.failed
        return report

    def _persist_summary(self, goal: str, report: CompletionReport) -> None:
        """Optionally save a summary entry to MemoryManager."""
        if self._memory is None:
            return
        try:
            short = report.as_short_summary()
            entry = f"Long-run completed: {goal[:60]}\n{short}"
            self._memory.remember(entry, category="Executive")
        except Exception as exc:
            logger.debug("LongRunningEngine: could not persist summary: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _team_to_phase_name(team: str) -> str:
    """Map a team name to a human-readable phase label."""
    mapping = {
        "research":     "Research",
        "engineering":  "Backend",
        "qa":           "Tests",
        "documentation":"Docs",
        "design":       "Frontend",
        "devops":       "Deployment",
        "security":     "Security",
    }
    return mapping.get(team.lower(), team.title() if team else "Unknown")
