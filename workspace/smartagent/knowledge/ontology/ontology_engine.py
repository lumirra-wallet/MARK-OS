"""
OntologyEngine — hierarchical category management for knowledge.

Categories form a tree where each node is a `Category` with a path like
"Technology/Programming/Python/Asyncio". Inheritance means a concept in a
child category also logically belongs to all ancestor categories.

Storage: the full category tree is serialized as a single JSON file at
`knowledge/ontology.json`. This is a single-file design because the ontology
is typically small and frequently queried together.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from smartagent.knowledge.categories.category import Category
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

# Default top-level categories seeded on first run.
_DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {"name": "Technology", "parent_path": "", "description": "Technical concepts and systems"},
    {"name": "Science", "parent_path": "", "description": "Scientific knowledge and discoveries"},
    {"name": "Business", "parent_path": "", "description": "Business, economics, and strategy"},
    {"name": "Personal", "parent_path": "", "description": "Personal growth and life skills"},
    {"name": "Research", "parent_path": "", "description": "Research findings and methods"},
    {"name": "History", "parent_path": "", "description": "Historical events and context"},
    {"name": "Philosophy", "parent_path": "", "description": "Philosophical ideas and ethics"},
]


class OntologyEngine:
    """
    Manages the hierarchical knowledge category tree.

    The tree is persisted as a single JSON file and kept in memory as a
    dict keyed by the full category path. This makes lookups O(1) and
    parent/ancestor traversal O(depth).

    Args:
        root: The knowledge storage root directory.
    """

    def __init__(self, root: str | Path = "knowledge") -> None:
        self._path = Path(root) / "ontology.json"
        # {full_path: Category}
        self._categories: dict[str, Category] = {}
        self._load()

    def _load(self) -> None:
        """Load categories from disk, or seed defaults on first run."""
        if self._path.exists():
            try:
                raw: list[dict[str, Any]] = json.loads(
                    self._path.read_text(encoding="utf-8")
                )
                for d in raw:
                    cat = Category.from_dict(d)
                    self._categories[cat.path] = cat
                logger.info("OntologyEngine loaded %d categories", len(self._categories))
                return
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Ontology file corrupt; re-seeding defaults: %s", exc)
        # First run or corrupt file — seed with defaults.
        for d in _DEFAULT_CATEGORIES:
            cat = Category.from_dict(d)
            self._categories[cat.path] = cat
        self._save()
        logger.info("OntologyEngine seeded %d default categories", len(self._categories))

    def _save(self) -> None:
        """Persist the current category tree to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [cat.to_dict() for cat in sorted(self._categories.values(), key=lambda c: c.path)]
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------ #
    # Category management                                                  #
    # ------------------------------------------------------------------ #

    def add_category(
        self,
        name: str,
        parent_path: str = "",
        description: str = "",
        aliases: list[str] | None = None,
    ) -> Category:
        """
        Add a new category. The parent_path must already exist (or be "").

        Args:
            name: Short category name, e.g. "Python".
            parent_path: Full path of the parent, e.g. "Technology/Programming".
            description: What this category covers.
            aliases: Alternative names.

        Returns:
            The created `Category`.

        Raises:
            ValueError: If the parent path does not exist.
            ValueError: If a category with this path already exists.
        """
        if parent_path and parent_path not in self._categories:
            raise ValueError(
                f"Parent category {parent_path!r} does not exist. "
                f"Create it before adding a child."
            )
        cat = Category(
            name=name,
            parent_path=parent_path,
            description=description,
            aliases=list(aliases) if aliases else [],
        )
        if cat.path in self._categories:
            raise ValueError(f"Category {cat.path!r} already exists.")
        self._categories[cat.path] = cat
        self._save()
        logger.info("Added category %r", cat.path)
        return cat

    def remove_category(self, path: str) -> bool:
        """
        Remove a category and all its descendants.

        Returns True if the category was found and removed, False otherwise.
        """
        if path not in self._categories:
            return False
        to_remove = [p for p in self._categories if p == path or p.startswith(f"{path}/")]
        for p in to_remove:
            del self._categories[p]
        self._save()
        logger.info("Removed category %r and %d descendant(s)", path, len(to_remove) - 1)
        return True

    def get(self, path: str) -> Category | None:
        """Look up a category by its full path."""
        return self._categories.get(path)

    def exists(self, path: str) -> bool:
        """Whether a category with this exact path exists."""
        return path in self._categories

    # ------------------------------------------------------------------ #
    # Hierarchy traversal                                                  #
    # ------------------------------------------------------------------ #

    def children(self, parent_path: str) -> list[Category]:
        """Return direct children of the category at `parent_path`."""
        return [
            cat
            for cat in self._categories.values()
            if cat.parent_path == parent_path
        ]

    def ancestors(self, path: str) -> list[Category]:
        """
        Return all ancestor categories from the root down to (but not
        including) the category at `path`, ordered root-first.
        """
        parts = path.split("/")
        result: list[Category] = []
        for i in range(1, len(parts)):
            ancestor_path = "/".join(parts[:i])
            cat = self._categories.get(ancestor_path)
            if cat:
                result.append(cat)
        return result

    def descendants(self, path: str) -> list[Category]:
        """Return all descendants of `path` (at any depth below it)."""
        return [
            cat
            for p, cat in self._categories.items()
            if p != path and p.startswith(f"{path}/")
        ]

    def is_ancestor_of(self, ancestor_path: str, descendant_path: str) -> bool:
        """Whether `ancestor_path` is an ancestor of `descendant_path`."""
        return descendant_path.startswith(f"{ancestor_path}/")

    def list_all(self) -> list[Category]:
        """Return every registered category sorted by path."""
        return sorted(self._categories.values(), key=lambda c: c.path)

    def list_roots(self) -> list[Category]:
        """Return all top-level (root) categories."""
        return [cat for cat in self._categories.values() if cat.is_root()]

    def ensure_path(self, path: str, description: str = "") -> Category:
        """
        Ensure the full category path exists, creating missing segments.

        Example: `ensure_path("Technology/Programming/Python")` creates
        "Technology", "Technology/Programming", and
        "Technology/Programming/Python" if they don't already exist.
        """
        parts = path.split("/")
        parent = ""
        cat: Category | None = None
        for part in parts:
            cat_path = f"{parent}/{part}" if parent else part
            if not self.exists(cat_path):
                cat = self.add_category(part, parent_path=parent, description=description)
            else:
                cat = self._categories[cat_path]
            parent = cat_path
        return cat  # type: ignore[return-value]

    def search(self, query: str) -> list[Category]:
        """
        Find categories whose name, path, or aliases contain `query`
        (case-insensitive substring match).
        """
        q = query.lower()
        return [
            cat
            for cat in self._categories.values()
            if q in cat.name.lower()
            or q in cat.path.lower()
            or any(q in alias.lower() for alias in cat.aliases)
        ]
