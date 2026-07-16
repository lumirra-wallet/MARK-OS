"""
WorkerCache — in-memory output cache for OllamaWorkerMixin results.

Cache key: MD5 of (goal.lower() | task_title.lower() | worker_name.lower() | model_id)

This avoids re-calling Ollama when:
  - The same engineer goal is retried after a failed test cycle
  - DevLoop reruns the same task after a fix

The cache is session-scoped (lives until the process exits).  It does NOT
persist across restarts — that would risk stale code being injected.

Usage::

    from smartagent.performance.worker_cache import get_global_cache

    cache = get_global_cache()
    key = cache.make_key(goal, task_title, worker_name, model_id)
    hit = cache.get(key)
    if hit is None:
        result = call_ollama(...)
        cache.put(key, result)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    puts: int = 0

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / max(self.total, 1)

    def as_display(self) -> str:
        return (
            f"  Cache hits  : {self.hits} / {self.total} "
            f"({self.hit_rate:.0%} hit rate)  entries={self.puts - self.hits}"
        )


class WorkerCache:
    """
    Thread-safe (GIL-protected) in-memory LRU-style worker output cache.

    Args:
        max_size: Maximum number of entries.  LRU eviction when exceeded.
    """

    def __init__(self, max_size: int = 256) -> None:
        self._store: dict[str, str] = {}
        self._max_size = max_size
        self.stats = CacheStats()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def make_key(
        self,
        goal: str,
        task_title: str,
        worker_name: str,
        model_id: Optional[str],
    ) -> str:
        """Return the MD5 cache key for this worker call."""
        raw = f"{goal.lower()}|{task_title.lower()}|{worker_name.lower()}|{model_id or ''}"
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()

    def get(self, key: str) -> Optional[str]:
        """Return cached output for *key*, or ``None`` on a miss."""
        value = self._store.get(key)
        if value is not None:
            self.stats.hits += 1
            # Move to end (most recently used)
            self._store.pop(key)
            self._store[key] = value
        else:
            self.stats.misses += 1
        return value

    def put(self, key: str, value: str) -> None:
        """Store *value* under *key*, evicting oldest entry if at capacity."""
        if key in self._store:
            self._store.pop(key)
        elif len(self._store) >= self._max_size:
            # Evict oldest entry
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key)
        self._store[key] = value
        self.stats.puts += 1

    def invalidate(self, key: str) -> bool:
        """Remove *key* from the cache. Returns True if it existed."""
        if key in self._store:
            self._store.pop(key)
            return True
        return False

    def clear(self) -> None:
        """Remove all entries and reset stats."""
        self._store.clear()
        self.stats = CacheStats()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: str) -> bool:
        return key in self._store


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_global_cache: WorkerCache | None = None


def get_global_cache() -> WorkerCache:
    """Return the module-level :class:`WorkerCache` singleton."""
    global _global_cache
    if _global_cache is None:
        _global_cache = WorkerCache()
    return _global_cache
