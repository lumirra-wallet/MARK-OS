"""
Vault: the on-disk root of SmartAgent's persistent memory.

The vault is a plain directory tree of Markdown files, organized into
category subfolders (Personal, Business, Projects, ...). No database is
used by design — Memory v1 stores every memory as a readable, editable
`.md` file, and the vault itself is just the filesystem underneath it.

This module owns the vault's directory layout and raw file I/O (write,
read, list, delete). `MemoryManager` builds the higher-level
remember/recall/search/update/delete API on top of it, so callers never
touch paths or file formats directly.
"""

from __future__ import annotations

from pathlib import Path

from smartagent.logs.logger import get_logger
from smartagent.memory.entry import MemoryEntry

logger = get_logger(__name__)

# The default category set requested for Memory v1. Kept as a plain list
# (not an enum) since categories are just folder names — users/owners can
# add their own by passing `categories` to `Vault`/`MemoryManager`, and any
# folder that already exists on disk is respected automatically.
DEFAULT_CATEGORIES = [
    "Personal",
    "Business",
    "Projects",
    "Knowledge",
    "Research",
    "Journal",
    "Archive",
]


class Vault:
    """
    Manages the vault directory structure and raw Markdown file access.

    Args:
        root: Path to the vault directory. Configurable (rather than
            hardcoded) so tests can point at an isolated temp directory and
            deployments can relocate the vault without code changes.
        categories: Category subfolders to guarantee exist. Defaults to the
            standard Memory v1 category set.
    """

    def __init__(self, root: str | Path = "vault", categories: list[str] | None = None) -> None:
        self.root = Path(root)
        self.categories = list(categories) if categories else list(DEFAULT_CATEGORIES)
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Create the vault root and every configured category folder."""
        self.root.mkdir(parents=True, exist_ok=True)
        for category in self.categories:
            (self.root / category).mkdir(parents=True, exist_ok=True)

    def _category_dir(self, category: str) -> Path:
        """
        Return (creating if needed) the directory for `category`.

        Categories outside the configured default set are still allowed —
        the vault is meant to be a flexible personal knowledge store, not a
        rigid schema — so an unrecognized category simply gets its own
        folder on first use.
        """
        directory = self.root / category
        directory.mkdir(parents=True, exist_ok=True)
        if category not in self.categories:
            self.categories.append(category)
        return directory

    def list_categories(self) -> list[str]:
        """Return every category folder currently present in the vault."""
        if not self.root.exists():
            return list(self.categories)
        return sorted(path.name for path in self.root.iterdir() if path.is_dir())

    def write(self, entry: MemoryEntry) -> Path:
        """Write `entry` to its category folder as a Markdown file."""
        path = self._category_dir(entry.category) / entry.filename
        path.write_text(entry.to_markdown(), encoding="utf-8")
        logger.info("Wrote memory %s to %s", entry.id, path)
        return path

    def find_path(self, memory_id: str) -> Path | None:
        """
        Locate the Markdown file for `memory_id`.

        The vault has no separate index/database, so lookup by ID scans
        category folders for a matching filename. This is a deliberate
        Memory v1 tradeoff (simplicity and zero extra state) that stays
        fast enough for a personal vault; a future version could add an
        index if the vault grows very large.
        """
        for category_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            candidate = category_dir / f"{memory_id}.md"
            if candidate.exists():
                return candidate
        return None

    def read(self, memory_id: str) -> MemoryEntry | None:
        """Read and parse a single memory by ID, or None if it doesn't exist."""
        path = self.find_path(memory_id)
        if path is None:
            return None
        return MemoryEntry.from_markdown(path.read_text(encoding="utf-8"))

    def read_all(self, category: str | None = None) -> list[MemoryEntry]:
        """Read and parse every memory, optionally scoped to one category."""
        if category:
            directories = [self.root / category]
        else:
            directories = [path for path in self.root.iterdir() if path.is_dir()] if self.root.exists() else []

        entries: list[MemoryEntry] = []
        for directory in directories:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.md")):
                entries.append(MemoryEntry.from_markdown(path.read_text(encoding="utf-8")))
        return entries

    def delete(self, memory_id: str) -> bool:
        """Delete the Markdown file for `memory_id`. Returns False if not found."""
        path = self.find_path(memory_id)
        if path is None:
            return False
        path.unlink()
        logger.info("Deleted memory %s (%s)", memory_id, path)
        return True
