"""
smartagent.vector — pluggable vector/embedding storage abstraction.

Select a backend via VECTOR_PROVIDER env var:
    VECTOR_PROVIDER=keyword   (default) — TF-IDF keyword search, no deps
    VECTOR_PROVIDER=chroma    — ChromaDB local vector store
    VECTOR_PROVIDER=pgvector  — PostgreSQL + pgvector extension

Quick-start::

    from smartagent.vector.factory import get_vector_store
    vs = get_vector_store()
    vs.add(["hello world"], ids=["doc1"], metadatas=[{"source": "test"}])
    results = vs.search("hello", n=3)
"""

from smartagent.vector.base import VectorProvider, SearchResult
from smartagent.vector.factory import get_vector_store

__all__ = ["VectorProvider", "SearchResult", "get_vector_store"]
