"""
smartagent.server.self_state — MARK's internal self-state.

Originally a standalone Mode/active_tasks tracker (Phase 5). Replaced with
a thin wrapper around the real self-model already built in
smartagent.mind.executive.executive_controller.ExecutiveController —
attention, confidence, homeostasis, and a proper state machine, not a bare
dataclass — discovered mid-session sitting unused because nothing outside
smartagent/brain/ and its own tests ever constructed one. See the "MARK
Core Reconciliation" note: this is move 2 of that plan.

A handful of explicit calls at natural transition points in api.py update
it (task_started/task_finished/set_model) — this module doesn't rewire the
pipeline itself, it just observes it, same as before.

Thread-safe singleton, same shape as ProviderFactory in llm/factory.py.
"""

from __future__ import annotations

import threading
from typing import Any

from smartagent.mind.executive.executive_controller import ExecutiveController, MindProviders


class SelfStateTracker:
    """One per process. Wraps a real ExecutiveController — mode/active_tasks
    are updated from api.py's request lifecycle; model is refreshed
    opportunistically when known; memory status is passed through as-is
    (the Mind has no equivalent concept yet)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_model: str | None = None
        self._memory_status = "available"
        self._active_tasks = 0
        self._current_task_name: str | None = None
        self._controller = ExecutiveController(
            providers=MindProviders(active_model=lambda: self._active_model),
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            model = self._controller.self_model()
            return {
                "identity": model.name,
                "owner": model.owner,
                "mode": model.state,
                "state": model.state,
                "current_activity": model.current_activity,
                "active_tasks": self._active_tasks,
                "model": self._active_model or "none",
                "memory": self._memory_status,
                "voice": "disabled",  # honest — voice hasn't been built
                "confidence": model.confidence,
                "health": model.health_score,
            }

    def task_started(self, task_name: str = "conversation", importance: float = 0.5) -> None:
        with self._lock:
            self._active_tasks += 1
            self._current_task_name = task_name
            self._controller.start_task(task_name, importance)

    def task_finished(self, succeeded: bool = True, what_happened: str = "") -> None:
        with self._lock:
            self._active_tasks = max(0, self._active_tasks - 1)
            task_name = self._current_task_name or "conversation"
            self._controller.complete_task(
                task_name, succeeded, what_happened or "Task finished.",
            )
            self._current_task_name = None

    def set_model(self, model_id: str | None) -> None:
        with self._lock:
            self._active_model = model_id

    def set_memory_status(self, status: str) -> None:
        with self._lock:
            self._memory_status = status


_tracker: SelfStateTracker | None = None


def get_self_state_tracker() -> SelfStateTracker:
    global _tracker
    if _tracker is None:
        _tracker = SelfStateTracker()
    return _tracker
