"""
smartagent.server.rate_limiter — lightweight per-workspace rate limiting
for /run requests (Phase 6: cost & safety control).

Not a queue or backpressure system — just a hard cap on how many /run
calls a workspace can trigger inside a short rolling window, so a runaway
client (or an accidental repeated submit) can't silently burn through LLM
calls unbounded. Additive: nothing calls this except the one guard in
api.py's _run().
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """True if *key* may proceed; records the attempt either way it's
        allowed. Returns False without recording when already at the cap."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self._window:
                q.popleft()
            if len(q) >= self._max:
                return False
            q.append(now)
            return True

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


_limiter: RateLimiter | None = None


def get_run_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
