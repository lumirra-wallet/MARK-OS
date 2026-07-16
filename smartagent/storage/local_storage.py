"""
LocalStorageProvider — file-based JSON storage.

Stores each namespace as a single JSON file under ``STORAGE_DIR``
(default: ``.mark_storage/``).  Thread-safe via a per-namespace file lock.

Suitable for local development and single-process deployments.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from smartagent.storage.base import StorageProvider, StorageRecord, _now
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_DIR = Path(os.environ.get("STORAGE_DIR", ".mark_storage"))


class LocalStorageProvider(StorageProvider):
    """
    Stores each namespace as ``<STORAGE_DIR>/<namespace>.json``.

    The JSON file is a flat dict: ``{key: {value, created_at, updated_at}}``.
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self._dir = Path(storage_dir or _DEFAULT_DIR)
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    # ── Internal helpers ───────────────────────────────────────────────────

    def initialize(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.debug("LocalStorageProvider: storage dir %s", self._dir)

    def _ns_lock(self, namespace: str) -> threading.Lock:
        with self._global_lock:
            if namespace not in self._locks:
                self._locks[namespace] = threading.Lock()
            return self._locks[namespace]

    def _ns_path(self, namespace: str) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir / f"{namespace}.json"

    def _load(self, namespace: str) -> dict[str, Any]:
        path = self._ns_path(namespace)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("LocalStorageProvider: could not read %s — %s", path, exc)
            return {}

    def _save(self, namespace: str, data: dict[str, Any]) -> None:
        path = self._ns_path(namespace)
        try:
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.error("LocalStorageProvider: could not write %s — %s", path, exc)

    # ── StorageProvider interface ──────────────────────────────────────────

    def get(self, namespace: str, key: str) -> Any | None:
        with self._ns_lock(namespace):
            data = self._load(namespace)
            record = data.get(key)
            return record["value"] if record else None

    def set(self, namespace: str, key: str, value: Any) -> None:
        with self._ns_lock(namespace):
            data = self._load(namespace)
            now = _now()
            if key in data:
                data[key]["value"]      = value
                data[key]["updated_at"] = now
            else:
                data[key] = {"value": value, "created_at": now, "updated_at": now}
            self._save(namespace, data)

    def delete(self, namespace: str, key: str) -> bool:
        with self._ns_lock(namespace):
            data = self._load(namespace)
            if key not in data:
                return False
            del data[key]
            self._save(namespace, data)
            return True

    def list_keys(self, namespace: str) -> list[str]:
        with self._ns_lock(namespace):
            return list(self._load(namespace).keys())

    def list_records(self, namespace: str) -> list[StorageRecord]:
        with self._ns_lock(namespace):
            data = self._load(namespace)
            return [
                StorageRecord(
                    namespace=namespace,
                    key=k,
                    value=v["value"],
                    created_at=v.get("created_at", ""),
                    updated_at=v.get("updated_at", ""),
                )
                for k, v in data.items()
            ]

    def health(self) -> dict[str, Any]:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            test_path = self._dir / "_health.tmp"
            test_path.write_text("ok")
            test_path.unlink()
            return {
                "status":   "ok",
                "message":  f"local storage at {self._dir}",
                "provider": "local",
                "dir":      str(self._dir),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc), "provider": "local"}
