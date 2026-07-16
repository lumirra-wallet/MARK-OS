"""
TestingWorker — writes and runs tests.

Phase 2: stub.
Phase 4: Ollama with a "software QA engineer" system prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class TestingWorker(BaseWorker):
    """
    Specialist for testing and quality assurance.

    Handles: TESTING tasks.

    Phase 4 system prompt (preview):
        "You are a software QA engineer.  Given an implementation, write
        comprehensive unit tests using pytest, identify edge cases, and
        report any issues found."
    """

    @property
    def name(self) -> str:
        return "Testing Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.TESTING]

    @property
    def description(self) -> str:
        return "Writes unit tests, validates behaviour, and identifies edge cases."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)
        impl_note = f"  Tested implementation from: {prior[-1][:60]}…" if prior else ""
        return (
            f"[Testing] Completed: {task.title}\n"
            f"{impl_note}\n"
            f"  Tests written and validated for: {context.goal}"
        ).strip()
