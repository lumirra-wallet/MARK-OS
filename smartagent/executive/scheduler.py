"""
Scheduler — Phase 11.4/11.5 upgrade: real AI workers, retry logic, progress display.

Phase 11.4 additions:
  - Real Ollama-powered workers via OllamaWorkerMixin
  - Per-task timing (wall-clock seconds)
  - Confidence score tracking in ExecutionContext.metadata

Phase 11.5 additions:
  - Automatic retry on transient worker failures (configurable max_retries)
  - Console progress display (task start/complete/fail with timing)
  - Stores per-task metadata (timing, confidence, retry count)

All Phase 2/3 behaviour is preserved: dependency ordering, cancellation,
terminal-state detection, and the ``Scheduler.run()`` return contract are
unchanged.
"""

from __future__ import annotations

import sys
import time
from typing import Optional, TYPE_CHECKING

from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.task import Task, TaskStatus
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.worker_registry import WorkerRegistry

logger = get_logger(__name__)

_MAX_ITERATIONS = 1_000

# Status icons for console output
_ICON_RUN = "▶"
_ICON_OK  = "✓"
_ICON_ERR = "✗"
_ICON_RET = "↺"


class Scheduler:
    """
    Synchronous, dependency-aware task scheduler with retry support.

    Args:
        worker_registry: Maps task types to worker classes.
        max_retries:     How many times to retry a failing task before
                         marking it as FAILED.  Default 2 (= up to 3 total
                         attempts).  Set to 0 to disable retries.
        show_progress:   Print per-task progress to stdout.  Default True.
                         Tests can set this to False for cleaner output.
    """

    def __init__(
        self,
        worker_registry: Optional["WorkerRegistry"] = None,
        max_retries: int = 2,
        show_progress: bool = True,
    ) -> None:
        self._worker_registry = worker_registry
        self._max_retries = max_retries
        self._show_progress = show_progress
        # Subsystem isolation: track the last active subsystem for handoff logging.
        self._current_subsystem: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, context: ExecutionContext) -> ExecutionContext:
        """
        Execute all tasks in *context* in dependency order.

        Phase 11.4/11.5 changes (backward-compatible):
          - Shows console progress per task.
          - Retries transient failures up to ``max_retries`` times.
          - Records per-task timing in ``context.metadata["task_timing"]``.

        Returns the updated ``ExecutionContext``.
        """
        if context.is_cancelled:
            logger.info("Scheduler: context already cancelled — skipping execution")
            return context

        context.transition_to(ExecutionState.RUNNING)
        logger.info(
            "Scheduler: starting execution  goal=%r  tasks=%d",
            context.goal, context.task_count,
        )

        # Ensure metadata containers exist
        context.metadata.setdefault("task_timing", {})
        context.metadata.setdefault("task_confidence", {})
        context.metadata.setdefault("task_retries", {})

        self._seed_queue(context)

        iteration = 0
        while not context.task_queue.is_empty() and iteration < _MAX_ITERATIONS:
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

            if context.task_queue.is_empty():
                for t in context.task_graph.get_ready_tasks():
                    t.mark_ready()
                    context.task_queue.enqueue(t)

        if context.is_cancelled:
            return context

        all_tasks = context.task_graph.all_tasks()
        failed = any(t.status == TaskStatus.FAILED for t in all_tasks)
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

        self._print_execution_summary(context)
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
        """
        Dispatch *task*, recording outcome, timing, and confidence.

        Phase 11.5: retries the task up to ``_max_retries`` times before
        marking it failed.  Each retry attempt is logged to the console.

        Subsystem Isolation: emits a handoff banner when the active subsystem
        changes between consecutive tasks.
        """
        # Subsystem handoff detection
        task_subsystem = getattr(task, "subsystem", "generic")
        if self._current_subsystem is not None and task_subsystem != self._current_subsystem:
            banner = f"── switching subsystem: {self._current_subsystem} → {task_subsystem} ──"
            logger.info("Scheduler: %s", banner)
            self._print(banner)
        self._current_subsystem = task_subsystem

        task.mark_running()
        logger.info(
            "Scheduler: running %r  type=%s  subsystem=%s",
            task.title, task.task_type.value, task_subsystem,
        )
        self._print_task_start(task)

        last_error: str = ""
        attempts = 0
        start_wall = time.monotonic()

        while attempts <= self._max_retries:
            try:
                result = self._execute(task, context)
                elapsed = time.monotonic() - start_wall
                context.metadata["task_timing"][task.id] = round(elapsed, 2)
                context.metadata["task_retries"][task.id] = attempts

                newly_ready = context.task_graph.mark_completed(task.id, result)
                context.record_result(task.id, result)
                for t in newly_ready:
                    context.task_queue.enqueue(t)

                logger.debug(
                    "Scheduler: %r completed in %.2fs (attempt %d) — unlocked %d tasks",
                    task.title, elapsed, attempts + 1, len(newly_ready),
                )
                self._print_task_done(task, elapsed, context)
                return  # success — exit retry loop

            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                attempts += 1
                if attempts <= self._max_retries:
                    logger.warning(
                        "Scheduler: %r failed (attempt %d/%d): %s — retrying",
                        task.title, attempts, self._max_retries + 1, last_error,
                    )
                    self._print_task_retry(task, attempts, last_error)
                    time.sleep(0.3 * attempts)  # brief back-off: 0.3s, 0.6s, …

        # All attempts exhausted
        elapsed = time.monotonic() - start_wall
        context.metadata["task_timing"][task.id] = round(elapsed, 2)
        context.metadata["task_retries"][task.id] = attempts - 1

        blocked = context.task_graph.mark_failed(task.id, last_error)
        context.record_error(task.id, last_error)
        logger.warning(
            "Scheduler: %r failed after %d attempts (%s) — blocked %d tasks",
            task.title, attempts, last_error, len(blocked),
        )
        self._print_task_fail(task, elapsed, last_error)

    def _execute(self, task: Task, context: ExecutionContext) -> str:
        """
        Dispatch *task* to its registered worker and return the result.

        Phase 11.4: uses real Ollama-powered workers when available.
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

        # Phase 1 stub
        return f"Completed: {task.title}"

    # ------------------------------------------------------------------
    # Console progress display (Phase 11.5)
    # ------------------------------------------------------------------

    def _print(self, msg: str) -> None:
        """Write *msg* to stdout if progress display is enabled."""
        if self._show_progress:
            print(msg, flush=True)

    def _print_task_start(self, task: Task) -> None:
        self._print(
            f"  {_ICON_RUN}  [{task.task_type.value:14s}] {task.title}"
        )

    def _print_task_done(
        self,
        task: Task,
        elapsed: float,
        context: ExecutionContext,
    ) -> None:
        confidence = context.metadata.get("task_confidence", {}).get(task.id)
        conf_str = f"  confidence={confidence:.0%}" if confidence is not None else ""
        self._print(
            f"  {_ICON_OK}  [{task.task_type.value:14s}] {task.title}"
            f"  ({elapsed:.1f}s{conf_str})"
        )

    def _print_task_fail(self, task: Task, elapsed: float, error: str) -> None:
        short_err = error[:60] + "…" if len(error) > 60 else error
        self._print(
            f"  {_ICON_ERR}  [{task.task_type.value:14s}] {task.title}"
            f"  ({elapsed:.1f}s) — {short_err}"
        )

    def _print_task_retry(self, task: Task, attempt: int, error: str) -> None:
        short_err = error[:50] + "…" if len(error) > 50 else error
        self._print(
            f"  {_ICON_RET}  [{task.task_type.value:14s}] {task.title}"
            f"  retry {attempt} — {short_err}"
        )

    def _print_execution_summary(self, context: ExecutionContext) -> None:
        """Print a one-line summary after all tasks finish."""
        state = context.state.value
        icon = _ICON_OK if state == "completed" else _ICON_ERR
        total_time = sum(context.metadata.get("task_timing", {}).values())

        confidences = list(context.metadata.get("task_confidence", {}).values())
        avg_conf = (
            sum(confidences) / len(confidences) if confidences else None
        )
        conf_str = f"  avg confidence={avg_conf:.0%}" if avg_conf is not None else ""

        self._print(
            f"\n  {icon}  {state.upper()}  "
            f"{context.completed_count}/{context.task_count} tasks"
            f"  total={total_time:.1f}s{conf_str}"
        )
