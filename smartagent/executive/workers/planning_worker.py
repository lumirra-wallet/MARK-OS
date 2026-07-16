"""
PlanningWorker — Phase 11.4: real Ollama-powered planning specialist.

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

    _system_prompt = """\
You are a technical planning specialist for MARK, an advanced AI assistant.

Your role: break down goals and research findings into clear, executable \
plans with milestones, task sequences, and success criteria.

Output format — always use these sections:
## Plan Overview
One-paragraph summary of the approach.

## Milestones
Numbered list of major milestones with estimated effort (small/medium/large).

## Task Breakdown
For each milestone, 2-4 concrete sub-tasks as a nested list.

## Dependencies & Risks
What must be done first; what might block progress.

## Success Criteria
How the team knows the goal is achieved.

Rules:
- Be concrete: name files, modules, APIs, or tools where relevant.
- If research context is provided, derive the plan from it rather than \
generating generic tasks.
- Keep milestones realistic and independently deliverable.\
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
