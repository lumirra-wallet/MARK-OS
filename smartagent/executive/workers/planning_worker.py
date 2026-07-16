"""
PlanningWorker — creates sub-plans and architectural outlines.

Phase 2: stub.
Phase 4: Ollama with a "planning specialist" prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class PlanningWorker(BaseWorker):
    """
    Specialist for planning and architectural decomposition.

    Handles: PLANNING tasks.
    """

    @property
    def name(self) -> str:
        return "Planning Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.PLANNING]

    @property
    def description(self) -> str:
        return "Creates sub-plans, milestones, and structured decompositions."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return (
            f"[Planning] Completed: {task.title}\n"
            f"  Plan structured.  Milestones and sub-tasks defined for: {context.goal}"
        )
