"""
CodingWorker — writes implementation code.

Phase 2: stub.
Phase 4: Ollama with an "expert Python engineer" system prompt, using
         the coding model (qwen2.5-coder:7b by default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class CodingWorker(BaseWorker):
    """
    Specialist for code implementation.

    Handles: CODING and IMPLEMENTATION tasks.

    Phase 4 system prompt (preview):
        "You are an expert Python engineer.  Given a task description and
        any prior research or design context, write clean, well-documented,
        production-quality code."
    """

    @property
    def name(self) -> str:
        return "Coding Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.CODING, TaskType.IMPLEMENTATION]

    @property
    def description(self) -> str:
        return "Writes clean, production-quality implementation code."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)
        design_note = f"  Based on: {prior[-1][:60]}…" if prior else ""
        return (
            f"[Coding] Completed: {task.title}\n"
            f"{design_note}\n"
            f"  Code implemented for: {context.goal}"
        ).strip()
