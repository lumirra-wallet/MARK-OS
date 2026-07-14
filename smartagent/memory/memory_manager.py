"""
Memory management — Memory v1: a persistent Markdown vault.

`MemoryManager` is the single entry point the rest of SmartAgent uses to
store and retrieve memories. Memory v1 deliberately stores everything as
plain Markdown files on disk (see `smartagent.memory.vault.Vault`),
organized into category folders — no database and no vector/semantic
search yet (see SMARTAGENT.md and the Memory v1 requirements). This keeps
memories human-readable/editable today, while keeping the public API
(remember/recall/search/update/delete/list_categories) stable so a smarter
backend can be swapped in later without touching callers such as `brain`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from smartagent.logs.logger import get_logger
from smartagent.memory.entry import MemoryEntry
from smartagent.memory.vault import Vault

logger = get_logger(__name__)

# Where new memories land when the caller doesn't specify a category.
# "Journal" is the natural home for raw, unclassified exchanges/notes.
DEFAULT_CATEGORY = "Journal"


def _now_iso() -> str:
    """UTC timestamp in ISO 8601, used for both created_at and updated_at."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_id() -> str:
    """
    Build a sortable, filesystem-safe, unique ID for a new memory.

    A timestamp prefix keeps memory files sorted chronologically when
    browsed directly in a file manager or `ls` — a deliberate "the vault
    should be human-browsable" design goal. The short UUID suffix
    guarantees uniqueness even for memories created within the same second.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


class MemoryManager:
    """
    Stores and retrieves SmartAgent's memories in a persistent Markdown vault.

    Args:
        backend: Kept for backward compatibility with `Settings.memory_backend`.
            Memory v1 only implements "markdown_vault"; any other value logs a
            warning and falls back to it, since no other backend exists yet.
        vault_path: Directory that holds the vault. Configurable so tests and
            deployments can point at their own location instead of a hardcoded
            path.
        categories: Category subfolders to ensure exist in the vault. Defaults
            to the standard Memory v1 category set.
    """

    def __init__(
        self,
        backend: str = "markdown_vault",
        vault_path: str = "vault",
        categories: list[str] | None = None,
    ) -> None:
        if backend not in ("markdown_vault", "in_memory"):
            logger.warning("Unknown memory backend %r requested; using markdown_vault.", backend)
        self.backend = "markdown_vault"
        self.vault = Vault(root=vault_path, categories=categories)
        logger.info("MemoryManager ready (vault=%s)", self.vault.root)

    def remember(
        self,
        content: str,
        category: str = DEFAULT_CATEGORY,
        tags: list[str] | None = None,
    ) -> MemoryEntry:
        """
        Store a new memory as a Markdown file in the vault and return it.

        Metadata (id, timestamp, category, tags) is generated automatically
        so callers only ever need to provide the content plus optional
        classification hints.
        """
        now = _now_iso()
        entry = MemoryEntry(
            id=_make_id(),
            category=category,
            content=content,
            tags=list(tags) if tags else [],
            created_at=now,
            updated_at=now,
        )
        self.vault.write(entry)
        logger.info("Remembered %s in category %r (tags=%s)", entry.id, category, entry.tags)
        return entry

    def recall(self, memory_id: str) -> MemoryEntry | None:
        """Fetch a single memory by its unique ID, or None if it doesn't exist."""
        entry = self.vault.read(memory_id)
        if entry is None:
            logger.info("Recall miss for id %r", memory_id)
        return entry

    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """
        Keyword-search memory content and tags, most recent first.

        Memory v1 intentionally implements simple case-insensitive
        substring matching — not semantic/vector search (that is explicitly
        out of scope; see SMARTAGENT.md and the Memory v1 requirements).
        The signature is stable so a smarter ranking strategy can replace
        the implementation later without touching callers.
        """
        entries = self.vault.read_all(category=category)
        query_lower = query.lower().strip()
        if not query_lower:
            matches = entries
        else:
            matches = [
                entry
                for entry in entries
                if query_lower in entry.content.lower()
                or any(query_lower in tag.lower() for tag in entry.tags)
            ]
        matches.sort(key=lambda entry: entry.created_at, reverse=True)
        logger.info("Search %r (category=%s) matched %d memories", query, category, len(matches))
        return matches[:limit]

    def update(
        self,
        memory_id: str,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> MemoryEntry | None:
        """
        Update an existing memory's content and/or tags in place.

        Only fields explicitly passed are changed; `updated_at` always
        advances so the vault reflects when a memory was last touched.
        Returns None (and logs a warning) if `memory_id` doesn't exist.
        """
        entry = self.vault.read(memory_id)
        if entry is None:
            logger.warning("Update failed: memory %r not found", memory_id)
            return None
        if content is not None:
            entry.content = content
        if tags is not None:
            entry.tags = list(tags)
        entry.updated_at = _now_iso()
        self.vault.write(entry)
        logger.info("Updated memory %s", memory_id)
        return entry

    def delete(self, memory_id: str) -> bool:
        """Permanently remove a memory file from the vault. Returns False if missing."""
        deleted = self.vault.delete(memory_id)
        if deleted:
            logger.info("Deleted memory %s", memory_id)
        else:
            logger.warning("Delete failed: memory %r not found", memory_id)
        return deleted

    def list_categories(self) -> list[str]:
        """Return every category folder currently present in the vault."""
        return self.vault.list_categories()

    def clear(self) -> None:
        """
        Remove every memory from the vault.

        Not part of the core Memory v1 spec, but kept (as in the previous
        placeholder) since it's useful for resetting a scratch/test vault
        between runs.
        """
        for entry in self.vault.read_all():
            self.vault.delete(entry.id)
