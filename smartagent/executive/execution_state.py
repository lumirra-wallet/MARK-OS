"""
ExecutionState — the lifecycle state of an entire execution run.

Distinct from ``TaskStatus`` (which tracks a single task).
``ExecutionState`` tracks the overall run that ``ExecutiveController``
manages from goal receipt to result delivery.

Transitions:
    IDLE → PLANNING   — goal received, Planner is decomposing
    PLANNING → READY  — plan is built and validated
    READY → RUNNING   — Scheduler has started dispatching tasks
    RUNNING → PAUSED  — user or system paused execution
    PAUSED → RUNNING  — execution resumed
    RUNNING → COMPLETED — all tasks finished successfully
    RUNNING → FAILED    — one or more tasks failed terminally
    * → CANCELLED       — user cancelled mid-run
"""

from enum import Enum


class ExecutionState(Enum):
    """Lifecycle state of an ``ExecutionContext`` (a single goal run)."""

    IDLE = "idle"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """True when the execution has reached a final (non-resumable) state."""
        return self in (
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
        )

    @property
    def is_active(self) -> bool:
        """True when the execution is currently progressing."""
        return self in (ExecutionState.PLANNING, ExecutionState.RUNNING)
