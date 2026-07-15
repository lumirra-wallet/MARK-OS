"""
Source data model — provenance tracking for every piece of knowledge.

Every concept, evidence item, and relationship must link to at least one
Source so MARK always knows where knowledge came from and how reliable
it is. This satisfies the Milestone 7 requirement: "Every piece of
knowledge must remember where it came from."
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    """The category of source that produced a piece of knowledge."""

    MANUAL_ENTRY = "manual_entry"
    MEMORY = "memory"
    RESEARCH = "research"
    BOOKS = "books"
    DOCUMENTATION = "documentation"
    INTERNET = "internet"
    VIDEOS = "videos"
    COURSES = "courses"
    PERSONAL_NOTES = "personal_notes"
    FUTURE_OBSIDIAN = "future_obsidian"
    FUTURE_BROWSER = "future_browser"


@dataclass
class Source:
    """
    Provenance record for a piece of knowledge.

    Args:
        id: Unique stable ID.
        source_type: Category of the source.
        author: Who produced this source material.
        url: URL placeholder (may be empty if not web-based).
        publication: Name of the book, document, course, etc.
        date: When this source was published or accessed (ISO date string).
        reliability_score: How trustworthy this source is [0.0, 1.0].
            1.0 = highly authoritative (e.g. official documentation).
            0.5 = neutral (personal notes, unverified internet).
        citation: Free-text citation formatted for human reading.
        notes: Any additional context about this source.
    """

    id: str
    source_type: SourceType = SourceType.MANUAL_ENTRY
    author: str = ""
    url: str = ""
    publication: str = ""
    date: str = ""
    reliability_score: float = 0.7
    citation: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "source_type": self.source_type.value,
            "author": self.author,
            "url": self.url,
            "publication": self.publication,
            "date": self.date,
            "reliability_score": self.reliability_score,
            "citation": self.citation,
            "notes": self.notes,
        }

    def to_json(self, indent: int = 2) -> str:
        """Render as a pretty-printed JSON string for on-disk storage."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Source":
        """Deserialize from a dictionary (e.g. parsed JSON)."""
        return cls(
            id=d["id"],
            source_type=SourceType(d.get("source_type", "manual_entry")),
            author=d.get("author", ""),
            url=d.get("url", ""),
            publication=d.get("publication", ""),
            date=d.get("date", ""),
            reliability_score=float(d.get("reliability_score", 0.7)),
            citation=d.get("citation", ""),
            notes=d.get("notes", ""),
        )

    @classmethod
    def from_json(cls, text: str) -> "Source":
        """Parse a JSON string back into a Source."""
        return cls.from_dict(json.loads(text))
