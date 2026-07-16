"""
TestingWorker — Phase 11.4 / Milestone 19 / v2.0 Performance Upgrade.

v2.0: system prompt trimmed to test-only output format.
Writes comprehensive tests and validates implementation code against the
design and requirements from prior steps.

Milestone 19: inherits FileEditMixin so fenced code blocks with filename
annotations are automatically written as real files.
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
    Uses the coding model for test code generation.
    """

    _allowed_tools: tuple[str, ...] = (
        "file_read",
        "file_write",
        "directory_list",
        "search_files",
    )

    # v2.0: trimmed to test-only output format
    # Filename goes directly on the fence line (Pattern B) so FileEditMixin
    # can extract it.  Format: ```python test_foo.py  (no "filename:" label)
    _system_prompt = """\
Expert QA engineer. Return ONLY pytest test code.

Rules:
- No explanations. No markdown prose. Only fenced code blocks.
- REQUIRED: put the target filename directly on the fence line, like this:
    ```python test_calculator.py
    <code here>
    ```
- Use exactly this pattern: triple backtick + language + space + filename.ext
- pytest conventions: test_ prefix, fixtures, parametrize.
- Test happy path, edge cases, and error conditions.
- Import and test the implementation directly — do not mock core logic.\
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

    # execute() is intentionally NOT defined here — same reason as CodingWorker.
    #
    # MRO: TestingWorker → FileEditMixin → WorkerToolMixin → …
    #
    # FileEditMixin.execute() wraps WorkerToolMixin.execute() (_execute_with_tools)
    # so that fenced test-code blocks in the LLM response are written to disk.
    # Defining execute() here would bypass FileEditMixin and break file creation.
