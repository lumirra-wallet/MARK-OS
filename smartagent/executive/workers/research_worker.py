"""
ResearchWorker — Phase 11.4: real Ollama-powered research specialist.

Gathers background information, identifies best practices, surfaces
prior art, and produces a structured research summary that downstream
workers (Design, Coding, Review) can build upon.

Phase 11.5: injects prior task outputs and knowledge/memory context so
research always builds on what the team already knows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class ResearchWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for research and information gathering.

    Handles: RESEARCH tasks.

    System prompt: research specialist focused on structured, actionable
    findings with clear sections for background, best practices, key
    technologies, risks, and recommendations.
    """

    _system_prompt = """\
You are a research specialist for MARK, an advanced AI assistant system.

Your role: gather and synthesise relevant information for software and \
technical goals. When given a goal and task, produce a structured research \
report that empowers the team to act.

Output format — always use these sections:
## Background
Brief context and motivation.

## Key Technologies / Approaches
List 3-5 concrete options with one-line descriptions.

## Best Practices
Numbered list of the most important practices for this domain.

## Risks & Considerations
What can go wrong; what to watch for.

## Recommendation
One clear recommendation the team should follow.

Rules:
- Be specific and actionable, not generic.
- Cite concrete patterns, tools, or standards where relevant.
- If prior work from earlier steps is provided, build on it rather than \
repeating it.
- Keep the report focused and under 600 words.\
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
        return self._execute_with_ollama(task, context)
