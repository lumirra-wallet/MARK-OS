"""
WorkingMemory — Milestone 6, Part 4.

Temporary cognitive scratch space: the current conversation, intermediate
reasoning, temporary facts, in-progress calculations, tool outputs,
current research, plans, and hypotheses. Explicitly **not** permanent —
everything stored here expires on its own and is never persisted to the
Memory vault (`smartagent.memory`), which remains the only durable store.

Design decision: expiration is lazy (checked on read/list, and via an
explicit `purge_expired()`) rather than driven by a background timer —
consistent with the rest of the Mind being synchronous and
deterministic (see the package docstring in `smartagent/mind/__init__.py`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_TTL_SECONDS = 600.0


@dataclass
class WorkingMemoryItem:
    """A single working-memory entry."""

    key: str
    value: Any
    category: str = "fact"
    created_at: float = field(default_factory=time.monotonic)
    ttl_seconds: float = DEFAULT_TTL_SECONDS

    def is_expired(self, now: float | None = None) -> bool:
        """Whether this item's TTL has elapsed as of `now` (defaults to the current time)."""
        current = time.monotonic() if now is None else now
        return (current - self.created_at) >= self.ttl_seconds


class WorkingMemory:
    """
    Holds temporary, auto-expiring items grouped by category.

    Recognized categories (not enforced — free-form strings are accepted so
    future callers aren't blocked by a closed enum): "conversation",
    "reasoning", "fact", "calculation", "tool_output", "research", "plan",
    "hypothesis".

    Args:
        default_ttl_seconds: TTL applied to `put()` calls that don't specify one.
        clock: Injectable time source (seconds, monotonic-style) for deterministic tests.
    """

    def __init__(
        self,
        default_ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._clock = clock or time.monotonic
        self._items: dict[str, WorkingMemoryItem] = {}

    def put(self, key: str, value: Any, category: str = "fact", ttl_seconds: float | None = None) -> WorkingMemoryItem:
        """Store (or overwrite) `key` with `value`, resetting its TTL clock."""
        item = WorkingMemoryItem(
            key=key,
            value=value,
            category=category,
            created_at=self._clock(),
            ttl_seconds=self.default_ttl_seconds if ttl_seconds is None else ttl_seconds,
        )
        self._items[key] = item
        return item

    def get(self, key: str) -> Any | None:
        """Return `key`'s value, or `None` if missing or expired (expired entries are dropped)."""
        item = self._items.get(key)
        if item is None:
            return None
        if item.is_expired(self._clock()):
            del self._items[key]
            return None
        return item.value

    def all(self, category: str | None = None) -> list[WorkingMemoryItem]:
        """Return every non-expired item, optionally filtered by `category`."""
        self.purge_expired()
        items = list(self._items.values())
        if category is not None:
            items = [item for item in items if item.category == category]
        return items

    def forget(self, key: str) -> bool:
        """Remove `key` immediately, regardless of TTL. Returns whether it existed."""
        return self._items.pop(key, None) is not None

    def purge_expired(self) -> int:
        """Drop every expired item. Returns how many were removed."""
        now = self._clock()
        expired = [key for key, item in self._items.items() if item.is_expired(now)]
        for key in expired:
            del self._items[key]
        return len(expired)

    def clear(self) -> None:
        """Drop everything, expired or not."""
        self._items.clear()

    def __len__(self) -> int:
        self.purge_expired()
        return len(self._items)
