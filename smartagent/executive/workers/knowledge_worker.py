"""
KnowledgeWorker — queries MARK's knowledge graph.

Phase 2: stub.
Phase 4: integrates with ``KnowledgeManager`` to surface structured
         concepts relevant to each task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class KnowledgeWorker(BaseWorker):
    """
    Specialist for knowledge retrieval and concept enrichment.

    Handles: ANALYSIS tasks (primary); also used cross-cuttingly in Phase 4.
    """

    @property
    def name(self) -> str:
        return "Knowledge Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.ANALYSIS]

    @property
    def description(self) -> str:
        return "Retrieves relevant knowledge concepts and enriches task context."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return (
            f"[Knowledge] Completed: {task.title}\n"
            f"  Relevant knowledge concepts retrieved for: {context.goal}"
        )
