"""
Evidence data model — factual support for a concept.

Knowledge is not just claimed — it is supported. Each Evidence record
documents one specific piece of supporting (or contradicting) information
for a concept, along with how strong that support is and whether it has
been independently verified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class EvidenceType(str, Enum):
    """How the evidence was produced or obtained."""

    DIRECT = "direct"           # Directly observed or experienced
    INDIRECT = "indirect"       # Inferred from related observations
    ANECDOTAL = "anecdotal"     # Single instance, not systematically tested
    EXPERIMENTAL = "experimental"  # Result of a controlled test or experiment
    THEORETICAL = "theoretical"  # Follows logically from established principles


class EvidenceVerificationStatus(str, Enum):
    """How thoroughly this evidence has been independently checked."""

    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"


@dataclass
class Evidence:
    """
    A single piece of supporting or contradicting information for a concept.

    Args:
        id: Unique stable ID.
        concept_id: The concept this evidence supports or challenges.
        description: What the evidence actually says or shows.
        source_id: ID of the Source record this evidence comes from.
        evidence_type: How the evidence was produced.
        strength: How strongly this evidence supports the concept [0.0, 1.0].
            Values above 0.5 are supporting; values below 0.5 are weakening
            (e.g. a counter-example is 0.1).
        confidence: How confident we are in this evidence itself [0.0, 1.0].
        timestamp: ISO 8601 UTC when this evidence was recorded.
        verification_status: Whether this evidence has been independently checked.
        notes: Any caveats, context, or additional observations.
    """

    id: str
    concept_id: str
    description: str = ""
    source_id: str = ""
    evidence_type: EvidenceType = EvidenceType.DIRECT
    strength: float = 0.8
    confidence: float = 0.7
    timestamp: str = ""
    verification_status: EvidenceVerificationStatus = EvidenceVerificationStatus.UNVERIFIED
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "concept_id": self.concept_id,
            "description": self.description,
            "source_id": self.source_id,
            "evidence_type": self.evidence_type.value,
            "strength": self.strength,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "verification_status": self.verification_status.value,
            "notes": self.notes,
        }

    def to_json(self, indent: int = 2) -> str:
        """Render as a pretty-printed JSON string for on-disk storage."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Evidence":
        """Deserialize from a dictionary (e.g. parsed JSON)."""
        return cls(
            id=d["id"],
            concept_id=d.get("concept_id", ""),
            description=d.get("description", ""),
            source_id=d.get("source_id", ""),
            evidence_type=EvidenceType(d.get("evidence_type", "direct")),
            strength=float(d.get("strength", 0.8)),
            confidence=float(d.get("confidence", 0.7)),
            timestamp=d.get("timestamp", ""),
            verification_status=EvidenceVerificationStatus(
                d.get("verification_status", "unverified")
            ),
            notes=d.get("notes", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "Evidence":
        """Parse a JSON string back into an Evidence."""
        return cls.from_dict(json.loads(text))
