"""
smartagent.storage — pluggable storage abstraction.

Select a backend via DATABASE_PROVIDER env var:
    DATABASE_PROVIDER=sqlite    (default) — JSON files on disk
    DATABASE_PROVIDER=postgres  — PostgreSQL via SQLAlchemy
    DATABASE_PROVIDER=mongodb   — MongoDB via pymongo (MONGODB_URI required)

Quick-start::

    from smartagent.storage.factory import get_storage
    store = get_storage()
    store.set("settings", "theme", {"dark": True})
    val  = store.get("settings", "theme")
"""

from smartagent.storage.base import StorageProvider, StorageRecord
from smartagent.storage.factory import get_storage

__all__ = ["StorageProvider", "StorageRecord", "get_storage"]
