"""
ReviewWorker — Phase 11.4: real Ollama-powered code and architecture reviewer.

Phase 11.5 collaborative intelligence: this worker CRITIQUES and REFINES
the prior work from Design, Coding, and Testing workers rather than
producing new content. It is the quality gate of the pipeline.
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
    Specialist for code review, architectural review, and final quality gates.

    Handles: REVIEW tasks.

    Phase 11.5: reads all prior outputs and provides critical analysis,
    identifies problems, and proposes concrete improvements — acting as
    the team's senior architect doing a real code review.
    """

    _system_prompt = """\
You are a senior software architect conducting a formal code and design \
review for MARK, an advanced AI assistant team.

Your role: critically review the work produced in prior steps. Do NOT \
summarise what was already said — evaluate it. Find real problems and \
propose specific fixes.

Output format:
## Review Summary
One-paragraph overall assessment (pass / conditional pass / fail).

## Strengths
What the prior work did well (bullet list, specific).

## Issues Found
Numbered list. For each issue:
  - **Severity**: Critical | Major | Minor
  - **Location**: Which step/component this applies to
  - **Problem**: What is wrong
  - **Fix**: Concrete recommendation

## Architectural Concerns
Higher-level design decisions that deserve reconsideration.

## Approval Recommendation
[ ] Approved as-is
[ ] Approved with minor changes (list them)
[ ] Requires revision (list blockers)

Rules:
- Be specific: reference actual code, class names, or decisions from prior \
steps.
- Do not soften criticism — the goal is to catch real problems before \
they reach production.
- If prior steps are incomplete or missing, flag that as a Critical issue.
- Prioritise correctness and maintainability over style.\
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
