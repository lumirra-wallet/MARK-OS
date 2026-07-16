"""
PGVectorProvider — PostgreSQL + pgvector extension.

Activated when VECTOR_PROVIDER=pgvector.
Requires:
    pip install pgvector sqlalchemy psycopg2-binary

PostgreSQL setup::

    CREATE EXTENSION IF NOT EXISTS vector;
"""

from __future__ import annotations

import json
import os
from typing import Any

from smartagent.vector.base import VectorProvider, SearchResult
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_TABLE = "mark_vectors"
_DIM   = int(os.environ.get("EMBEDDING_DIM", "1536"))  # text-embedding-3-small default

_SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id         TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    embedding  vector({_DIM}),
    metadata   JSONB DEFAULT '{{}}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS {_TABLE}_embedding_idx
    ON {_TABLE} USING ivfflat (embedding vector_cosine_ops);
"""


class PGVectorProvider(VectorProvider):
    """
    Stores document embeddings in a pgvector column and searches via cosine similarity.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._url    = database_url or os.environ.get("DATABASE_URL", "")
        self._engine = None

    def initialize(self) -> None:
        if not self._url:
            raise RuntimeError("PGVectorProvider requires DATABASE_URL to be set")
        try:
            from sqlalchemy import create_engine, text  # type: ignore
            self._engine = create_engine(self._url, pool_pre_ping=True)
            with self._engine.connect() as conn:
                conn.execute(text(_SCHEMA_SQL))
                conn.commit()
            logger.info("PGVectorProvider: table %s ready", _TABLE)
        except ImportError:
            raise RuntimeError(
                "PGVectorProvider requires: pip install pgvector sqlalchemy psycopg2-binary"
            )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        from smartagent.llm.factory import get_active_provider
        import os as _os
        provider = get_active_provider()
        if provider == "github":
            from smartagent.llm.github_provider import GitHubProvider
            p = GitHubProvider(token=_os.environ.get("GITHUB_TOKEN", ""))
            p.load()
            return [p.embed(t) for t in texts]
        else:
            from smartagent.models.providers.ollama_provider import OllamaProvider
            p = OllamaProvider(base_url=_os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
            p.load()
            return [p.embed(t) for t in texts]

    def _engine_ok(self):
        if self._engine is None:
            self.initialize()
        return self._engine

    def add(
        self,
        texts:     list[str],
        ids:       list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        from sqlalchemy import text
        embeds = self._embed(texts)
        metas  = metadatas or [{} for _ in texts]
        with self._engine_ok().connect() as conn:
            for doc_id, t, emb, meta in zip(ids, texts, embeds, metas):
                conn.execute(text(f"""
                    INSERT INTO {_TABLE} (id, content, embedding, metadata)
                    VALUES (:id, :content, :emb, :meta)
                    ON CONFLICT (id) DO UPDATE
                    SET content=EXCLUDED.content, embedding=EXCLUDED.embedding,
                        metadata=EXCLUDED.metadata
                """), {"id": doc_id, "content": t,
                       "emb": str(emb), "meta": json.dumps(meta)})
            conn.commit()

    def search(self, query: str, n: int = 5) -> list[SearchResult]:
        from sqlalchemy import text
        q_emb = str(self._embed([query])[0])
        with self._engine_ok().connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, content, metadata,
                       1 - (embedding <=> :qemb::vector) AS score
                FROM {_TABLE}
                ORDER BY embedding <=> :qemb::vector
                LIMIT :n
            """), {"qemb": q_emb, "n": n}).fetchall()
        return [
            SearchResult(id=r[0], text=r[1], metadata=json.loads(r[2] or "{}"),
                         score=round(float(r[3]), 4))
            for r in rows
        ]

    def delete(self, ids: list[str]) -> None:
        from sqlalchemy import text
        with self._engine_ok().connect() as conn:
            for doc_id in ids:
                conn.execute(text(f"DELETE FROM {_TABLE} WHERE id=:id"), {"id": doc_id})
            conn.commit()

    def count(self) -> int:
        from sqlalchemy import text
        with self._engine_ok().connect() as conn:
            return conn.execute(text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar() or 0
