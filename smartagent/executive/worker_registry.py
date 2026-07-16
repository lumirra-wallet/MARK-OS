"""
WorkerRegistry — maps task types to worker classes.

In Phase 1 the registry is populated with stub entries (strings) so the
``Planner`` can display which worker *would* handle each task.

In Phase 2 real ``BaseWorker`` subclasses are registered here, and the
``Scheduler`` queries the registry to instantiate the right worker for
each task before calling ``worker.execute(task, context)``.

Design rules:
- Registration is by ``TaskType`` value (string) for JSON-serialisability.
- ``get()`` returns ``None`` on miss — callers decide whether to fall back
  to a generic worker or raise.
- ``list_workers()`` is what the ``workers`` console command reads (Phase 2).
"""

from __future__ import annotations

from typing import Any, Optional

from smartagent.executive.task import TaskType
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


class WorkerRegistry:
    """
    Registry mapping ``TaskType`` values to worker classes (or stub names).

    Phase 1: stores human-readable string labels so the console can list
             "registered" workers without any real implementation.
    Phase 2: stores actual ``BaseWorker`` subclasses; ``get()`` returns a
             class that can be instantiated and called.
    """

    def __init__(self) -> None:
        # Maps task_type.value (str) → worker class or label (Any)
        self._workers: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, task_type: "str | TaskType", worker: Any) -> None:
        """
        Register *worker* for *task_type*.

        Args:
            task_type: A ``TaskType`` enum member or its string value.
            worker:    The worker class (Phase 2+) or a label string (Phase 1).
        """
        key = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        self._workers[key] = worker
        label = getattr(worker, "__name__", str(worker))
        logger.debug("WorkerRegistry: registered %r → %s", key, label)

    def unregister(self, task_type: "str | TaskType") -> None:
        """Remove the worker registered for *task_type*, if any."""
        key = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        self._workers.pop(key, None)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, task_type: "str | TaskType") -> Optional[Any]:
        """
        Return the worker registered for *task_type*, or ``None``.

        Falls back to the ``TaskType.GENERIC`` worker if the specific type
        is not registered.
        """
        key = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        return self._workers.get(key) or self._workers.get(TaskType.GENERIC.value)

    def has(self, task_type: "str | TaskType") -> bool:
        """Return ``True`` if a worker is registered for *task_type*."""
        key = task_type.value if isinstance(task_type, TaskType) else str(task_type)
        return key in self._workers

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def list_workers(self) -> list[dict[str, str]]:
        """
        Return a list of ``{task_type, worker}`` dicts — one per registration.

        Used by the ``workers`` console command (Phase 2).
        """
        rows: list[dict[str, str]] = []
        for task_type_key, worker in self._workers.items():
            label = getattr(worker, "__name__", str(worker))
            rows.append({"task_type": task_type_key, "worker": label})
        return rows

    def count(self) -> int:
        """Number of registered worker types."""
        return len(self._workers)

    def __repr__(self) -> str:
        return f"WorkerRegistry({len(self._workers)} workers)"


def build_default_registry() -> WorkerRegistry:
    """
    Build the default ``WorkerRegistry`` with Phase 1 stub labels.

    In Phase 2 this function will be updated to import and register real
    ``BaseWorker`` subclasses.  The label strings here are the names that
    will become class names in Phase 2.
    """
    reg = WorkerRegistry()
    stubs = [
        (TaskType.RESEARCH,       "ResearchWorker"),
        (TaskType.PLANNING,       "PlanningWorker"),
        (TaskType.DESIGN,         "DesignWorker"),
        (TaskType.ARCHITECTURE,   "ArchitectureWorker"),
        (TaskType.CODING,         "CodingWorker"),
        (TaskType.IMPLEMENTATION, "ImplementationWorker"),
        (TaskType.TESTING,        "TestingWorker"),
        (TaskType.REVIEW,         "ReviewWorker"),
        (TaskType.DOCUMENTATION,  "DocumentationWorker"),
        (TaskType.ANALYSIS,       "AnalysisWorker"),
        (TaskType.REPORT,         "ReportWorker"),
        (TaskType.GENERIC,        "GenericWorker"),
    ]
    for task_type, label in stubs:
        reg.register(task_type, label)
    return reg
