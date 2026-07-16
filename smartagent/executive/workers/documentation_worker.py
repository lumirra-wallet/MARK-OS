"""
DocumentationWorker — generates technical documentation.

Phase 2: stub.
Phase 4: Ollama with a "technical writer" system prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class DocumentationWorker(BaseWorker):
    """
    Specialist for generating technical documentation.

    Handles: DOCUMENTATION tasks.
    """

    @property
    def name(self) -> str:
        return "Documentation Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.DOCUMENTATION]

    @property
    def description(self) -> str:
        return "Generates README files, API docs, inline comments, and user guides."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)
        source_note = f"  Documented: {prior[-1][:60]}…" if prior else ""
        return (
            f"[Documentation] Completed: {task.title}\n"
            f"{source_note}\n"
            f"  Documentation generated for: {context.goal}"
        ).strip()
