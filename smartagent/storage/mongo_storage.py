"""
MongoStorageProvider — MongoDB storage backend via pymongo.

Activated when DATABASE_PROVIDER=mongodb and MONGODB_URI is set.

Schema
------
One collection: ``mark_storage``, with a unique compound index on
(namespace, key) — the same (namespace, key) primary-key shape as
PostgresStorageProvider's table, so callers can't tell the backends apart.

    {
        "namespace":  str,
        "key":        str,
        "value":      <native BSON — dict/list/str/int/float/bool/None>,
        "created_at": str (ISO 8601, matches StorageRecord's own format),
        "updated_at": str,
    }
"""

from __future__ import annotations

from typing import Any

from smartagent.storage.base import StorageProvider, StorageRecord, _now
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_COLLECTION_NAME = "mark_storage"


class MongoStorageProvider(StorageProvider):
    """
    MongoDB-backed storage provider.

    Requires:
        pip install pymongo
        MONGODB_URI=mongodb+srv://user:pass@cluster/...
    """

    def __init__(self, uri: str, db_name: str = "mark") -> None:
        self._uri = uri
        self._db_name = db_name
        self._client = None      # lazy init
        self._collection = None  # lazy init

    def _collection_or_raise(self):  # type: ignore[return]
        if self._collection is None:
            raise RuntimeError(
                "MongoStorageProvider not initialized — call initialize() first"
            )
        return self._collection

    def initialize(self) -> None:
        try:
            from pymongo import MongoClient  # type: ignore
            self._client = MongoClient(self._uri, serverSelectionTimeoutMS=5000)
            self._client.admin.command("ping")
            self._collection = self._client[self._db_name][_COLLECTION_NAME]
            self._collection.create_index(
                [("namespace", 1), ("key", 1)], unique=True, name="namespace_key_unique",
            )
            logger.info("MongoStorageProvider: connected to db=%s", self._db_name)
        except ImportError:
            raise RuntimeError(
                "MongoStorageProvider requires pymongo: pip install pymongo"
            )
        except Exception as exc:
            raise RuntimeError(f"MongoStorageProvider: cannot connect — {exc}") from exc

    def get(self, namespace: str, key: str) -> Any | None:
        doc = self._collection_or_raise().find_one({"namespace": namespace, "key": key})
        return doc["value"] if doc else None

    def set(self, namespace: str, key: str, value: Any) -> None:
        now = _now()
        self._collection_or_raise().update_one(
            {"namespace": namespace, "key": key},
            {
                "$set": {"value": value, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    def delete(self, namespace: str, key: str) -> bool:
        result = self._collection_or_raise().delete_one({"namespace": namespace, "key": key})
        return result.deleted_count > 0

    def list_keys(self, namespace: str) -> list[str]:
        docs = self._collection_or_raise().find(
            {"namespace": namespace}, {"key": 1},
        ).sort("key", 1)
        return [d["key"] for d in docs]

    def list_records(self, namespace: str) -> list[StorageRecord]:
        docs = self._collection_or_raise().find({"namespace": namespace}).sort("key", 1)
        return [
            StorageRecord(
                namespace=namespace,
                key=d["key"],
                value=d["value"],
                created_at=d.get("created_at", ""),
                updated_at=d.get("updated_at", ""),
            )
            for d in docs
        ]

    def health(self) -> dict[str, Any]:
        import time
        t0 = time.monotonic()
        try:
            if self._client is None:
                raise RuntimeError("not initialized")
            self._client.admin.command("ping")
            ms = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": f"mongodb reachable ({ms}ms)", "provider": "mongodb"}
        except Exception as exc:
            return {"status": "error", "message": str(exc), "provider": "mongodb"}
