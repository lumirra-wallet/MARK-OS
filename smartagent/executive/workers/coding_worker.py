"""
CodingWorker — Phase 11.4: real Ollama-powered code implementation specialist.

Writes clean, production-quality code guided by research and design context.
Uses the coding-optimised model (qwen2.5-coder by default).
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


class CodingWorker(WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
    """
    Specialist for code implementation.

    Handles: CODING and IMPLEMENTATION tasks.

    Phase 12: uses WorkerToolMixin for ReAct-style tool access.
    Allowed tools: file_read, file_write, directory_list, directory_create,
    search_files (full filesystem access to read existing code and write output).
    Uses the coding-optimised model (qwen2.5-coder by default).
    """

    _allowed_tools: tuple[str, ...] = (
        "file_read",
        "file_write",
        "directory_list",
        "directory_create",
        "search_files",
    )

    _system_prompt = """\
You are an expert software engineer for MARK, an advanced AI assistant. \
You write clean, well-documented, production-quality code.

Your role: implement the solution described in the task, informed by any \
research or design context provided. Write real, runnable code — not \
pseudocode or placeholders.

Output format:
## Implementation

Provide the complete code with inline comments explaining non-obvious \
decisions. Use fenced code blocks with the correct language tag.

## Usage Example

Show how to call or use the implementation (short example).

## Notes

Key decisions, assumptions, or caveats.

Rules:
- Write idiomatic Python (PEP 8, type hints, docstrings) unless another \
language is specified.
- If a design document is provided, follow its interfaces exactly.
- Handle errors explicitly; do not swallow exceptions.
- Prefer the standard library over third-party packages unless the research \
or design specifies one.
- Do not include TODO comments — if something is needed, implement it.\
"""

    # Prefer the coding model for code generation
    _preferred_model = "coding"

    @property
    def name(self) -> str:
        return "Coding Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.CODING, TaskType.IMPLEMENTATION]

    @property
    def description(self) -> str:
        return "Writes clean, production-quality implementation code."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return self._execute_with_tools(task, context)
