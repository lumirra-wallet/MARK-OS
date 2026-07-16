"""
PostgresStorageProvider — PostgreSQL storage backend via SQLAlchemy.

Activated when DATABASE_PROVIDER=postgres and DATABASE_URL is set.

Schema
------
One table: ``mark_storage``

    namespace  TEXT  NOT NULL
    key        TEXT  NOT NULL
    value      JSONB NOT NULL
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    PRIMARY KEY (namespace, key)
"""

from __future__ import annotations

import json
from typing import Any

from smartagent.storage.base import StorageProvider, StorageRecord, _now
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mark_storage (
    namespace  TEXT        NOT NULL,
    key        TEXT        NOT NULL,
    value      TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, key)
);
CREATE INDEX IF NOT EXISTS mark_storage_ns_idx ON mark_storage (namespace);
"""


class PostgresStorageProvider(StorageProvider):
    """
    PostgreSQL-backed storage provider.

    Requires:
        pip install sqlalchemy psycopg2-binary
        DATABASE_URL=postgresql://user:pass@host/db
    """

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._engine = None  # lazy init

    def _engine_or_raise(self):  # type: ignore[return]
        if self._engine is None:
            raise RuntimeError(
                "PostgresStorageProvider not initialized — call initialize() first"
            )
        return self._engine

    def initialize(self) -> None:
        try:
            from sqlalchemy import create_engine, text  # type: ignore
            self._engine = create_engine(self._url, pool_pre_ping=True)
            with self._engine.connect() as conn:
                conn.execute(text(_SCHEMA_SQL))
                conn.commit()
            logger.info("PostgresStorageProvider: connected to %s", self._url.split("@")[-1])
        except ImportError:
            raise RuntimeError(
                "PostgresStorageProvider requires sqlalchemy and psycopg2-binary: "
                "pip install sqlalchemy psycopg2-binary"
            )
        except Exception as exc:
            raise RuntimeError(f"PostgresStorageProvider: cannot connect — {exc}") from exc

    def get(self, namespace: str, key: str) -> Any | None:
        from sqlalchemy import text
        with self._engine_or_raise().connect() as conn:
            row = conn.execute(
                text("SELECT value FROM mark_storage WHERE namespace=:ns AND key=:k"),
                {"ns": namespace, "k": key},
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, namespace: str, key: str, value: Any) -> None:
        from sqlalchemy import text
        now = _now()
        serialized = json.dumps(value, default=str)
        with self._engine_or_raise().connect() as conn:
            conn.execute(text("""
                INSERT INTO mark_storage (namespace, key, value, created_at, updated_at)
                VALUES (:ns, :k, :v, :ca, :ua)
                ON CONFLICT (namespace, key) DO UPDATE
                SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at
            """), {"ns": namespace, "k": key, "v": serialized, "ca": now, "ua": now})
            conn.commit()

    def delete(self, namespace: str, key: str) -> bool:
        from sqlalchemy import text
        with self._engine_or_raise().connect() as conn:
            result = conn.execute(
                text("DELETE FROM mark_storage WHERE namespace=:ns AND key=:k"),
                {"ns": namespace, "k": key},
            )
            conn.commit()
        return (result.rowcount or 0) > 0

    def list_keys(self, namespace: str) -> list[str]:
        from sqlalchemy import text
        with self._engine_or_raise().connect() as conn:
            rows = conn.execute(
                text("SELECT key FROM mark_storage WHERE namespace=:ns ORDER BY key"),
                {"ns": namespace},
            ).fetchall()
        return [r[0] for r in rows]

    def list_records(self, namespace: str) -> list[StorageRecord]:
        from sqlalchemy import text
        with self._engine_or_raise().connect() as conn:
            rows = conn.execute(
                text("SELECT key, value, created_at, updated_at FROM mark_storage "
                     "WHERE namespace=:ns ORDER BY key"),
                {"ns": namespace},
            ).fetchall()
        return [
            StorageRecord(
                namespace=namespace,
                key=r[0],
                value=json.loads(r[1]),
                created_at=str(r[2]),
                updated_at=str(r[3]),
            )
            for r in rows
        ]

    def health(self) -> dict[str, Any]:
        import time
        t0 = time.monotonic()
        try:
            from sqlalchemy import text
            with self._engine_or_raise().connect() as conn:
                conn.execute(text("SELECT 1"))
            ms = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": f"postgres reachable ({ms}ms)", "provider": "postgres"}
        except Exception as exc:
            return {"status": "error", "message": str(exc), "provider": "postgres"}
