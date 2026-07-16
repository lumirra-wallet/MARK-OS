"""
MemoryWorker — reads from and writes to MARK's memory vault.

Phase 2: stub.
Phase 4: integrates with ``MemoryManager`` to persist key findings
         from prior tasks and surface relevant past experience.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class MemoryWorker(BaseWorker):
    """
    Specialist for memory operations — storing and retrieving past results.

    Handles: no specific TaskType alone; used as a support worker in Phase 4
    to persist key outputs after each phase completes.
    """

    @property
    def name(self) -> str:
        return "Memory Worker"

    @property
    def task_types(self) -> list[TaskType]:
        # Memory operations are cross-cutting; this worker is invoked
        # explicitly by the Orchestrator, not auto-routed by TaskType.
        return []

    @property
    def description(self) -> str:
        return "Persists key findings to MARK's memory vault for future recall."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return (
            f"[Memory] Completed: {task.title}\n"
            f"  Key findings persisted to memory for: {context.goal}"
        )
