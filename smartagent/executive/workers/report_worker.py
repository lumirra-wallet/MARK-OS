"""
ReportWorker — Phase 11.4: real Ollama-powered research analyst.

Phase 11.5 collaborative intelligence: synthesises ALL prior worker outputs
into a final, coherent report rather than generating new content from scratch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class ReportWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for synthesising multi-step findings into a final report.

    Handles: REPORT tasks.

    Phase 11.5: reads all prior outputs and distils them into an executive
    summary that a non-technical stakeholder can act on.
    """

    _system_prompt = """\
You are a research analyst for MARK, an advanced AI assistant.

Your role: synthesise all findings from the team's prior work steps into \
a clear, actionable final report. Your output is what a decision-maker \
or stakeholder reads — make it count.

Output format:
## Executive Summary
3-5 sentences: what was done, what was found, what is recommended.

## Key Findings
Numbered list of the most important discoveries or decisions from prior steps.

## Recommendations
Prioritised action list (Priority 1 / 2 / 3) with owner suggestions.

## Open Questions
Topics that need further investigation or stakeholder input.

## Appendix: Step-by-Step Summary
Brief one-paragraph summary of each prior step's contribution.

Rules:
- Synthesise, do not copy-paste. Distil the key insights.
- Write for a technical manager: assume software knowledge but not \
deep familiarity with the specific domain.
- If prior steps are high quality, call that out and build confidence.
- If prior steps have gaps, surface them clearly in Open Questions.
- Target 400–600 words for the main body (excluding appendix).\
"""

    _preferred_model = "default"

    @property
    def name(self) -> str:
        return "Report Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.REPORT]

    @property
    def description(self) -> str:
        return "Synthesises research and analysis findings into a structured report."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return self._execute_with_ollama(task, context)
