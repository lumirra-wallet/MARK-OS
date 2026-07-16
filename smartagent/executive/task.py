"""
Task — the atomic unit of MARK's executive planning system.

A ``Task`` represents one step in a goal's execution plan.  Tasks are
created by the ``Planner``, arranged into a ``TaskGraph``, queued by
``submit_to_queue()``, and executed by the ``Scheduler``.

Design rules:
- Tasks are *immutable after creation* except for ``status``, ``result``,
  ``error``, ``started_at``, and ``completed_at`` — which are set by the
  Scheduler during execution.
- ``dependencies`` is a list of task *ids* (strings), not references.
  The ``TaskGraph`` resolves references at runtime.
- ``TaskType`` drives worker selection in Phase 2.  In Phase 1 it is
  recorded for display and future routing only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TaskStatus(Enum):
    """
    Lifecycle states for a single task.

    Transitions (Scheduler enforces these):
        PENDING  → READY      when all dependencies completed
        PENDING  → BLOCKED    when a dependency fails
        READY    → RUNNING    when Scheduler picks it up
        RUNNING  → COMPLETED  on success
        RUNNING  → FAILED     on error
    """

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(Enum):
    """
    Semantic category of a task — used by the WorkerRegistry (Phase 2) to
    route each task to the appropriate specialist worker.
    """

    RESEARCH = "research"
    PLANNING = "planning"
    DESIGN = "design"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    CODING = "coding"
    TESTING = "testing"
    REVIEW = "review"
    DOCUMENTATION = "documentation"
    ANALYSIS = "analysis"
    REPORT = "report"
    GENERIC = "generic"
    DEBUGGING = "debugging"  # Milestone 20 — Self Debugging


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Task:
    """
    One step in a MARK execution plan.

    Attributes:
        id:           Unique identifier (UUID4 by default).
        title:        Short human-readable label shown in the console.
        description:  Longer description passed to the worker as context.
        task_type:    Semantic category for worker routing.
        status:       Current lifecycle state (Scheduler manages transitions).
        dependencies: Ordered list of task ids that must complete first.
        result:       Output produced by the worker (set on completion).
        error:        Error message (set on failure).
        created_at:   ISO-8601 timestamp of task creation.
        started_at:   ISO-8601 timestamp when execution began.
        completed_at: ISO-8601 timestamp when execution finished.
        metadata:     Free-form dict for worker-specific data.
    """

    title: str
    description: str = ""
    task_type: TaskType = TaskType.GENERIC
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Convenience predicates
    # ------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """True when the task has reached a final state (completed or failed)."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    @property
    def is_runnable(self) -> bool:
        """True when the task is in READY state and can be dispatched."""
        return self.status == TaskStatus.READY

    # ------------------------------------------------------------------
    # Lifecycle helpers (called by Scheduler)
    # ------------------------------------------------------------------

    def mark_ready(self) -> None:
        """Transition PENDING → READY."""
        if self.status == TaskStatus.PENDING:
            self.status = TaskStatus.READY

    def mark_running(self) -> None:
        """Transition READY → RUNNING, recording start time."""
        self.status = TaskStatus.RUNNING
        self.started_at = _now_iso()

    def mark_completed(self, result: str = "") -> None:
        """Transition RUNNING → COMPLETED, recording result and finish time."""
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = _now_iso()

    def mark_failed(self, error: str = "") -> None:
        """Transition RUNNING → FAILED, recording error and finish time."""
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = _now_iso()

    def mark_blocked(self) -> None:
        """Transition PENDING → BLOCKED when a dependency fails."""
        self.status = TaskStatus.BLOCKED

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        dep_str = f" (after {len(self.dependencies)} task(s))" if self.dependencies else ""
        return f"[{self.status.value.upper()}] {self.title}{dep_str}"

    def __repr__(self) -> str:
        return (
            f"Task(id={self.id[:8]}…, title={self.title!r}, "
            f"type={self.task_type.value}, status={self.status.value})"
        )
