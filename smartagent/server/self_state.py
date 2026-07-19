"""
smartagent.server.self_state — MARK's internal self-state (Phase 5).

Tracks what MARK is doing right now: idle / reasoning / executing / etc,
how many tasks are active, and whether core resources (model, memory) are
available. A handful of explicit calls at natural transition points in
api.py update it — this module doesn't rewire the pipeline itself, it just
observes it.

Thread-safe singleton, same shape as ProviderFactory in llm/factory.py.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Mode(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    REASONING = "reasoning"
    EXECUTING = "executing"
    LEARNING = "learning"


@dataclass
class SelfState:
    mode: Mode = Mode.IDLE
    active_tasks: int = 0
    model_loaded: str | None = None
    memory_status: str = "available"
    voice_status: str = "disabled"  # honest — Phase 4 (voice) hasn't been built

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity": "MARK",
            "mode": self.mode.value,
            "active_tasks": self.active_tasks,
            "model": self.model_loaded or "none",
            "memory": self.memory_status,
            "voice": self.voice_status,
        }


class SelfStateTracker:
    """One per process. Mode/active_tasks are updated from api.py's request
    lifecycle; model/memory are refreshed opportunistically when known."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = SelfState()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._state.as_dict()

    def set_mode(self, mode: Mode) -> None:
        with self._lock:
            self._state.mode = mode

    def task_started(self, mode: Mode = Mode.EXECUTING) -> None:
        with self._lock:
            self._state.active_tasks += 1
            self._state.mode = mode

    def task_finished(self) -> None:
        with self._lock:
            self._state.active_tasks = max(0, self._state.active_tasks - 1)
            if self._state.active_tasks == 0:
                self._state.mode = Mode.IDLE

    def set_model(self, model_id: str | None) -> None:
        with self._lock:
            self._state.model_loaded = model_id

    def set_memory_status(self, status: str) -> None:
        with self._lock:
            self._state.memory_status = status


_tracker: SelfStateTracker | None = None


def get_self_state_tracker() -> SelfStateTracker:
    global _tracker
    if _tracker is None:
        _tracker = SelfStateTracker()
    return _tracker
