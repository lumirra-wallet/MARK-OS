"""
ReportWorker — synthesises findings into a structured report.

Phase 2: stub.
Phase 4: Ollama with a "research analyst" system prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class ReportWorker(BaseWorker):
    """
    Specialist for synthesising multi-step findings into a final report.

    Handles: REPORT tasks.
    """

    @property
    def name(self) -> str:
        return "Report Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.REPORT]

    @property
    def description(self) -> str:
        return "Synthesises research and analysis findings into a structured report."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)
        synthesis_note = f"  Synthesised {len(prior)} prior result(s)." if prior else ""
        return (
            f"[Report] Completed: {task.title}\n"
            f"  {synthesis_note}\n"
            f"  Final report generated for: {context.goal}"
        ).strip()
