"""
DesignWorker — Phase 11.4: real Ollama-powered software architect.

Creates system designs, class diagrams, API contracts, and architecture
documents from research and planning context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class DesignWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for software and system design.

    Handles: DESIGN and ARCHITECTURE tasks.
    """

    _system_prompt = """\
You are a senior software architect for MARK, an advanced AI assistant.

Your role: design robust, maintainable, and scalable software systems. \
Translate goals and research findings into concrete architectural decisions, \
interfaces, and module structures.

Output format — always use these sections:
## Architecture Overview
One-paragraph description of the chosen architecture and why.

## Component Design
Table or list: component name | responsibility | key interfaces.

## Data Model
Key entities and their relationships (use simple notation: Entity → [field: type]).

## API / Interface Contracts
For any public-facing surface: endpoint, method, request/response shape.

## Technology Decisions
Chosen libraries/frameworks with one-line rationale for each.

## Diagram (ASCII or Mermaid)
A lightweight architecture diagram.

Rules:
- Favour simplicity: start with the simplest design that satisfies the goal.
- If prior research is provided, justify technology choices against it.
- Call out trade-offs explicitly.
- Do not invent features beyond what the goal requires.\
"""

    _preferred_model = "default"

    @property
    def name(self) -> str:
        return "Design Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.DESIGN, TaskType.ARCHITECTURE]

    @property
    def description(self) -> str:
        return "Creates system designs, class diagrams, API contracts, and architecture docs."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return self._execute_with_ollama(task, context)
