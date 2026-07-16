"""
Scheduler — executes a TaskGraph in dependency order (Phase 2/3 upgrade).

Phase 1: stub workers, no real execution.
Phase 2: real ``BaseWorker`` subclasses dispatched via ``WorkerRegistry``.
Phase 3: full state machine, cancellation support, ``run``/``cancel`` commands.

Task lifecycle inside the Scheduler:
    PENDING  → READY    (graph unlocks it when all deps complete)
    READY    → RUNNING  (scheduler dequeues and dispatches it)
    RUNNING  → COMPLETED / FAILED  (worker finishes / raises)
    PENDING  → BLOCKED  (upstream task failed)

Cancellation (Phase 3):
    ``ExecutionContext.cancel()`` is called externally (e.g. from the
    ``cancel`` console command).  The Scheduler checks
    ``context.is_cancelled`` at the top of every iteration and stops
    cleanly without leaving tasks in RUNNING state.

Phase 3 notes on the console ``run`` command:
    The Scheduler is synchronous — ``run()`` blocks until complete.
    Phase 5 will replace this with an async runner for long-running goals.
    For Phase 3, synchronous is correct: ``run`` prints results after the
    call returns and the console stays responsive.
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

_MAX_ITERATIONS = 1_000


class Scheduler:
    """
    Synchronous, dependency-aware task scheduler.

    Accepts an ``ExecutionContext`` whose ``task_graph`` and ``task_queue``
    have been populated by ``ExecutiveController``, runs all tasks to
    completion (or failure/cancellation), and returns the updated context.
    """

    def __init__(self, worker_registry: Optional["WorkerRegistry"] = None) -> None:
        self._worker_registry = worker_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, context: ExecutionContext) -> ExecutionContext:
        """
        Execute all tasks in *context* in dependency order.

        Handles:
            - Seeding the queue with initially-ready tasks.
            - Dispatching each ready task to its worker.
            - Unlocking downstream tasks as tasks complete.
            - Blocking downstream tasks when a task fails.
            - Stopping cleanly when ``context.is_cancelled`` is True.

        Returns the updated ``ExecutionContext``.
        """
        # Phase 3: if the context was cancelled before run() was called,
        # return immediately without overwriting the CANCELLED state.
        if context.is_cancelled:
            logger.info("Scheduler: context already cancelled — skipping execution")
            return context

        context.transition_to(ExecutionState.RUNNING)
        logger.info(
            "Scheduler: starting execution  goal=%r  tasks=%d",
            context.goal, context.task_count,
        )

        self._seed_queue(context)

        iteration = 0
        while not context.task_queue.is_empty() and iteration < _MAX_ITERATIONS:
            # Phase 3: honour cancellation at each loop iteration.
            if context.is_cancelled:
                logger.info("Scheduler: execution cancelled after %d iterations", iteration)
                return context

            iteration += 1
            task = context.task_queue.dequeue()
            if task is None:
                break

            self._run_task(task, context)

            if context.is_cancelled:
                logger.info("Scheduler: execution cancelled mid-run")
                return context

            # Unlock newly-ready tasks after each completion.
            if context.task_queue.is_empty():
                for t in context.task_graph.get_ready_tasks():
                    t.mark_ready()
                    context.task_queue.enqueue(t)

        # Determine final state.
        if context.is_cancelled:
            return context  # already transitioned by cancel()

        all_tasks = context.task_graph.all_tasks()
        failed = any(t.status == TaskStatus.FAILED for t in all_tasks)
        # Treat any non-terminal task (BLOCKED, PENDING) as a failure —
        # they indicate unfinished work, e.g. because an upstream task failed.
        non_terminal = any(not t.is_terminal for t in all_tasks)
        final = (
            ExecutionState.FAILED if (failed or non_terminal)
            else ExecutionState.COMPLETED
        )
        context.transition_to(final)

        logger.info(
            "Scheduler: finished  state=%s  completed=%d/%d",
            final.value, context.completed_count, context.task_count,
        )
        return context

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _seed_queue(self, context: ExecutionContext) -> None:
        """Move initially-ready tasks (no deps) to READY and enqueue them."""
        for task in context.task_graph.all_tasks():
            if task.status == TaskStatus.PENDING and not task.dependencies:
                task.mark_ready()
                context.task_queue.enqueue(task)
        logger.debug("Scheduler: seeded %d initial tasks", context.task_queue.size())

    def _run_task(self, task: Task, context: ExecutionContext) -> None:
        """Dispatch *task*, record outcome, notify graph to unlock dependents."""
        task.mark_running()
        logger.info(
            "Scheduler: running %r  type=%s", task.title, task.task_type.value
        )
        try:
            result = self._execute(task, context)
            newly_ready = context.task_graph.mark_completed(task.id, result)
            context.record_result(task.id, result)
            for t in newly_ready:
                context.task_queue.enqueue(t)
            logger.debug(
                "Scheduler: %r completed — unlocked %d tasks",
                task.title, len(newly_ready),
            )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            blocked = context.task_graph.mark_failed(task.id, error)
            context.record_error(task.id, error)
            logger.warning(
                "Scheduler: %r failed (%s) — blocked %d tasks",
                task.title, error, len(blocked),
            )

    def _execute(self, task: Task, context: ExecutionContext) -> str:
        """
        Dispatch *task* to its registered worker and return the result.

        Phase 2: looks up the real worker class via ``_worker_registry``.
        Phase 1 fallback: returns a stub result when no registry is set.
        """
        if self._worker_registry is not None:
            worker_class = self._worker_registry.get(task.task_type)
            if worker_class is not None and callable(worker_class):
                try:
                    worker = worker_class()
                    return str(worker.execute(task, context))
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"Worker {worker_class.__name__} failed: {exc}"
                    ) from exc

        # Phase 1 stub — mark every task done immediately.
        return f"Completed: {task.title}"
