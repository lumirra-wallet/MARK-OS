"""
ResearchWorker — gathers information and prior art for a goal.

Phase 2: stub implementation.
Phase 4: calls Ollama with a "research specialist" system prompt,
         using the goal as the user message, and returns a structured
         research report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class ResearchWorker(BaseWorker):
    """
    Specialist for research and information gathering.

    Handles: RESEARCH tasks.

    Phase 4 system prompt (preview):
        "You are a research specialist.  Given a goal, gather relevant
        background information, identify best practices, list key
        technologies or approaches, and produce a structured summary."
    """

    @property
    def name(self) -> str:
        return "Research Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.RESEARCH]

    @property
    def description(self) -> str:
        return "Gathers background information, prior art, and best practices for a goal."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)
        prior_note = f"  Prior context: {prior[0][:60]}…" if prior else ""
        return (
            f"[Research] Completed: {task.title}\n"
            f"  Goal: {task.description}\n"
            f"{prior_note}"
            f"  Findings: Background research gathered.  "
            f"Key considerations identified for: {context.goal}"
        ).strip()
