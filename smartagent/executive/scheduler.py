"""
Scheduler — executes a TaskGraph in dependency order (Phase 1/3).

The Scheduler is the "operating system kernel" of MARK's executive layer.
It knows which tasks can run (READY), runs them through the appropriate
worker, and unlocks downstream tasks as each one completes.

Phase 1 behaviour:
    No real workers yet.  The Scheduler calls ``_execute_stub()`` which
    marks every task COMPLETED with "Completed" as the result.  This
    gives the framework a runnable state so ``run`` and ``plan`` commands
    work end-to-end before Phase 2 adds real workers.

Phase 2 upgrade:
    Replace ``_execute_stub()`` with ``worker_registry.get(task.task_type)``
    and call ``worker.execute(task, context)``.  Everything else stays the
    same.

Task lifecycle inside the Scheduler:
    PENDING  → READY    (graph unlocks it)
    READY    → RUNNING  (scheduler picks it up)
    RUNNING  → COMPLETED / FAILED  (worker finishes)
    PENDING  → BLOCKED  (upstream failed)
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.task import Task, TaskStatus
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.worker_registry import WorkerRegistry

logger = get_logger(__name__)

# Guard against infinite loops in degenerate graphs.
_MAX_ITERATIONS = 1_000


class Scheduler:
    """
    Synchronous, single-threaded task scheduler.

    Accepts an ``ExecutionContext`` whose ``task_graph`` and ``task_queue``
    have been populated by ``ExecutiveController``, then runs all tasks to
    completion (or failure) before returning the updated context.

    Phase 3 will replace this with an async / threaded scheduler that
    supports parallel task execution.  The interface (``run(context)``)
    remains identical.
    """

    def __init__(self, worker_registry: Optional["WorkerRegistry"] = None) -> None:
        """
        Args:
            worker_registry: Registry of worker classes used for task dispatch.
                             ``None`` in Phase 1 — stub execution is used instead.
        """
        self._worker_registry = worker_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, context: ExecutionContext) -> ExecutionContext:
        """
        Execute all tasks in *context* in dependency order.

        Modifies *context* in-place (updates task statuses, results, errors,
        and execution state) and returns it for convenience.

        Returns:
            The updated ``ExecutionContext``.
        """
        context.transition_to(ExecutionState.RUNNING)
        logger.info("Scheduler: starting execution for goal=%r (%d tasks)", context.goal, context.task_count)

        # Seed the queue with initial READY tasks (tasks with no dependencies).
        self._seed_queue(context)

        iteration = 0
        while not context.task_queue.is_empty() and iteration < _MAX_ITERATIONS:
            iteration += 1
            task = context.task_queue.dequeue()
            if task is None:
                break
            self._run_task(task, context)

            # After a task completes/fails, check if new tasks became ready.
            if not context.task_queue.is_empty():
                continue  # more tasks already queued — keep going
            # Queue drained — ask graph for newly-unlocked tasks.
            newly_ready = context.task_graph.get_ready_tasks()
            for t in newly_ready:
                t.mark_ready()
                context.task_queue.enqueue(t)

        # Determine final state.
        if context.task_graph.all_completed():
            failed = any(t.status == TaskStatus.FAILED for t in context.task_graph.all_tasks())
            final = ExecutionState.FAILED if failed else ExecutionState.COMPLETED
        else:
            # Leftover BLOCKED or PENDING tasks — treat as partial failure.
            final = ExecutionState.FAILED

        context.transition_to(final)
        logger.info(
            "Scheduler: finished.  state=%s  completed=%d/%d",
            final.value, context.completed_count, context.task_count,
        )
        return context

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _seed_queue(self, context: ExecutionContext) -> None:
        """
        Move the initial wave of PENDING tasks (no dependencies) to READY
        and enqueue them so the run-loop has something to start with.
        """
        for task in context.task_graph.all_tasks():
            if task.status == TaskStatus.PENDING and not task.dependencies:
                task.mark_ready()
                context.task_queue.enqueue(task)
        logger.debug("Scheduler: seeded queue with %d initial tasks", context.task_queue.size())

    def _run_task(self, task: Task, context: ExecutionContext) -> None:
        """
        Dispatch *task* to a worker (or stub), record the outcome, and
        notify the ``TaskGraph`` so it can unlock dependents.
        """
        task.mark_running()
        logger.info("Scheduler: running task %r (%s)", task.title, task.task_type.value)

        try:
            result = self._execute(task, context)
            newly_ready = context.task_graph.mark_completed(task.id, result)
            context.record_result(task.id, result)
            for t in newly_ready:
                context.task_queue.enqueue(t)
            logger.debug("Scheduler: task %r completed; unlocked %d tasks", task.title, len(newly_ready))
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            blocked = context.task_graph.mark_failed(task.id, error)
            context.record_error(task.id, error)
            logger.warning("Scheduler: task %r failed (%s); blocked %d tasks", task.title, error, len(blocked))

    def _execute(self, task: Task, context: ExecutionContext) -> str:
        """
        Execute *task* and return its result string.

        Phase 1: returns a stub result so the framework is end-to-end
        runnable without real workers.

        Phase 2 upgrade: look up the worker in ``_worker_registry`` and
        call ``worker.execute(task, context)`` instead.
        """
        if self._worker_registry is not None:
            worker_class = self._worker_registry.get(task.task_type)
            if worker_class is not None and callable(worker_class):
                try:
                    worker = worker_class()
                    return worker.execute(task, context)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"Worker {worker_class} failed: {exc}") from exc

        # Phase 1 stub — mark every task done immediately.
        return f"Completed: {task.title}"
