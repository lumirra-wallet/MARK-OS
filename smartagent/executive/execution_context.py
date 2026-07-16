"""
ExecutionContext — the live state of one goal-execution run.

An ``ExecutionContext`` is created by ``ExecutiveController.receive_goal()``
and flows through the entire pipeline:

    ExecutiveController → Planner → TaskGraph → TaskQueue → Scheduler → results

The context is the single source of truth for everything about a run:
  - the original goal
  - the plan (TaskGraph)
  - the pending-task queue (TaskQueue)
  - current execution state
  - per-task results and errors
  - aggregate metadata (timing, model used, etc.)

Workers receive the context so they can read sibling task results and
contribute their own (Phase 2+).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.task import Task, TaskStatus
from smartagent.executive.task_graph import TaskGraph
from smartagent.executive.task_queue import TaskQueue


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ExecutionContext:
    """
    Carries all state for one goal-execution run.

    Attributes:
        goal:       The original user goal string.
        plan_id:    UUID identifying this run (auto-generated).
        task_graph: DAG of all tasks in the plan.
        task_queue: FIFO queue of ready-to-run tasks.
        state:      Current ``ExecutionState`` of this run.
        results:    Dict mapping task_id → result text.
        errors:     Dict mapping task_id → error message.
        created_at: ISO-8601 timestamp of context creation.
        started_at: ISO-8601 timestamp when execution began.
        ended_at:   ISO-8601 timestamp when execution finished.
        metadata:   Free-form dict for model name, token counts, etc.
    """

    goal: str
    task_graph: TaskGraph = field(default_factory=TaskGraph)
    task_queue: TaskQueue = field(default_factory=TaskQueue)
    state: ExecutionState = ExecutionState.IDLE
    results: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def task_count(self) -> int:
        """Total number of tasks in the plan."""
        return len(self.task_graph)

    @property
    def completed_count(self) -> int:
        """Number of tasks that have successfully completed."""
        return sum(
            1 for t in self.task_graph.all_tasks()
            if t.status == TaskStatus.COMPLETED
        )

    @property
    def failed_count(self) -> int:
        """Number of tasks that have failed."""
        return sum(
            1 for t in self.task_graph.all_tasks()
            if t.status == TaskStatus.FAILED
        )

    @property
    def is_complete(self) -> bool:
        """True when all tasks are in a terminal state."""
        return self.task_graph.all_completed()

    @property
    def has_failures(self) -> bool:
        """True when at least one task failed."""
        return self.task_graph.has_failures()

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def transition_to(self, new_state: ExecutionState) -> None:
        """Update ``state``, recording timing on key transitions."""
        self.state = new_state
        if new_state == ExecutionState.RUNNING and self.started_at is None:
            self.started_at = _now_iso()
        if new_state.is_terminal:
            self.ended_at = _now_iso()

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    def record_result(self, task_id: str, result: str) -> None:
        """Store the output of a completed task."""
        self.results[task_id] = result

    def record_error(self, task_id: str, error: str) -> None:
        """Store the error message of a failed task."""
        self.errors[task_id] = error

    def get_result(self, task_id: str) -> Optional[str]:
        """Return the result for *task_id*, or ``None`` if not yet available."""
        return self.results.get(task_id)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """One-line summary of this execution context."""
        return (
            f"[{self.plan_id[:8]}] goal={self.goal!r}  "
            f"state={self.state.value}  "
            f"tasks={self.completed_count}/{self.task_count}"
        )

    def __repr__(self) -> str:
        return (
            f"ExecutionContext(plan_id={self.plan_id[:8]}…, "
            f"state={self.state.value}, "
            f"tasks={self.task_count})"
        )
