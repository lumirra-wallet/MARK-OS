"""
StorageProvider — abstract base for all MARK storage backends.

All storage operations are namespaced (e.g. "chat", "memory", "settings",
"agent_state", "project") so different subsystems cannot collide.

Implementations
---------------
LocalStorageProvider   — JSON files on disk  (DATABASE_PROVIDER=sqlite)
PostgresStorageProvider — PostgreSQL / SQLAlchemy (DATABASE_PROVIDER=postgres)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class StorageRecord:
    """A single persisted item."""
    namespace: str
    key:       str
    value:     Any
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace":  self.namespace,
            "key":        self.key,
            "value":      self.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class StorageProvider(ABC):
    """
    Abstract storage interface.

    Namespaces
    ----------
    chat          — conversation messages and sessions
    memory        — agent long-term memory entries
    settings      — user / system configuration
    agent_state   — running agent task state
    project       — project metadata and profiles

    Any string is a valid namespace; the above are conventional names.
    """

    # ── Core CRUD ──────────────────────────────────────────────────────────

    @abstractmethod
    def get(self, namespace: str, key: str) -> Any | None:
        """Return the stored value, or None if the key doesn't exist."""

    @abstractmethod
    def set(self, namespace: str, key: str, value: Any) -> None:
        """Persist *value* under (namespace, key).  Overwrites if present."""

    @abstractmethod
    def delete(self, namespace: str, key: str) -> bool:
        """Delete the record.  Returns True if it existed."""

    @abstractmethod
    def list_keys(self, namespace: str) -> list[str]:
        """Return all keys in *namespace*."""

    @abstractmethod
    def list_records(self, namespace: str) -> list[StorageRecord]:
        """Return all records in *namespace* with metadata."""

    # ── Convenience helpers ────────────────────────────────────────────────

    def get_or_default(self, namespace: str, key: str, default: Any) -> Any:
        val = self.get(namespace, key)
        return val if val is not None else default

    def exists(self, namespace: str, key: str) -> bool:
        return self.get(namespace, key) is not None

    def clear_namespace(self, namespace: str) -> int:
        """Delete all records in *namespace*.  Returns the count deleted."""
        keys = self.list_keys(namespace)
        for k in keys:
            self.delete(namespace, k)
        return len(keys)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """One-time setup (create tables, directories, etc.).  No-op by default."""

    def health(self) -> dict[str, Any]:
        """Return a health dict with at least ``status`` and ``message`` keys."""
        try:
            self.list_keys("_health_check")
            return {"status": "ok", "message": "storage reachable", "provider": self.__class__.__name__}
        except Exception as exc:
            return {"status": "error", "message": str(exc), "provider": self.__class__.__name__}

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
