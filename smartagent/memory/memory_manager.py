"""
Memory management.

Defines `MemoryManager`, the single entry point the rest of SmartAgent uses
to store and retrieve memories. The current implementation is an in-memory
placeholder (a plain Python list) so the interface is usable immediately;
it will later be swapped for persistent backends (SQLite, a vector
database for semantic recall, etc.) without changing the public API.
"""

from __future__ import annotations


class MemoryManager:
    """
    Stores and retrieves SmartAgent's memories.

    Args:
        backend: Identifier for which storage backend to use
            (e.g. "in_memory", "sqlite", "vector_store"). Only "in_memory"
            is implemented so far; other values are accepted but currently
            behave the same as "in_memory".
    """

    def __init__(self, backend: str = "in_memory") -> None:
        self.backend = backend
        # Placeholder storage: a simple ordered list of memory entries.
        # TODO: replace with a persistent/queryable backend based on
        # `self.backend` (e.g. SQLite for structured facts, a vector store
        # for semantic search over conversation history).
        self._entries: list[dict] = []

    def remember(self, content: str, metadata: dict | None = None) -> None:
        """
        Store a new piece of information.

        Placeholder implementation: appends to an in-memory list. Will
        later handle embedding generation, deduplication, and persistence.
        """
        self._entries.append({"content": content, "metadata": metadata or {}})

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """
        Retrieve memories relevant to `query`.

        Placeholder implementation: returns the most recent entries
        regardless of relevance to `query`. Will later perform actual
        semantic or keyword-based retrieval.
        """
        # TODO: implement real relevance ranking (semantic search, keyword
        # match, recency weighting, etc.) instead of naive slicing.
        return self._entries[-limit:]

    def clear(self) -> None:
        """Erase all stored memories. Placeholder — no persistence to clean up yet."""
        self._entries.clear()
