"""
ConfidenceEngine — Milestone 6, Part 7.

Every decision should receive a confidence score, along with the reasoning
behind it. The core rule: **never fabricate certainty** — the score is a
transparent function of evidence, conflicts, missing information, and
unknowns, never a flat default. `ConfidenceEngine` also keeps a bounded
history so trends ("confidence has been dropping") are inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_MAX_HISTORY = 50


@dataclass
class ConfidenceAssessment:
    """The full confidence picture behind one decision — never just a bare number."""

    confidence: float
    reason: str
    evidence: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class ConfidenceEngine:
    """
    Scores decisions and tracks a bounded history of past assessments.

    Scoring heuristic (deliberately simple and transparent, not learned):
    start from a base confidence proportional to how much evidence is
    supplied, then subtract a penalty per conflict, per missing piece of
    information, and per unknown. Clamped to [0.0, 1.0].
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.events = event_bus
        self._history: list[ConfidenceAssessment] = []

    def score(
        self,
        reason: str,
        evidence: list[str] | None = None,
        conflicts: list[str] | None = None,
        missing_information: list[str] | None = None,
        unknowns: list[str] | None = None,
    ) -> ConfidenceAssessment:
        """Compute a `ConfidenceAssessment`, record it, and publish `ConfidenceChanged`."""
        evidence = evidence or []
        conflicts = conflicts or []
        missing_information = missing_information or []
        unknowns = unknowns or []

        base = min(0.5 + 0.1 * len(evidence), 1.0)
        penalty = 0.2 * len(conflicts) + 0.1 * len(missing_information) + 0.1 * len(unknowns)
        confidence = max(0.0, min(1.0, base - penalty))

        recommendations: list[str] = []
        if conflicts:
            recommendations.append("Resolve conflicting evidence before acting.")
        if missing_information:
            recommendations.append("Gather the missing information before committing.")
        if unknowns:
            recommendations.append("Flag remaining unknowns to the owner.")
        if not evidence:
            recommendations.append("No supporting evidence was supplied — treat this as a guess.")

        assessment = ConfidenceAssessment(
            confidence=confidence,
            reason=reason,
            evidence=evidence,
            conflicts=conflicts,
            missing_information=missing_information,
            unknowns=unknowns,
            recommendations=recommendations,
        )
        self._history.append(assessment)
        del self._history[:-_MAX_HISTORY]

        logger.info("Confidence scored: %.2f (%s)", confidence, reason)
        if self.events is not None:
            self.events.publish(Events.CONFIDENCE_CHANGED, confidence=confidence, reason=reason)
        return assessment

    def history(self) -> list[ConfidenceAssessment]:
        """Every assessment made so far, oldest first."""
        return list(self._history)

    def latest(self) -> ConfidenceAssessment | None:
        """The most recent assessment, or `None` if `score()` has never been called."""
        return self._history[-1] if self._history else None
