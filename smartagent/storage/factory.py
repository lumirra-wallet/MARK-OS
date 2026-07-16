"""
Storage factory — returns the active StorageProvider singleton.

Selection order:
    1. DATABASE_PROVIDER env var  ("sqlite" | "postgres")
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
        from smartagent.storage.postgres_storage import PostgresStorageProvider
        p = PostgresStorageProvider(database_url)
        p.initialize()
        return p

    # Default: local JSON storage
    from smartagent.storage.local_storage import LocalStorageProvider
    p = LocalStorageProvider()
    p.initialize()
    return p


def reset_storage() -> None:
    """Clear the singleton (useful in tests)."""
    global _instance
    _instance = None
