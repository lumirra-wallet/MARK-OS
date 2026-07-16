"""
TaskGraph — a directed acyclic graph of Tasks.

Each node is a ``Task``; each edge represents a dependency
(Task B depends on Task A → A must complete before B can run).

The graph is built by the ``ExecutiveController`` after the ``Planner``
returns a flat task list.  Dependencies are expressed as task id strings;
the graph validates them and resolves them to ``Task`` objects at runtime.

Key operations:
    add_task()          — register a task (validates dep references)
    get_ready_tasks()   — tasks whose dependencies are all COMPLETED
    mark_completed()    — record task result; may unlock new tasks
    mark_failed()       — record task error; blocks downstream tasks
    all_completed()     — True when every task has reached a terminal state
    topological_order() — task list in safe execution order (Kahn's algorithm)
    as_display_lines()  — ASCII-art dependency tree for the console
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from smartagent.executive.task import Task, TaskStatus
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


class TaskGraphError(Exception):
    """Raised for structural problems in the task graph (cycle, missing dep, etc.)."""


class TaskGraph:
    """
    Directed Acyclic Graph of ``Task`` objects.

    All tasks are stored keyed by their id.  Dependency resolution is lazy:
    ``get_ready_tasks()`` inspects current status on every call so that the
    graph always reflects live state without requiring explicit notification.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    # ------------------------------------------------------------------
    # Building the graph
    # ------------------------------------------------------------------

    def add_task(self, task: Task) -> None:
        """
        Add *task* to the graph.

        Raises:
            TaskGraphError: If a task with the same id already exists.
        """
        if task.id in self._tasks:
            raise TaskGraphError(f"Task id {task.id!r} is already in the graph.")
        self._tasks[task.id] = task
        logger.debug("TaskGraph: added task %r (%s)", task.id[:8], task.title)

    def validate(self) -> None:
        """
        Verify graph integrity after all tasks have been added.

        Checks:
        - All dependency ids exist in the graph.
        - No cycles (topological sort succeeds).

        Raises:
            TaskGraphError: On missing dependency or detected cycle.
        """
        for task in self._tasks.values():
            for dep_id in task.dependencies:
                if dep_id not in self._tasks:
                    raise TaskGraphError(
                        f"Task {task.title!r} depends on unknown id {dep_id!r}."
                    )
        # Cycle detection via Kahn's algorithm (raises if sort is incomplete).
        self.topological_order()

    # ------------------------------------------------------------------
    # Querying state
    # ------------------------------------------------------------------

    def get(self, task_id: str) -> Optional[Task]:
        """Return the task with *task_id*, or ``None``."""
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[Task]:
        """Return all tasks in insertion order."""
        return list(self._tasks.values())

    def get_ready_tasks(self) -> list[Task]:
        """
        Return all tasks that are in PENDING status whose dependencies are all
        COMPLETED.  These are safe to move to READY and dispatch immediately.
        """
        ready: list[Task] = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            if all(
                self._tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self._tasks
            ):
                ready.append(task)
        return ready

    def all_completed(self) -> bool:
        """
        Return ``True`` when every task has reached a terminal state
        (COMPLETED or FAILED) — meaning the execution plan is finished.
        """
        return all(t.is_terminal for t in self._tasks.values())

    def has_failures(self) -> bool:
        """Return ``True`` if any task has FAILED."""
        return any(t.status == TaskStatus.FAILED for t in self._tasks.values())

    # ------------------------------------------------------------------
    # State transitions (called by Scheduler)
    # ------------------------------------------------------------------

    def mark_completed(self, task_id: str, result: str = "") -> list[Task]:
        """
        Mark *task_id* as COMPLETED.

        Returns the list of tasks that became READY as a result — callers
        can enqueue them immediately.

        Raises:
            KeyError: If *task_id* is not in the graph.
        """
        task = self._tasks[task_id]
        task.mark_completed(result)
        logger.debug("TaskGraph: task %r completed", task.title)
        # Unlock any tasks that were waiting on this one.
        newly_ready = self.get_ready_tasks()
        for t in newly_ready:
            t.mark_ready()
        return newly_ready

    def mark_failed(self, task_id: str, error: str = "") -> list[Task]:
        """
        Mark *task_id* as FAILED.

        Returns the list of tasks that were transitively blocked as a result
        (all downstream dependents move to BLOCKED).

        Raises:
            KeyError: If *task_id* is not in the graph.
        """
        task = self._tasks[task_id]
        task.mark_failed(error)
        logger.warning("TaskGraph: task %r failed: %s", task.title, error)
        blocked = self._block_downstream(task_id)
        return blocked

    def _block_downstream(self, failed_id: str) -> list[Task]:
        """
        Recursively block all tasks that depend (directly or transitively) on
        *failed_id*.  Returns the full list of newly-blocked tasks.
        """
        blocked: list[Task] = []
        for task in self._tasks.values():
            if task.status == TaskStatus.PENDING and failed_id in task.dependencies:
                task.mark_blocked()
                blocked.append(task)
                blocked.extend(self._block_downstream(task.id))
        return blocked

    # ------------------------------------------------------------------
    # Topological sort (Kahn's algorithm)
    # ------------------------------------------------------------------

    def topological_order(self) -> list[Task]:
        """
        Return tasks in a safe execution order (every task appears after all
        its dependencies).

        Raises:
            TaskGraphError: If the graph contains a cycle.
        """
        in_degree: dict[str, int] = {tid: 0 for tid in self._tasks}
        children: dict[str, list[str]] = {tid: [] for tid in self._tasks}

        for task in self._tasks.values():
            for dep_id in task.dependencies:
                if dep_id in self._tasks:
                    in_degree[task.id] += 1
                    children[dep_id].append(task.id)

        queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
        order: list[Task] = []

        while queue:
            tid = queue.popleft()
            order.append(self._tasks[tid])
            for child_id in children[tid]:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        if len(order) != len(self._tasks):
            raise TaskGraphError(
                "TaskGraph contains a cycle — execution plan is invalid."
            )
        return order

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def as_display_lines(self) -> list[str]:
        """
        Return a human-readable ASCII representation of the task graph
        suitable for the `plan` console command.

        Example output:
            Goal
            ↓
            1. Research
            ↓
            2. Design
            ↓
            3. Implementation
            ↓
            4. Testing
            ↓
            5. Review
        """
        try:
            ordered = self.topological_order()
        except TaskGraphError:
            ordered = list(self._tasks.values())

        lines: list[str] = ["Goal"]
        for i, task in enumerate(ordered, start=1):
            lines.append("↓")
            status_badge = {
                TaskStatus.PENDING: "",
                TaskStatus.READY: " [ready]",
                TaskStatus.RUNNING: " [running…]",
                TaskStatus.BLOCKED: " [blocked]",
                TaskStatus.COMPLETED: " [✓]",
                TaskStatus.FAILED: " [✗]",
            }.get(task.status, "")
            lines.append(f"Task {i}  {task.title}{status_badge}")
        return lines

    def __len__(self) -> int:
        return len(self._tasks)

    def __repr__(self) -> str:
        return f"TaskGraph({len(self._tasks)} tasks)"
