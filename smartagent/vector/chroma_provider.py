"""
ChromaProvider — ChromaDB-backed vector store.

Activated when VECTOR_PROVIDER=chroma.
Requires: pip install chromadb

Embeddings are generated via the active LLM provider (GitHubProvider or
OllamaProvider) so no separate embedding model needs to be configured.
"""

from __future__ import annotations

import os
from typing import Any

from smartagent.vector.base import VectorProvider, SearchResult
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = os.environ.get("CHROMA_PATH", ".mark_chroma")
_COLLECTION   = os.environ.get("CHROMA_COLLECTION", "mark_knowledge")


class ChromaProvider(VectorProvider):
    """
    Persistent ChromaDB vector store.

    Documents are embedded on the fly via the active provider.
    Embeddings are cached by ChromaDB so repeat queries are fast.
    """

    def __init__(
        self,
        path:       str = _DEFAULT_PATH,
        collection: str = _COLLECTION,
    ) -> None:
        self._path       = path
        self._col_name   = collection
        self._client     = None
        self._collection = None

    def initialize(self) -> None:
        try:
            import chromadb  # type: ignore
            self._client     = chromadb.PersistentClient(path=self._path)
            self._collection = self._client.get_or_create_collection(self._col_name)
            logger.info("ChromaProvider: collection %r at %s (%d docs)",
                        self._col_name, self._path, self._collection.count())
        except ImportError:
            raise RuntimeError(
                "ChromaProvider requires chromadb: pip install chromadb"
            )

    def _col(self):
        if self._collection is None:
            self.initialize()
        return self._collection

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via the active LLM provider."""
        from smartagent.llm.factory import get_active_provider
        provider = get_active_provider()
        # Use the factory to get the actual provider object for embedding
        from smartagent.llm.factory import _load_state
        from smartagent.llm.github_provider import GitHubProvider
        import os as _os
        if provider == "github":
            token = _os.environ.get("GITHUB_TOKEN", "")
            p = GitHubProvider(token=token)
            p.load()
            return [p.embed(t) for t in texts]
        else:
            from smartagent.models.providers.ollama_provider import OllamaProvider
            ollama_url = _os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            p = OllamaProvider(base_url=ollama_url)
            p.load()
            return [p.embed(t) for t in texts]

    def add(
        self,
        texts:     list[str],
        ids:       list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        embeddings = self._embed(texts)
        self._col().upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas or [{} for _ in texts],
        )

    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        q_embed = self._embed([query])[0]
        results = self._col().query(
            query_embeddings=[q_embed],
            n_results=min(n, self._col().count() or 1),
            include=["documents", "distances", "metadatas"],
        )
        out = []
        docs      = (results.get("documents")  or [[]])[0]
        distances = (results.get("distances")  or [[]])[0]
        metas     = (results.get("metadatas")  or [[]])[0]
        ids_ret   = (results.get("ids")        or [[]])[0]
        for doc_id, text, dist, meta in zip(ids_ret, docs, distances, metas):
            score = round(1.0 - dist, 4)  # chroma returns L2 distance
            out.append(SearchResult(id=doc_id, text=text, score=score, metadata=meta or {}))
        return out

    def delete(self, ids: list[str]) -> None:
        self._col().delete(ids=ids)

    def count(self) -> int:
        return self._col().count()

    def clear(self) -> None:
        self._col().delete(where={"_exists": True})
