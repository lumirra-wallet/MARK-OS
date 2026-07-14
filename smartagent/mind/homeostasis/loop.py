"""
DigitalHomeostasisLoop — Milestone 6, Part 13.

Instead of only ever reacting to user input, MARK should periodically ask
itself: am I healthy, am I overloaded, am I making progress, do my goals
still match my mission, is anything failing, should I notify the owner.

Modeled as an explicit `tick()` a caller invokes once per evaluation cycle
— real periodic scheduling belongs to `smartagent.automation` (out of
scope here; see the Mind package docstring), so this stays a pure,
deterministic, directly testable primitive rather than a background thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smartagent.logs.logger import get_logger
from smartagent.mind.homeostasis.health_metrics import HealthMetrics
from smartagent.mind.homeostasis.homeostasis_engine import HomeostasisEngine

logger = get_logger(__name__)


@dataclass
class HomeostasisTickResult:
    """The answers to one homeostasis evaluation cycle."""

    is_healthy: bool
    is_overloaded: bool
    is_making_progress: bool
    goals_match_mission: bool
    anything_failing: bool
    should_notify_owner: bool
    notes: list[str] = field(default_factory=list)


class DigitalHomeostasisLoop:
    """
    Runs one self-evaluation cycle at a time via `tick()`.

    Args:
        homeostasis_engine: Supplies the health score/band for this cycle.
    """

    def __init__(self, homeostasis_engine: HomeostasisEngine) -> None:
        self.homeostasis_engine = homeostasis_engine

    def tick(
        self,
        metrics: HealthMetrics,
        progress_made: bool = True,
        goals: list[str] | None = None,
        mission_keywords: list[str] | None = None,
        recent_failures: int = 0,
    ) -> HomeostasisTickResult:
        """
        Run one evaluation cycle and return a `HomeostasisTickResult`.

        Args:
            metrics: Current `HealthMetrics` snapshot to score.
            progress_made: Whether any goal/task advanced since the last tick.
            goals: Current goal names, used for the (best-effort, keyword-based)
                "do my goals still match my mission" check.
            mission_keywords: Words/phrases drawn from the mission statement to
                match goal names against. If omitted, the check always passes
                (there's nothing to compare against).
            recent_failures: Count of failures observed since the last tick.
        """
        report = self.homeostasis_engine.check(metrics)
        is_healthy = report.band == "healthy"
        is_overloaded = report.band == "critical" or metrics.task_load >= 0.9 or metrics.queue_length > 20
        anything_failing = recent_failures > 0 or metrics.errors > 0 or not metrics.model_availability

        goals_match_mission = True
        if goals and mission_keywords:
            goals_match_mission = any(
                keyword.lower() in goal.lower() for goal in goals for keyword in mission_keywords
            )

        should_notify_owner = is_overloaded or (report.band == "critical") or (anything_failing and recent_failures > 2)

        notes: list[str] = []
        if is_overloaded:
            notes.append("Task load or queue length is critically high.")
        if not progress_made:
            notes.append("No progress detected since the last cycle.")
        if not goals_match_mission:
            notes.append("Current goals do not appear to reference the mission.")
        if anything_failing:
            notes.append(f"{recent_failures} recent failure(s) and {metrics.errors} recorded error(s).")

        result = HomeostasisTickResult(
            is_healthy=is_healthy,
            is_overloaded=is_overloaded,
            is_making_progress=progress_made,
            goals_match_mission=goals_match_mission,
            anything_failing=anything_failing,
            should_notify_owner=should_notify_owner,
            notes=notes,
        )
        logger.info(
            "Homeostasis tick: healthy=%s overloaded=%s progress=%s failing=%s notify=%s",
            is_healthy,
            is_overloaded,
            progress_made,
            anything_failing,
            should_notify_owner,
        )
        return result
