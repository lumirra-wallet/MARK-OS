"""
ReviewWorker — code review, quality gates, and final sign-off.

Phase 2: stub.
Phase 4: Ollama with a "senior software architect" system prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class ReviewWorker(BaseWorker):
    """
    Specialist for code review, architectural review, and final quality gates.

    Handles: REVIEW tasks.
    """

    @property
    def name(self) -> str:
        return "Review Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.REVIEW]

    @property
    def description(self) -> str:
        return "Performs code review, quality gates, and final sign-off."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)
        review_basis = f"  Reviewed: {prior[-1][:60]}…" if prior else ""
        return (
            f"[Review] Completed: {task.title}\n"
            f"{review_basis}\n"
            f"  Review complete.  Approved for: {context.goal}"
        ).strip()
