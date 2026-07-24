"""
Storage factory — returns the active StorageProvider singleton.

Selection order:
    1. DATABASE_PROVIDER env var  ("sqlite" | "postgres" | "mongodb")
    2. DATABASE_URL present        → postgres
    3. Default                     → sqlite (local JSON files)

Usage::

    from smartagent.storage.factory import get_storage
    store = get_storage()
    store.set("settings", "key", {"value": 1})
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.storage.base import StorageProvider

_instance: "StorageProvider | None" = None


def get_storage() -> "StorageProvider":
    """Return the module-level StorageProvider singleton, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = _create()
    return _instance


def _local_fallback(reason: str) -> "StorageProvider":
    """Return a working local JSON store, logging *why* we fell back.

    Used when a remote backend (mongodb/postgres) is configured but its
    server is unreachable at boot — a paused Atlas cluster, no network, a
    DNS failure (``getaddrinfo failed``), etc. Degrading to local storage
    keeps MARK alive and quiet instead of raising on every ``get_storage()``
    call: because the factory caches the returned singleton, falling back
    here ONCE stops the repeated 5-second connection retries that would
    otherwise flood the logs. Matches the rest of MARK's degrade-gracefully
    philosophy (Ollama down → fallback reply, TTS down → browser voice).
    """
    from smartagent.logs.logger import get_logger
    get_logger(__name__).warning(
        "storage: remote backend unavailable — falling back to LOCAL JSON storage. "
        "MARK will run normally but any data in the remote DB is not visible until "
        "it is reachable again. Reason: %s", reason,
    )
    from smartagent.storage.local_storage import LocalStorageProvider
    p = LocalStorageProvider()
    p.initialize()
    return p


def _create() -> "StorageProvider":
    provider_name = os.environ.get("DATABASE_PROVIDER", "sqlite").strip().lower()
    database_url  = os.environ.get("DATABASE_URL", "")

    # Only use postgres when explicitly requested — DATABASE_URL alone is NOT enough
    # (Replit auto-sets DATABASE_URL for its built-in PostgreSQL, but MARK should use
    # its own lightweight local storage by default unless the operator opts in).

    if provider_name == "postgres":
        if not database_url:
            raise RuntimeError(
                "DATABASE_PROVIDER=postgres but DATABASE_URL is not set. "
                "Set DATABASE_URL=postgresql://user:pass@host/db"
            )
        try:
            from smartagent.storage.postgres_storage import PostgresStorageProvider
            p = PostgresStorageProvider(database_url)
            p.initialize()
            return p
        except Exception as exc:  # noqa: BLE001 — connection failure, not misconfig
            return _local_fallback(f"postgres init failed: {exc}")

    if provider_name == "mongodb":
        mongodb_uri = os.environ.get("MONGODB_URI", "")
        if not mongodb_uri:
            raise RuntimeError(
                "DATABASE_PROVIDER=mongodb but MONGODB_URI is not set. "
                "Set MONGODB_URI=mongodb+srv://user:pass@cluster/..."
            )
        db_name = os.environ.get("MONGODB_DB_NAME", "mark")
        try:
            from smartagent.storage.mongo_storage import MongoStorageProvider
            p = MongoStorageProvider(mongodb_uri, db_name)
            p.initialize()
            return p
        except Exception as exc:  # noqa: BLE001 — cluster unreachable / DNS / paused
            return _local_fallback(f"mongodb init failed: {exc}")

    # Default: local JSON storage
    from smartagent.storage.local_storage import LocalStorageProvider
    p = LocalStorageProvider()
    p.initialize()
    return p


def reset_storage() -> None:
    """Clear the singleton (useful in tests)."""
    global _instance
    _instance = None
