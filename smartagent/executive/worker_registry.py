"""
WorkerRegistry — maps task types to worker classes (Phase 2 upgrade).

In Phase 1 the registry stored string labels.
In Phase 2 it stores real ``BaseWorker`` subclasses — the ``Scheduler``
instantiates them and calls ``worker.execute(task, context)``.

``build_default_registry()`` is the single place that wires all workers.
The console ``workers`` command reads ``list_workers()`` directly from here.
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.workers.base_worker import BaseWorker

logger = get_logger(__name__)


class WorkerRegistry:
    """
    Registry mapping ``TaskType`` values to ``BaseWorker`` subclasses.

    Phase 2: stores actual ``BaseWorker`` subclasses; ``get()`` returns a
             class that the Scheduler instantiates per-dispatch.
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
            worker:    A ``BaseWorker`` subclass (Phase 2+) or a label (Phase 1).
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

        Falls back to the ``TaskType.GENERIC`` worker when the specific
        type is not explicitly registered.
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
        Return one dict per registered worker with keys:
          ``task_type``, ``worker``, ``name``, ``description``, ``phase``.

        ``name`` / ``description`` / ``phase`` come from the worker instance
        when *worker* is a real class; fall back to the class name / "—" / "—"
        otherwise.
        """
        rows: list[dict[str, str]] = []
        seen_classes: set[int] = set()
        for task_type_key, worker in self._workers.items():
            # Deduplicate by identity so multi-type workers (CodingWorker handles
            # CODING + IMPLEMENTATION) appear only once in the listing.
            worker_id = id(worker)
            if worker_id in seen_classes:
                continue
            seen_classes.add(worker_id)

            class_name = getattr(worker, "__name__", str(worker))
            # Instantiate temporarily to read descriptive properties.
            try:
                instance = worker()
                display_name = instance.name
                desc = instance.description
                phase = instance.phase
            except Exception:
                display_name = class_name
                desc = "—"
                phase = "—"

            rows.append({
                "task_type": task_type_key,
                "worker": class_name,
                "name": display_name,
                "description": desc,
                "phase": phase,
            })
        return rows

    def count(self) -> int:
        """Number of registered task-type → worker mappings."""
        return len(self._workers)

    def unique_worker_count(self) -> int:
        """Number of unique worker classes registered (deduplicated)."""
        return len({id(w) for w in self._workers.values()})

    def __repr__(self) -> str:
        return f"WorkerRegistry({self.count()} mappings, {self.unique_worker_count()} workers)"


def build_default_registry() -> WorkerRegistry:
    """
    Build the default ``WorkerRegistry`` with real Phase 2 worker classes.

    Each worker class is registered once per ``TaskType`` it handles.
    Multi-type workers (e.g. CodingWorker handles CODING + IMPLEMENTATION)
    are registered for each type individually; ``list_workers()`` deduplicates
    by class identity for display.

    Phase 4: replace stub workers with Ollama-connected implementations by
    changing the import — the registry wiring stays identical.
    """
    from smartagent.executive.workers.research_worker import ResearchWorker
    from smartagent.executive.workers.planning_worker import PlanningWorker
    from smartagent.executive.workers.design_worker import DesignWorker
    from smartagent.executive.workers.coding_worker import CodingWorker
    from smartagent.executive.workers.testing_worker import TestingWorker
    from smartagent.executive.workers.review_worker import ReviewWorker
    from smartagent.executive.workers.documentation_worker import DocumentationWorker
    from smartagent.executive.workers.report_worker import ReportWorker
    from smartagent.executive.workers.knowledge_worker import KnowledgeWorker

    # GenericWorker — used as fallback for unrecognised task types.
    class _GenericWorker:
        name = "Generic Worker"
        task_types = [TaskType.GENERIC]
        description = "Fallback handler for unrecognised task types."
        phase = "stub"

        def execute(self, task, context):
            return f"[Generic] Completed: {task.title}"

    reg = WorkerRegistry()

    mappings: list[tuple[TaskType, Any]] = [
        (TaskType.RESEARCH,       ResearchWorker),
        (TaskType.PLANNING,       PlanningWorker),
        (TaskType.DESIGN,         DesignWorker),
        (TaskType.ARCHITECTURE,   DesignWorker),       # DesignWorker handles both
        (TaskType.CODING,         CodingWorker),
        (TaskType.IMPLEMENTATION, CodingWorker),       # CodingWorker handles both
        (TaskType.TESTING,        TestingWorker),
        (TaskType.REVIEW,         ReviewWorker),
        (TaskType.DOCUMENTATION,  DocumentationWorker),
        (TaskType.REPORT,         ReportWorker),
        (TaskType.ANALYSIS,       KnowledgeWorker),
        (TaskType.GENERIC,        _GenericWorker),
    ]

    for task_type, worker_class in mappings:
        reg.register(task_type, worker_class)

    return reg
