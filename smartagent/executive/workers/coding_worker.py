"""
CodingWorker — Phase 11.4 / Milestone 19 / v2.0 Performance Upgrade.

v2.0: system prompt trimmed to code-only output format.
Writes clean, production-quality code guided by research and design context.
Uses the coding-optimised model (qwen2.5-coder by default).

Milestone 19: inherits FileEditMixin so any fenced code block in the output
that carries a filename annotation is automatically written as a real file
into the workspace's output/ directory (via the FileEditor injected by the
Orchestrator).
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


class CodingWorker(FileEditMixin, WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
    """
    Specialist for code implementation.

    Handles: CODING and IMPLEMENTATION tasks.
    Uses the coding-optimised model (qwen2.5-coder by default).
    """

    _allowed_tools: tuple[str, ...] = (
        "file_read",
        "file_write",
        "directory_list",
        "directory_create",
        "search_files",
    )

    # v2.0: trimmed to code-only output — no prose, no markdown wrapper
    # Filename goes directly on the fence line (Pattern B) so FileEditMixin
    # can extract it.  Format: ```python calculator.py  (no "filename:" label)
    _system_prompt = """\
Expert software engineer. Return ONLY runnable code.

Rules:
- No explanations. No markdown prose. Only fenced code blocks.
- REQUIRED: put the target filename directly on the fence line, like this:
    ```python calculator.py
    <code here>
    ```
- Use exactly this pattern: triple backtick + language + space + filename.ext
- Idiomatic Python, PEP 8, type hints, docstrings.
- Handle errors explicitly. No TODO comments — implement it.
- Follow any prior design or research context exactly.\
"""

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

    # execute() is intentionally NOT defined here.
    #
    # The MRO is:  CodingWorker → FileEditMixin → WorkerToolMixin → …
    #
    # When the Scheduler calls worker.execute(task, context):
    #   1. FileEditMixin.execute() runs first (leftmost mixin).
    #   2. It calls super().execute() → WorkerToolMixin.execute() → _execute_with_tools()
    #   3. The LLM response (containing fenced code blocks) is returned to step 1.
    #   4. FileEditMixin._write_output_files() parses the blocks and writes them to disk.
    #
    # Defining execute() here would short-circuit step 1, skipping file creation.
