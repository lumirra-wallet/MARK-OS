"""
HomeostasisEngine — Milestone 6, Part 8.

MARK's internal health monitoring system: takes a `HealthMetrics` snapshot,
scores it, and generates a `HealthChanged` event whenever the score crosses
a configured threshold (e.g. dropping from "healthy" into "degraded"),
rather than on every single check — otherwise every tick would spam an event.
"""

from __future__ import annotations

from dataclasses import dataclass

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger
from smartagent.mind.homeostasis.health_metrics import HealthMetrics

logger = get_logger(__name__)

DEGRADED_THRESHOLD = 0.6
CRITICAL_THRESHOLD = 0.3


def _band(score: float) -> str:
    if score < CRITICAL_THRESHOLD:
        return "critical"
    if score < DEGRADED_THRESHOLD:
        return "degraded"
    return "healthy"


@dataclass
class HealthReport:
    """The result of one `HomeostasisEngine.check()` call."""

    metrics: HealthMetrics
    score: float
    band: str


class HomeostasisEngine:
    """
    Scores `HealthMetrics` snapshots and reports threshold-crossing changes.

    Args:
        event_bus: Optional bus to publish `HealthChanged` onto when the
            health band (healthy/degraded/critical) changes from the
            previous check.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.events = event_bus
        self._last_band: str | None = None
        self._last_report: HealthReport | None = None

    def check(self, metrics: HealthMetrics) -> HealthReport:
        """Score `metrics`, publish `HealthChanged` if the health band changed, and return the report."""
        score = metrics.score()
        band = _band(score)
        report = HealthReport(metrics=metrics, score=score, band=band)
        self._last_report = report

        if band != self._last_band:
            logger.info("Health band changed: %s -> %s (score=%.2f)", self._last_band, band, score)
            if self.events is not None:
                self.events.publish(Events.HEALTH_CHANGED, previous_band=self._last_band, band=band, score=score)
            self._last_band = band

        return report

    def last_report(self) -> HealthReport | None:
        """The most recent `HealthReport`, or `None` before the first `check()`."""
        return self._last_report

    def is_healthy(self) -> bool:
        """Whether the most recent check landed in the "healthy" band. `True` before any check."""
        return self._last_band in (None, "healthy")
