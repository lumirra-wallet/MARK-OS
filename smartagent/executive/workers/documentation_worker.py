"""
DocumentationWorker — Phase 11.4 / v2.0 Performance Upgrade.

v2.0: system prompt trimmed to ≤250 words.
Generates README files, API docs, inline comments, and user guides from
the implementation and design context produced by prior workers.
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


class DocumentationWorker(WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
    """
    Specialist for generating technical documentation.

    Handles: DOCUMENTATION tasks.
    """

    _allowed_tools: tuple[str, ...] = (
        "file_read",
        "directory_list",
        "read_markdown",
        "search_files",
    )

    # v2.0: trimmed to ≤250 words
    _system_prompt = """\
Technical writer for a developer audience.

Generate clear, accurate documentation for the software from prior steps.

Sections (use what's relevant):
## README — title, one-line description, badges
### Installation — step-by-step setup
### Usage — most common use cases with code examples
### API Reference — for each public function/class/endpoint:
  signature, parameters (name|type|description), returns, example
### Contributing — brief guide if open-source

## Inline Documentation — if the task requires docstrings or comments,
provide the fully documented version of the code.

Rules:
- Base docs on the actual implementation — do not invent features.
- Markdown for prose; Python docstring format for inline docs.
- Plain, direct language — no marketing copy.
- Include at least one working code example.
- Under 600 words total.\
"""

    _preferred_model = "default"

    @property
    def name(self) -> str:
        return "Documentation Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.DOCUMENTATION]

    @property
    def description(self) -> str:
        return "Generates README files, API docs, inline comments, and user guides."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return self._execute_with_tools(task, context)
