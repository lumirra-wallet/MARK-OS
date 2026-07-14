"""
Category model for the Knowledge Ontology.

Categories form a hierarchy (tree) where each category may have a parent.
The path of a category is the slash-separated chain of names from root to
leaf, e.g. "Technology/Programming/Python/Asyncio".

This is a simple value object — the hierarchy structure is owned by
`OntologyEngine`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Category:
    """
    A single node in the ontology category tree.

    Args:
        name: Short display name, e.g. "Python".
        parent_path: The full path of the parent category, e.g.
            "Technology/Programming". Empty string for root categories.
        description: What this category covers.
        aliases: Alternative names for this category.
    """

    name: str
    parent_path: str = ""
    description: str = ""
    aliases: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        """Full hierarchical path, e.g. 'Technology/Programming/Python'."""
        if self.parent_path:
            return f"{self.parent_path}/{self.name}"
        return self.name

    @property
    def depth(self) -> int:
        """How deep in the hierarchy this category sits (root = 0)."""
        return self.path.count("/")

    def is_root(self) -> bool:
        """Whether this category has no parent."""
        return self.parent_path == ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "parent_path": self.parent_path,
            "path": self.path,
            "description": self.description,
            "aliases": self.aliases,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Category":
        """Deserialize from a dictionary (e.g. parsed JSON)."""
        return cls(
            name=d["name"],
            parent_path=d.get("parent_path", ""),
            description=d.get("description", ""),
            aliases=d.get("aliases", []),
        )

    @classmethod
    def from_json(cls, text: str) -> "Category":
        """Parse a JSON string back into a Category."""
        return cls.from_dict(json.loads(text))
