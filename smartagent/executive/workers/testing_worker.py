"""
TestingWorker — Phase 11.4 / Milestone 19.

Writes comprehensive tests and validates implementation code against the
design and requirements from prior steps.

Milestone 19: inherits FileEditMixin so any fenced code block in the output
that carries a filename annotation is automatically written as a real file
into the workspace's output/ directory.  Test files are written to disk, not
just returned as text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.file_edit_mixin import FileEditMixin
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin
from smartagent.executive.workers.tool_mixin import WorkerToolMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class TestingWorker(FileEditMixin, WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
    """
    Specialist for testing and quality assurance.

    Handles: TESTING tasks.

    Phase 12: uses WorkerToolMixin for ReAct-style tool access.
    Allowed tools: file_read (read implementation code), file_write (save tests),
    directory_list, search_files (find related files).
    Uses the coding model for test code generation.
    """

    _allowed_tools: tuple[str, ...] = (
        "file_read",
        "file_write",
        "directory_list",
        "search_files",
    )

    _system_prompt = """\
You are a senior QA engineer for MARK, an advanced AI assistant.

Your role: write comprehensive, well-structured tests for the implementation \
provided in prior steps. Identify edge cases, boundary conditions, and \
failure modes.

Output format:
## Test Suite

Provide the complete pytest test file with:
- Unit tests for each function/class
- Edge case tests (empty input, boundary values, error conditions)
- At least one integration test if applicable

Use fenced code blocks with ``python`` language tag.

## Coverage Summary

List the key scenarios tested and any intentionally excluded edge cases \
(with justification).

## Known Gaps

Scenarios that are hard to test in isolation and would require mocking or \
integration setup not provided here.

Rules:
- Use pytest conventions: ``test_`` prefix, fixtures, parametrize for \
multiple cases.
- Each test should have a clear docstring explaining what it verifies.
- If implementation code is provided in prior steps, import and test it \
directly.
- Do not mock core business logic — test it directly where possible.\
"""

    _preferred_model = "coding"

    @property
    def name(self) -> str:
        return "Testing Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.TESTING]

    @property
    def description(self) -> str:
        return "Writes unit tests, validates behaviour, and identifies edge cases."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return self._execute_with_tools(task, context)
