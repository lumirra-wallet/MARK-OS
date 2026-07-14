"""
Concept data model — the fundamental node of the Knowledge Graph.

Each concept is a discrete unit of knowledge MARK understands. It carries
rich metadata (confidence, importance, verification, revision history) and
links to its supporting evidence, sources, relationships, and dependencies.

Design: a dataclass with explicit field defaults so callers can create
lightweight concept stubs during inbox processing, then flesh them out
before they are approved into the permanent knowledge graph.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConceptDifficulty(str, Enum):
    """How hard it is for Mr. Smart to understand or explain this concept."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class ConceptStatus(str, Enum):
    """Lifecycle state of the concept."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class VerificationStatus(str, Enum):
    """How thoroughly this concept has been checked against evidence."""

    UNVERIFIED = "unverified"
    PENDING = "pending"       # In the inbox, awaiting owner review
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"


@dataclass
class RevisionEntry:
    """A single entry in a concept's revision history."""

    timestamp: str
    author: str
    summary: str
    previous_values: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "author": self.author,
            "summary": self.summary,
            "previous_values": self.previous_values,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RevisionEntry":
        return cls(
            timestamp=d.get("timestamp", ""),
            author=d.get("author", ""),
            summary=d.get("summary", ""),
            previous_values=d.get("previous_values", {}),
        )


@dataclass
class Concept:
    """
    A single node in MARK's knowledge graph.

    Every concept is the authoritative representation of one piece of
    knowledge. Concepts are mutable (they get updated as evidence grows),
    versioned (revision_history records every change), and linked to related
    knowledge via relationship_ids / dependency_ids / contradiction_ids.

    Args:
        id: Unique, stable ID (timestamp prefix + uuid8 suffix).
        title: Short human-readable name, e.g. "Python asyncio".
        description: Full explanation suitable for someone new to the topic.
        summary: 1-3 sentence overview for quick recall.
        category: Ontology category path, e.g. "Technology/Programming/Python".
        tags: Free-form labels for flexible grouping and search.
        aliases: Alternative names / abbreviations (also indexed by search).
        examples: Concrete usage examples.
        difficulty: How hard the concept is to grasp.
        status: Lifecycle state.
        confidence: Aggregate confidence score [0.0, 1.0].
        importance: How important this concept is to Mr. Smart [0.0, 1.0].
        created_at: ISO 8601 UTC timestamp.
        updated_at: ISO 8601 UTC timestamp.
        author: Who originally captured this concept.
        owner: Who is responsible for keeping it accurate.
        source_ids: IDs of Source records backing this concept.
        evidence_ids: IDs of Evidence records supporting this concept.
        relationship_ids: IDs of Relationship edges involving this concept.
        dependency_ids: Concept IDs this concept depends on.
        contradiction_ids: Concept IDs that directly contradict this concept.
        verification_status: How thoroughly the concept has been verified.
        revision_history: Ordered list of past changes.
    """

    id: str
    title: str
    description: str = ""
    summary: str = ""
    category: str = "Uncategorized"
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    difficulty: ConceptDifficulty = ConceptDifficulty.INTERMEDIATE
    status: ConceptStatus = ConceptStatus.ACTIVE
    confidence: float = 0.5
    importance: float = 0.5
    created_at: str = ""
    updated_at: str = ""
    author: str = "MARK"
    owner: str = "Mr. Smart"
    source_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    dependency_ids: list[str] = field(default_factory=list)
    contradiction_ids: list[str] = field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    revision_history: list[RevisionEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "summary": self.summary,
            "category": self.category,
            "tags": self.tags,
            "aliases": self.aliases,
            "examples": self.examples,
            "difficulty": self.difficulty.value,
            "status": self.status.value,
            "confidence": self.confidence,
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "author": self.author,
            "owner": self.owner,
            "source_ids": self.source_ids,
            "evidence_ids": self.evidence_ids,
            "relationship_ids": self.relationship_ids,
            "dependency_ids": self.dependency_ids,
            "contradiction_ids": self.contradiction_ids,
            "verification_status": self.verification_status.value,
            "revision_history": [r.to_dict() for r in self.revision_history],
        }

    def to_json(self, indent: int = 2) -> str:
        """Render as a pretty-printed JSON string for on-disk storage."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Concept":
        """Deserialize from a dictionary (e.g. parsed JSON)."""
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            summary=d.get("summary", ""),
            category=d.get("category", "Uncategorized"),
            tags=d.get("tags", []),
            aliases=d.get("aliases", []),
            examples=d.get("examples", []),
            difficulty=ConceptDifficulty(d.get("difficulty", "intermediate")),
            status=ConceptStatus(d.get("status", "active")),
            confidence=float(d.get("confidence", 0.5)),
            importance=float(d.get("importance", 0.5)),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            author=d.get("author", "MARK"),
            owner=d.get("owner", "Mr. Smart"),
            source_ids=d.get("source_ids", []),
            evidence_ids=d.get("evidence_ids", []),
            relationship_ids=d.get("relationship_ids", []),
            dependency_ids=d.get("dependency_ids", []),
            contradiction_ids=d.get("contradiction_ids", []),
            verification_status=VerificationStatus(
                d.get("verification_status", "unverified")
            ),
            revision_history=[
                RevisionEntry.from_dict(r) for r in d.get("revision_history", [])
            ],
        )

    @classmethod
    def from_json(cls, text: str) -> "Concept":
        """Parse a JSON string back into a Concept."""
        return cls.from_dict(json.loads(text))
