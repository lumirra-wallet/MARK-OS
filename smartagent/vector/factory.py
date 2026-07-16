"""
Vector store factory — returns the active VectorProvider singleton.

Selection order:
    1. VECTOR_PROVIDER env var   ("keyword" | "chroma" | "pgvector")
    2. DATABASE_URL + pgvector   → pgvector
    3. chromadb installed        → chroma
    4. Default                   → keyword

Usage::

    from smartagent.vector.factory import get_vector_store
    vs = get_vector_store()
    vs.add(["hello"], ["id1"])
    results = vs.search("hello")
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.vector.base import VectorProvider

_instance: "VectorProvider | None" = None


def get_vector_store() -> "VectorProvider":
    """Return the module-level VectorProvider singleton."""
    global _instance
    if _instance is None:
        _instance = _create()
    return _instance


def _create() -> "VectorProvider":
    name = os.environ.get("VECTOR_PROVIDER", "").strip().lower()

    if not name:
        # Auto-detect best available backend
        if os.environ.get("DATABASE_URL") and os.environ.get("VECTOR_PROVIDER") == "pgvector":
            name = "pgvector"
        else:
            try:
                import chromadb  # type: ignore  # noqa: F401
                name = "chroma"
            except ImportError:
                name = "keyword"

    if name == "pgvector":
        from smartagent.vector.pgvector_provider import PGVectorProvider
        p = PGVectorProvider()
        p.initialize()
        return p

    if name == "chroma":
        from smartagent.vector.chroma_provider import ChromaProvider
        p = ChromaProvider()
        p.initialize()
        return p

    # Default
    from smartagent.vector.keyword_provider import KeywordProvider
    return KeywordProvider()


def reset_vector_store() -> None:
    """Clear the singleton (useful in tests)."""
    global _instance
    _instance = None
