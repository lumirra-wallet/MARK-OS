"""
Confidence Engine — transparent, evidence-based confidence scoring.

Every concept receives an aggregate confidence score [0.0, 1.0] computed
from evidence quality, source reliability, contradictions, verification
status, age, and the number of supporting sources. The scoring is fully
deterministic and auditable — no black-box AI judgements.

Design principle: confidence scores are *derived*, not asserted. Callers
may supply a manual adjustment, but the engine always explains why a
score is what it is via `ConfidenceFactors`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.knowledge.concepts.concept import Concept
    from smartagent.knowledge.evidence.evidence import Evidence
    from smartagent.knowledge.sources.source import Source


@dataclass
class ConfidenceFactors:
    """
    Breakdown of the components that make up a concept's confidence score.

    Useful for auditing and explaining why a concept's confidence is
    what it is — MARK should never produce scores without being able
    to explain them.
    """

    evidence_score: float = 0.0       # Weighted average evidence strength × confidence
    source_score: float = 0.0         # Average reliability of linked sources
    contradiction_penalty: float = 0.0  # Deducted per unresolved contradiction
    verification_bonus: float = 0.0   # Added for verified concepts
    age_penalty: float = 0.0          # Slight decay for very old, unverified concepts
    source_count_bonus: float = 0.0   # Bonus for multiple corroborating sources
    manual_adjustment: float = 0.0    # Owner-supplied override delta
    final_score: float = 0.0          # Clamped result in [0.0, 1.0]
    notes: list[str] = field(default_factory=list)


class ConfidenceEngine:
    """
    Computes and explains concept confidence scores from evidence and sources.

    All arithmetic is explicit, weighted, and documented here. There are
    no magic numbers hidden in helper functions — every constant is named
    and explained.
    """

    # --- Tuning constants ---

    # Maximum bonus from having many corroborating sources (caps at 5 sources).
    _MAX_SOURCE_BONUS = 0.1
    _SOURCE_BONUS_CAP = 5

    # Penalty per unresolved contradiction (capped so contradictions alone
    # can never bring confidence below 0).
    _CONTRADICTION_PENALTY = 0.15
    _MAX_CONTRADICTION_PENALTY = 0.6

    # Bonus for a concept that has been manually verified by Mr. Smart.
    _VERIFICATION_BONUS = 0.1

    # Age penalty: starts after 365 days for unverified concepts;
    # max penalty = 0.15 (so a 2-year-old unverified claim isn't fully
    # discredited, just nudged lower).
    _AGE_PENALTY_START_DAYS = 365
    _MAX_AGE_PENALTY = 0.15

    def score(
        self,
        concept: "Concept",
        evidence_list: list["Evidence"] | None = None,
        sources: list["Source"] | None = None,
        manual_adjustment: float = 0.0,
    ) -> ConfidenceFactors:
        """
        Compute the full confidence breakdown for `concept`.

        Args:
            concept: The concept to score.
            evidence_list: Evidence records linked to this concept. Pass an
                empty list (not None) if the caller has confirmed there is
                no evidence (vs. just not loaded it yet).
            sources: Source records linked to this concept.
            manual_adjustment: Owner-supplied delta applied after all other
                factors. Clamped so the final score stays in [0.0, 1.0].

        Returns:
            A `ConfidenceFactors` instance with the breakdown and final score.
        """
        factors = ConfidenceFactors(manual_adjustment=manual_adjustment)

        # 1. Evidence quality
        if evidence_list:
            # Weight each evidence item by its own confidence × strength.
            weighted = [e.strength * e.confidence for e in evidence_list]
            factors.evidence_score = sum(weighted) / len(weighted)
            factors.notes.append(
                f"Evidence score {factors.evidence_score:.2f} from {len(evidence_list)} item(s)"
            )
        else:
            # No evidence loaded — start at a neutral 0.5 (neither confident
            # nor discredited, just unknown).
            factors.evidence_score = 0.5
            factors.notes.append("No evidence loaded; defaulting to neutral 0.5")

        # 2. Source reliability
        if sources:
            factors.source_score = sum(s.reliability_score for s in sources) / len(sources)
            factors.notes.append(
                f"Source reliability score {factors.source_score:.2f} from {len(sources)} source(s)"
            )
            # Multi-source corroboration bonus
            bonus = min(len(sources), self._SOURCE_BONUS_CAP) / self._SOURCE_BONUS_CAP
            factors.source_count_bonus = bonus * self._MAX_SOURCE_BONUS
            factors.notes.append(
                f"Source count bonus {factors.source_count_bonus:.2f} ({len(sources)} source(s))"
            )
        else:
            factors.source_score = 0.5
            factors.notes.append("No sources loaded; using neutral reliability 0.5")

        # 3. Contradictions
        num_contradictions = len(concept.contradiction_ids)
        if num_contradictions:
            raw_penalty = num_contradictions * self._CONTRADICTION_PENALTY
            factors.contradiction_penalty = min(raw_penalty, self._MAX_CONTRADICTION_PENALTY)
            factors.notes.append(
                f"Contradiction penalty -{factors.contradiction_penalty:.2f} "
                f"({num_contradictions} contradiction(s))"
            )

        # 4. Verification bonus
        from smartagent.knowledge.concepts.concept import VerificationStatus
        if concept.verification_status == VerificationStatus.VERIFIED:
            factors.verification_bonus = self._VERIFICATION_BONUS
            factors.notes.append(f"Verification bonus +{self._VERIFICATION_BONUS:.2f}")

        # 5. Age penalty (unverified concepts only)
        if (
            concept.verification_status != VerificationStatus.VERIFIED
            and concept.created_at
        ):
            try:
                created = datetime.fromisoformat(concept.created_at)
                now = datetime.now(timezone.utc)
                # Make `created` timezone-aware if it isn't already.
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = (now - created).days
                if age_days > self._AGE_PENALTY_START_DAYS:
                    excess_days = age_days - self._AGE_PENALTY_START_DAYS
                    # Grows linearly, capped at MAX_AGE_PENALTY.
                    factors.age_penalty = min(
                        excess_days / 730 * self._MAX_AGE_PENALTY,
                        self._MAX_AGE_PENALTY,
                    )
                    factors.notes.append(
                        f"Age penalty -{factors.age_penalty:.2f} ({age_days} days old, unverified)"
                    )
            except (ValueError, OverflowError):
                pass  # Malformed timestamp — skip age penalty gracefully.

        # 6. Combine
        raw = (
            (factors.evidence_score * 0.40)
            + (factors.source_score * 0.30)
            + factors.source_count_bonus
            + factors.verification_bonus
            - factors.contradiction_penalty
            - factors.age_penalty
            + manual_adjustment
        )
        factors.final_score = max(0.0, min(1.0, raw))
        factors.notes.append(f"Final score: {factors.final_score:.3f}")
        return factors

    def quick_score(
        self,
        concept: "Concept",
        evidence_list: list["Evidence"] | None = None,
        sources: list["Source"] | None = None,
        manual_adjustment: float = 0.0,
    ) -> float:
        """Convenience wrapper that returns only the final score float."""
        return self.score(concept, evidence_list, sources, manual_adjustment).final_score
