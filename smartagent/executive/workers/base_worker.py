"""
BaseWorker — abstract base class for all MARK specialist workers.

Architecture rule:
    Workers are the execution units of the MARK Executive Framework.
    They receive a ``Task`` and an ``ExecutionContext``, do their work,
    and return a result string.  They are stateless — no instance variables
    should be mutated between calls.

Interface::

    worker = ResearchWorker()
    result = worker.execute(task, context)   # → "Research complete: …"

Phase 2:
    Workers return a descriptive stub result so the full pipeline is
    end-to-end runnable without connecting to Ollama.

Phase 4 upgrade path:
    Override ``execute()`` to call ``model_manager.generate_stream()``
    with a specialist system prompt.  The ``ExecutionContext`` carries
    results from prior tasks so each worker can read sibling outputs.

Design rules:
    - Workers are never imported by name outside ``worker_registry.py``
      and ``workers/__init__.py``.
    - Workers must not mutate ``task.status`` directly — the ``Scheduler``
      owns status transitions.  Workers return a string; the Scheduler
      calls ``task.mark_completed(result)`` or ``task.mark_failed(error)``.
    - A worker that cannot complete its work raises an exception.
      The Scheduler catches it and calls ``task.mark_failed()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task, TaskType


@dataclass
class WorkerResult:
    """
    Structured result returned by a worker.

    ``text`` is the primary result forwarded to downstream tasks.
    ``metadata`` carries optional metrics (token count, elapsed time, etc.)
    that the Scheduler records without affecting routing logic.
    """

    text: str
    metadata: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}

    def __str__(self) -> str:
        return self.text


class BaseWorker(ABC):
    """
    Abstract base for all MARK worker agents.

    Subclasses must implement:
        ``name``       — short identifier used in console listings
        ``task_types`` — list of ``TaskType`` values this worker handles
        ``execute()``  — perform the work and return a result string
    """

    # ------------------------------------------------------------------
    # Identity (must be overridden by subclasses)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Short display name, e.g. "Research Worker"."""
        ...

    @property
    @abstractmethod
    def task_types(self) -> list["TaskType"]:
        """``TaskType`` values this worker is registered to handle."""
        ...

    @property
    def description(self) -> str:
        """
        One-line description of what this worker does.
        Override in subclasses for richer ``worker info`` output.
        """
        return f"Handles {', '.join(t.value for t in self.task_types)} tasks."

    @property
    def phase(self) -> str:
        """
        Implementation phase.  ``"stub"`` in Phase 2; ``"ollama"`` in Phase 4.
        Used by ``worker info`` to flag which workers have real AI integration.
        """
        return "stub"

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @abstractmethod
    def execute(
        self,
        task: "Task",
        context: "ExecutionContext",
    ) -> str:
        """
        Perform the work for *task* within *context* and return the result.

        Args:
            task:    The task to execute.  ``task.description`` contains the
                     full context (goal, phase).  Do not mutate ``task.status``.
            context: The live execution context.  Prior task results are
                     accessible via ``context.get_result(task_id)``.

        Returns:
            A non-empty result string.  This becomes ``task.result`` after
            the Scheduler calls ``task.mark_completed()``.

        Raises:
            Any exception signals failure — the Scheduler calls
            ``task.mark_failed(str(exc))``.
        """
        ...

    # ------------------------------------------------------------------
    # Convenience helpers available to subclasses
    # ------------------------------------------------------------------

    def _prior_results(self, task: "Task", context: "ExecutionContext") -> list[str]:
        """
        Return the result strings of all tasks that *task* depends on,
        in dependency order.  Returns an empty list if none are available.
        """
        results: list[str] = []
        for dep_id in task.dependencies:
            result = context.get_result(dep_id)
            if result:
                results.append(result)
        return results

    def __repr__(self) -> str:
        types = ", ".join(t.value for t in self.task_types)
        return f"{self.__class__.__name__}(task_types=[{types}])"
