"""
ResearchWorker — Phase 11.4 / v2.0 Performance Upgrade.

v2.0: system prompt trimmed to ≤150 words.
Gathers background information, identifies best practices, and produces a
structured research summary for downstream workers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin
from smartagent.executive.workers.tool_mixin import WorkerToolMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class ResearchWorker(WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
    """
    Specialist for research and information gathering.

    Handles: RESEARCH tasks.
    """

    _allowed_tools: tuple[str, ...] = ("date_time", "system_info", "read_markdown")

    # v2.0: trimmed to ≤150 words
    _system_prompt = """\
Research specialist. Produce a concise, actionable technical report.

Sections (use all):
## Background — brief context (2-3 sentences)
## Key Approaches — 3-5 options with one-line descriptions
## Best Practices — top 5 as numbered list
## Risks — top 3 risks to watch for
## Recommendation — one clear recommendation

Rules:
- Specific and actionable, not generic.
- Under 400 words total.
- Build on prior context if provided — do not repeat it.
- Cite concrete patterns, tools, or standards.\
"""

    _preferred_model = "default"

    @property
    def name(self) -> str:
        return "Research Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.RESEARCH]

    @property
    def description(self) -> str:
        return "Gathers background information, prior art, and best practices for a goal."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return self._execute_with_tools(task, context)
