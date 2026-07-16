"""
VectorProvider — abstract interface for all vector/embedding backends.

Implementations
---------------
KeywordProvider  — TF-IDF keyword search; zero dependencies; VECTOR_PROVIDER=keyword
ChromaProvider   — ChromaDB local store; VECTOR_PROVIDER=chroma
PGVectorProvider — PostgreSQL + pgvector; VECTOR_PROVIDER=pgvector
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    """A single vector search hit."""
    id:       str
    text:     str
    score:    float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorProvider(ABC):
    """
    Minimal vector store interface.

    Agent code calls only add / search / delete — never touching the backend.
    """

    @abstractmethod
    def add(
        self,
        texts:     list[str],
        ids:       list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Index *texts* with the given *ids* (and optional *metadatas*)."""

    @abstractmethod
    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        """Return the *n* most relevant results for *query*."""

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """Remove documents by id."""

    @abstractmethod
    def count(self) -> int:
        """Return the total number of indexed documents."""

    def clear(self) -> None:
        """Remove all documents (optional, default raises)."""
        raise NotImplementedError(f"{self.__class__.__name__}.clear() not implemented")

    def health(self) -> dict[str, Any]:
        try:
            self.count()
            return {"status": "ok", "message": f"{self.__class__.__name__} reachable", "count": self.count()}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def initialize(self) -> None:
        """One-time setup.  No-op by default."""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} docs={self.count()}>"
