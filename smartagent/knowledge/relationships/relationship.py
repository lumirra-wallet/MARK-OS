"""
Relationship data model — a directed edge in the Knowledge Graph.

Each relationship connects two concepts (from_concept_id → to_concept_id)
with a typed, weighted, confidence-scored edge. The type captures the
semantic meaning; strength and confidence capture how strong and how certain
that connection is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RelationshipType(str, Enum):
    """The semantic type of a relationship between two concepts."""

    DEPENDS_ON = "depends_on"
    PART_OF = "part_of"
    RELATED_TO = "related_to"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    INHERITS = "inherits"
    CAUSES = "causes"
    USES = "uses"
    CREATES = "creates"
    REQUIRES = "requires"
    IMPROVES = "improves"
    REPLACES = "replaces"
    SUPPORTS = "supports"
    REFERENCES = "references"


@dataclass
class Relationship:
    """
    A directed, typed edge between two concepts in the knowledge graph.

    Args:
        id: Unique stable ID for this relationship.
        from_concept_id: The source concept (the "subject").
        to_concept_id: The target concept (the "object").
        relation_type: Semantic type of the relationship.
        direction: "forward" (from→to only), "backward" (to→from only),
            or "bidirectional" (symmetric).
        strength: How strong the link is [0.0, 1.0]. 1.0 = definitive.
        confidence: How certain we are this relationship is correct [0.0, 1.0].
        source: Free-text provenance (source ID, URL, "manual", etc.).
        created_at: ISO 8601 UTC timestamp when the relationship was recorded.
        notes: Optional human notes about this specific relationship.
    """

    id: str
    from_concept_id: str
    to_concept_id: str
    relation_type: RelationshipType
    direction: str = "forward"
    strength: float = 0.8
    confidence: float = 0.8
    source: str = "manual"
    created_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "from_concept_id": self.from_concept_id,
            "to_concept_id": self.to_concept_id,
            "relation_type": self.relation_type.value,
            "direction": self.direction,
            "strength": self.strength,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at,
            "notes": self.notes,
        }

    def to_json(self, indent: int = 2) -> str:
        """Render as a pretty-printed JSON string for on-disk storage."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Relationship":
        """Deserialize from a dictionary (e.g. parsed JSON)."""
        return cls(
            id=d["id"],
            from_concept_id=d["from_concept_id"],
            to_concept_id=d["to_concept_id"],
            relation_type=RelationshipType(d.get("relation_type", "related_to")),
            direction=d.get("direction", "forward"),
            strength=float(d.get("strength", 0.8)),
            confidence=float(d.get("confidence", 0.8)),
            source=d.get("source", "manual"),
            created_at=d.get("created_at", ""),
            notes=d.get("notes", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "Relationship":
        """Parse a JSON string back into a Relationship."""
        return cls.from_dict(json.loads(text))
