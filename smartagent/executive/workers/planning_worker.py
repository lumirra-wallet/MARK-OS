"""
PlanningWorker — Phase 11.4 / v2.0 Performance Upgrade.

v2.0: system prompt trimmed to ≤150 words.
Creates sub-plans, milestones, and structured decompositions from a goal
and any prior research context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class PlanningWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for planning and architectural decomposition.

    Handles: PLANNING tasks.
    """

    # v2.0: trimmed to ≤150 words
    _system_prompt = """\
Technical planning specialist. Break goals into executable plans.

Sections (use all):
## Overview — one paragraph summary of approach
## Milestones — numbered list with effort (small/medium/large)
## Tasks — 2-4 sub-tasks per milestone as nested list
## Risks — what must be done first; what might block progress
## Done — how the team knows the goal is achieved

Rules:
- Concrete: name files, modules, APIs where relevant.
- Derive the plan from research context if provided.
- Keep milestones independently deliverable.
- Under 350 words total.\
"""

    _preferred_model = "default"

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
        return self._execute_with_ollama(task, context)
