"""
ParallelScheduler — Milestone 13: Parallel Executive Engine.

Upgrades the MARK Executive to execute independent tasks simultaneously
using ``ThreadPoolExecutor``.  Tasks only start once ALL their dependencies
have completed — the DAG ordering from ``TaskGraph`` is preserved exactly.

Design principles:
  - One ``state_lock`` (``threading.Lock``) guards every mutation to the
    task graph, ``ExecutionContext.results``, ``ExecutionContext.errors``,
    and the ``submitted_ids`` tracking set.  Workers run fully in parallel
    inside each call to ``_work()``; only the result-recording step is
    serialised.
  - Metadata containers (``task_timing``, ``task_confidence``, etc.) are
    pre-initialised before any thread starts so per-key writes are safe
    under CPython's GIL without extra locking.
  - The existing serial ``Scheduler`` is NOT modified — parallel execution
    is opt-in via ``ExecutiveController(use_parallel=True)``.
  - No asyncio.  Pure ``ThreadPoolExecutor`` as specified.

Performance metrics are recorded in
``context.metadata["parallel_metrics"]`` after every run::

    {
        "wall_time": float,               # actual elapsed seconds
        "sequential_estimate": float,     # sum of individual task times
        "speedup": float,                 # sequential_estimate / wall_time
        "max_workers": int,
        "tasks_completed": int,
        "tasks_failed": int,
    }
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait as futures_wait
from concurrent.futures import FIRST_COMPLETED
from typing import Optional

from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.task import Task, TaskStatus
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_ICON_RUN = "▶"
_ICON_OK  = "✓"
_ICON_ERR = "✗"
_ICON_RET = "↺"

# Poll interval for the cancellation check inside futures_wait()
_POLL_TIMEOUT = 0.5


class ParallelScheduler:
    """
    DAG-respecting parallel task scheduler for the MARK Executive.

    Args:
        worker_registry: Maps ``TaskType`` → worker class.  Pass ``None``
            for the default stub-only behaviour used in early tests.
        max_workers:     Thread pool size.  Should be read from
            ``Settings.max_parallel_workers``; default 4.
        show_progress:   Print per-task start/done lines to stdout.
        max_retries:     How many times to retry a failing task before
            propagating the error to the main loop.  Default 2.
    """

    def __init__(
        self,
        worker_registry=None,
        max_workers: int = 4,
        show_progress: bool = True,
        max_retries: int = 2,
    ) -> None:
        self._worker_registry = worker_registry
        self._max_workers = max_workers
        self._show_progress = show_progress
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, context: ExecutionContext) -> ExecutionContext:
        """
        Execute all tasks in *context* in parallel where dependencies allow.

        Returns the updated ``ExecutionContext``.
        """
        if context.is_cancelled:
            logger.info("ParallelScheduler: context already cancelled — skipping")
            return context

        context.transition_to(ExecutionState.RUNNING)
        logger.info(
            "ParallelScheduler: starting  goal=%r  tasks=%d  max_workers=%d",
            context.goal, context.task_count, self._max_workers,
        )

        # Pre-initialise metadata containers to avoid TOCTOU races between threads
        context.metadata.setdefault("task_timing", {})
        context.metadata.setdefault("task_confidence", {})
        context.metadata.setdefault("task_retries", {})

        state_lock = threading.Lock()
        submitted_ids: set[str] = set()
        t_start = time.monotonic()

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            pending: dict[Future, Task] = {}

            # Seed tasks that are ready to run (no deps, or already marked READY
            # by the Orchestrator's submit_to_queue() before we got here)
            with state_lock:
                for task in context.task_graph.all_tasks():
                    if task.status in (TaskStatus.PENDING, TaskStatus.READY) and (
                        not task.dependencies
                    ):
                        if task.status == TaskStatus.PENDING:
                            task.mark_ready()
                        submitted_ids.add(task.id)
                        f = executor.submit(self._work, task, context)
                        pending[f] = task

            logger.debug(
                "ParallelScheduler: seeded %d initial tasks", len(pending)
            )

            while pending:
                if context.is_cancelled:
                    logger.info("ParallelScheduler: cancelled mid-run")
                    break

                # Wait for at least one future to finish (with poll timeout)
                done_set, _ = futures_wait(
                    list(pending.keys()),
                    return_when=FIRST_COMPLETED,
                    timeout=_POLL_TIMEOUT,
                )

                for f in list(done_set):
                    task = pending.pop(f)
                    try:
                        result_text, timing, retries = f.result()

                        with state_lock:
                            newly_ready = context.task_graph.mark_completed(
                                task.id, result_text
                            )
                            context.record_result(task.id, result_text)
                            context.metadata["task_timing"][task.id] = timing
                            context.metadata["task_retries"][task.id] = retries

                            # Submit newly-unlocked tasks
                            for new_task in newly_ready:
                                if new_task.id not in submitted_ids:
                                    submitted_ids.add(new_task.id)
                                    nf = executor.submit(
                                        self._work, new_task, context
                                    )
                                    pending[nf] = new_task

                        logger.debug(
                            "ParallelScheduler: %r done (%.2fs) — unlocked %d",
                            task.title, timing, len(newly_ready),
                        )
                        self._print_done(task, timing, context)

                    except Exception as exc:  # noqa: BLE001
                        err = str(exc)
                        with state_lock:
                            blocked = context.task_graph.mark_failed(task.id, err)
                            context.record_error(task.id, err)
                            context.metadata["task_timing"][task.id] = 0.0

                        logger.warning(
                            "ParallelScheduler: %r failed: %s — blocked %d tasks",
                            task.title, err, len(blocked),
                        )
                        self._print_fail(task, err)

        # Determine final state
        total_wall = time.monotonic() - t_start
        self._record_performance_metrics(context, total_wall)

        if context.is_cancelled:
            return context

        all_tasks = context.task_graph.all_tasks()
        failed    = any(t.status == TaskStatus.FAILED for t in all_tasks)
        non_term  = any(not t.is_terminal for t in all_tasks)
        final_state = (
            ExecutionState.FAILED if (failed or non_term)
            else ExecutionState.COMPLETED
        )
        context.transition_to(final_state)

        logger.info(
            "ParallelScheduler: finished  state=%s  completed=%d/%d  "
            "wall=%.2fs  speedup=%.1fx",
            final_state.value,
            context.completed_count,
            context.task_count,
            total_wall,
            context.metadata["parallel_metrics"].get("speedup", 1.0),
        )
        self._print_summary(context, total_wall)
        return context

    # ------------------------------------------------------------------
    # Task execution (runs in worker threads)
    # ------------------------------------------------------------------

    def _work(self, task: Task, context: ExecutionContext) -> tuple[str, float, int]:
        """
        Execute *task* (with retry) and return ``(result, elapsed, retries)``.

        Raised exceptions propagate to the calling future and are caught in
        the main loop, which records the failure without crashing.
        """
        task.mark_running()
        self._print_start(task)

        t0 = time.monotonic()
        last_error = ""
        retries = 0

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                retries = attempt
                self._print_retry(task, attempt, last_error)
                time.sleep(0.3 * attempt)

            try:
                result = self._execute(task, context)
                elapsed = round(time.monotonic() - t0, 2)
                return result, elapsed, retries
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)

        # All retries exhausted — raise so the main loop records failure
        elapsed = time.monotonic() - t0
        raise RuntimeError(
            f"Task {task.title!r} failed after {self._max_retries + 1} "
            f"attempts: {last_error}"
        )

    def _execute(self, task: Task, context: ExecutionContext) -> str:
        """Dispatch *task* to its registered worker and return the result."""
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
        return f"Completed: {task.title}"

    # ------------------------------------------------------------------
    # Performance metrics
    # ------------------------------------------------------------------

    def _record_performance_metrics(
        self, context: ExecutionContext, total_wall: float
    ) -> None:
        """
        Store parallel execution metrics in ``context.metadata["parallel_metrics"]``.
        """
        task_times = context.metadata.get("task_timing", {})
        sequential_estimate = sum(task_times.values())
        speedup = (
            sequential_estimate / total_wall
            if total_wall > 0 and sequential_estimate > 0
            else 1.0
        )
        context.metadata["parallel_metrics"] = {
            "wall_time": round(total_wall, 3),
            "sequential_estimate": round(sequential_estimate, 3),
            "speedup": round(speedup, 2),
            "max_workers": self._max_workers,
            "tasks_completed": context.completed_count,
            "tasks_failed": context.failed_count,
        }

    # ------------------------------------------------------------------
    # Console display
    # ------------------------------------------------------------------

    def _print(self, msg: str) -> None:
        if self._show_progress:
            print(msg, flush=True)

    def _print_start(self, task: Task) -> None:
        self._print(
            f"  {_ICON_RUN}  [{task.task_type.value:14s}] {task.title}"
        )

    def _print_done(
        self, task: Task, elapsed: float, context: ExecutionContext
    ) -> None:
        confidence = context.metadata.get("task_confidence", {}).get(task.id)
        conf_str = f"  confidence={confidence:.0%}" if confidence is not None else ""
        self._print(
            f"  {_ICON_OK}  [{task.task_type.value:14s}] {task.title}"
            f"  ({elapsed:.1f}s{conf_str})"
        )

    def _print_fail(self, task: Task, error: str) -> None:
        short = error[:60] + "…" if len(error) > 60 else error
        self._print(
            f"  {_ICON_ERR}  [{task.task_type.value:14s}] {task.title}"
            f"  — {short}"
        )

    def _print_retry(self, task: Task, attempt: int, error: str) -> None:
        short = error[:50] + "…" if len(error) > 50 else error
        self._print(
            f"  {_ICON_RET}  [{task.task_type.value:14s}] {task.title}"
            f"  retry {attempt} — {short}"
        )

    def _print_summary(self, context: ExecutionContext, wall: float) -> None:
        m = context.metadata.get("parallel_metrics", {})
        icon = _ICON_OK if context.state == ExecutionState.COMPLETED else _ICON_ERR
        speedup = m.get("speedup", 1.0)
        self._print(
            f"\n  {icon}  {context.state.value.upper()}  "
            f"{context.completed_count}/{context.task_count} tasks  "
            f"wall={wall:.1f}s  speedup={speedup:.1f}x"
        )
