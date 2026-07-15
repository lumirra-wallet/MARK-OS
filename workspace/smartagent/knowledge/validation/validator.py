"""
Concept Validator — ensures new knowledge meets structural quality bar.

Validation runs inside the Knowledge Inbox pipeline before a concept ever
reaches the permanent knowledge graph. A concept that fails validation is
rejected immediately; one that passes moves on to contradiction detection
and confidence scoring.

This is schema/structural validation only — no AI reasoning, no semantic
judgements. The rules are explicit, deterministic, and fully auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.knowledge.concepts.concept import Concept


@dataclass
class ValidationResult:
    """Outcome of a concept validation pass."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Record a hard failure that blocks the concept from proceeding."""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        """Record a soft issue that allows the concept through but flags it."""
        self.warnings.append(message)


class ConceptValidator:
    """
    Validates that a `Concept` meets the minimum structural quality bar
    before it is allowed into the Knowledge Inbox processing pipeline.

    Rules:
    - REQUIRED: id, title (non-empty strings)
    - REQUIRED: confidence and importance in [0.0, 1.0]
    - WARN: description shorter than 10 characters
    - WARN: no tags, no summary
    - WARN: confidence == 0.5 exactly (suggests it was never explicitly set)
    """

    MIN_DESCRIPTION_LEN = 10

    def validate(self, concept: "Concept") -> ValidationResult:
        """
        Validate `concept` and return a `ValidationResult`.

        The result's `is_valid` flag starts True; any `add_error()` call
        sets it to False.
        """
        result = ValidationResult(is_valid=True)

        # --- Hard requirements ---

        if not concept.id or not concept.id.strip():
            result.add_error("Concept must have a non-empty id.")

        if not concept.title or not concept.title.strip():
            result.add_error("Concept must have a non-empty title.")

        if not (0.0 <= concept.confidence <= 1.0):
            result.add_error(
                f"Confidence {concept.confidence!r} is outside [0.0, 1.0]."
            )

        if not (0.0 <= concept.importance <= 1.0):
            result.add_error(
                f"Importance {concept.importance!r} is outside [0.0, 1.0]."
            )

        # --- Soft warnings ---

        if len(concept.description) < self.MIN_DESCRIPTION_LEN:
            result.add_warning(
                f"Description is very short ({len(concept.description)} chars); "
                f"consider expanding it for future searchability."
            )

        if not concept.summary:
            result.add_warning(
                "No summary provided; adding a 1-3 sentence summary improves quick recall."
            )

        if not concept.tags:
            result.add_warning(
                "No tags provided; tags improve search and categorization."
            )

        if concept.confidence == 0.5:
            result.add_warning(
                "Confidence is still at the default 0.5; consider scoring it once evidence is attached."
            )

        return result
