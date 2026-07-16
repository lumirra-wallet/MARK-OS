"""
ReviewWorker — Phase 11.4 / v2.0 Performance Upgrade.

v2.0: system prompt trimmed to ≤200 words.
Critically reviews prior outputs and provides a quality gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class ReviewWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for code review and final quality gates.

    Handles: REVIEW tasks.
    """

    # v2.0: trimmed to ≤200 words
    _system_prompt = """\
Senior software architect conducting a formal code review.

Critically evaluate the work from prior steps — do NOT summarise it.
Find real problems and propose specific fixes.

Sections (use all):
## Summary — one-paragraph overall verdict (pass / conditional / fail)
## Strengths — what was done well (bullets, specific)
## Issues — numbered list; for each: Severity (Critical/Major/Minor),
  Location, Problem, Fix
## Architecture — higher-level design concerns
## Verdict — [ ] Approved / [ ] Approved with changes / [ ] Needs revision

Rules:
- Reference actual code, class names, or decisions from prior steps.
- Do not soften criticism — catch real bugs before production.
- If prior steps are incomplete, flag as Critical.
- Under 450 words total.\
"""

    _preferred_model = "default"

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
        return self._execute_with_ollama(task, context)
