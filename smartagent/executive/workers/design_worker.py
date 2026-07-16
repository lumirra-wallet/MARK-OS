"""
DesignWorker — creates system designs, class diagrams, and interfaces.

Phase 2: stub.
Phase 4: Ollama with a "software architect" system prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class DesignWorker(BaseWorker):
    """
    Specialist for software and system design.

    Handles: DESIGN and ARCHITECTURE tasks.
    """

    @property
    def name(self) -> str:
        return "Design Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.DESIGN, TaskType.ARCHITECTURE]

    @property
    def description(self) -> str:
        return "Creates system designs, class diagrams, API contracts, and architecture docs."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)
        research_note = f"  Built on research: {prior[-1][:60]}…" if prior else ""
        return (
            f"[Design] Completed: {task.title}\n"
            f"{research_note}\n"
            f"  Architecture and interfaces designed for: {context.goal}"
        ).strip()
