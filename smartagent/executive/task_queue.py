"""
TaskQueue — a FIFO queue for ready-to-execute tasks.

The ``Scheduler`` dequeues tasks one at a time and dispatches them to
workers.  ``submit_to_queue()`` on ``ExecutiveController`` fills it
with the initial READY tasks from the ``TaskGraph``.

As the Scheduler completes tasks and the ``TaskGraph`` unlocks new
ones, those are re-enqueued here so the Scheduler's run-loop stays
simple: dequeue → execute → repeat until empty.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from smartagent.executive.task import Task
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


class TaskQueue:
    """
    Thread-unsafe FIFO queue for ``Task`` objects.

    The Scheduler runs synchronously in Phase 1 so thread-safety is not
    required yet.  Phase 3 may replace this with a priority queue or a
    thread-safe variant when parallel execution is introduced.
    """

    def __init__(self) -> None:
        self._queue: deque[Task] = deque()
        self._total_enqueued: int = 0

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------

    def enqueue(self, task: Task) -> None:
        """Add *task* to the back of the queue."""
        self._queue.append(task)
        self._total_enqueued += 1
        logger.debug("TaskQueue: enqueued %r (queue size=%d)", task.title, len(self._queue))

    def enqueue_many(self, tasks: list[Task]) -> None:
        """Enqueue all tasks in *tasks* preserving order."""
        for task in tasks:
            self.enqueue(task)

    def dequeue(self) -> Optional[Task]:
        """
        Remove and return the next task, or ``None`` if the queue is empty.
        """
        if not self._queue:
            return None
        task = self._queue.popleft()
        logger.debug("TaskQueue: dequeued %r (queue size=%d)", task.title, len(self._queue))
        return task

    def clear(self) -> None:
        """Remove all pending tasks from the queue."""
        count = len(self._queue)
        self._queue.clear()
        logger.debug("TaskQueue: cleared %d tasks", count)

    # ------------------------------------------------------------------
    # Read-only operations
    # ------------------------------------------------------------------

    def peek(self) -> Optional[Task]:
        """Return the next task without removing it, or ``None``."""
        return self._queue[0] if self._queue else None

    def is_empty(self) -> bool:
        """Return ``True`` when there are no tasks waiting."""
        return len(self._queue) == 0

    def size(self) -> int:
        """Number of tasks currently waiting in the queue."""
        return len(self._queue)

    def all_tasks(self) -> list[Task]:
        """Return a snapshot of queued tasks in order (does not dequeue them)."""
        return list(self._queue)

    @property
    def total_enqueued(self) -> int:
        """Running count of every task ever enqueued (not decremented on dequeue)."""
        return self._total_enqueued

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._queue)

    def __repr__(self) -> str:
        return f"TaskQueue(size={len(self._queue)}, total_enqueued={self._total_enqueued})"
