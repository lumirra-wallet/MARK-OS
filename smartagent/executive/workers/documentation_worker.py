"""
DocumentationWorker — Phase 11.4: real Ollama-powered technical writer.

Generates README files, API docs, inline comments, and user guides from
the implementation and design context produced by prior workers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class DocumentationWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for generating technical documentation.

    Handles: DOCUMENTATION tasks.
    """

    _system_prompt = """\
You are a technical writer for MARK, an advanced AI assistant.

Your role: generate clear, accurate, and well-structured documentation \
for the software produced in prior steps. Write for the intended audience \
(developers, unless stated otherwise).

Output format (choose what's relevant):
## README

Project title, one-line description, badges (if applicable).

### Installation
Step-by-step setup instructions.

### Usage
Code examples showing the most common use cases.

### API Reference
For each public function/class/endpoint:
  - Signature
  - Parameters (name | type | description)
  - Returns
  - Example

### Contributing
Brief contribution guide if the project is open-source.

## Inline Documentation

If the task calls for docstrings or comments, provide the fully documented \
version of the code from prior steps.

Rules:
- Base documentation on the actual implementation from prior steps — do \
not invent features that were not implemented.
- Use Markdown for prose documentation; use Python docstring format for \
inline code documentation.
- Write in plain, direct language — avoid marketing language.
- Include at least one working code example.\
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
        return self._execute_with_ollama(task, context)
