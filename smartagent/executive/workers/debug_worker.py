"""
DebugWorker — Milestone 20: Self Debugging.

A specialist worker that reads a Python traceback and the offending file,
then produces a fixed version of that file.

Two interfaces
--------------
1. **BaseWorker interface** — ``execute(task, context)`` for use inside the
   Orchestrator with a ``DEBUGGING`` task type.

2. **DebugLoop interface** — ``fix(traceback, filepath, file_content)`` called
   directly by :class:`~smartagent.debug.debug_loop.DebugLoop` so it can be
   used without an Orchestrator or task plan.

Phase behaviour
---------------
* **Phase 2 (stub)**: ``fix()`` returns the original file content unchanged.
  The DebugLoop detects "no change" and stops.  ``execute()`` returns a
  descriptive stub.  All tests pass without Ollama.

* **Phase 4 (Ollama)**: when a model is available in ``context.metadata``
  (injected by the Orchestrator), ``execute()`` uses
  :class:`~smartagent.executive.workers.ollama_mixin.OllamaWorkerMixin`
  to actually fix code.  ``fix()`` also gains AI capability when
  ``_model_manager`` is set via :meth:`with_model`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.debug.traceback_parser import ParsedTraceback
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class DebugWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for autonomous debugging tasks.

    Handles: ``DEBUGGING`` task type.

    The worker is designed to be useful in two modes:

    * **Orchestrator mode** — wired into the WorkerRegistry for ``DEBUGGING``
      tasks, receiving full ``ExecutionContext`` with AI services.

    * **Direct mode** — instantiated by :class:`DebugLoop` and called via
      :meth:`fix()` for each failing file.

    Args:
        model_manager: Optional ModelManager for AI-powered fixes.
                       Set this when using the worker outside an Orchestrator.
    """

    _system_prompt = """\
You are a senior Python debugging specialist for MARK, an advanced AI assistant.

Your role: receive a failing test traceback and the content of the offending \
file, then output the COMPLETE corrected file — every line, no omissions.

Rules:
- Output ONLY the corrected file content, no explanation before or after.
- Preserve all imports, class definitions, and unrelated functions exactly.
- Fix the root cause, not just the symptom.
- If the traceback indicates a missing import, add it at the top.
- If the traceback shows a wrong return type, fix the return statement.
- If the traceback shows an AttributeError, fix the attribute access or add it.
- Do NOT add TODO comments — implement the fix.
- Do NOT use fenced code blocks — output the raw file content directly.\
"""

    _preferred_model = "coding"

    def __init__(self, model_manager: Any | None = None) -> None:
        self._model_manager = model_manager

    @property
    def name(self) -> str:
        return "Debug Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.DEBUGGING]

    @property
    def description(self) -> str:
        return "Reads tracebacks and produces fixed file content autonomously."

    @property
    def phase(self) -> str:
        return "ollama" if self._model_manager else "stub"

    # ------------------------------------------------------------------
    # BaseWorker interface — used by the Orchestrator
    # ------------------------------------------------------------------

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        """
        Execute a DEBUGGING task from within the Orchestrator.

        Expects ``task.description`` to contain:
          - The failing test command
          - The traceback text
          - Optionally the file content

        Returns a summary of what was fixed.
        """
        # Phase 4: use Ollama if available
        mm = context.metadata.get("model_manager")
        if mm is not None:
            return self._execute_with_ollama(task, context)

        # Phase 2: stub result
        return (
            f"[Debug stub] Analysed: {task.title}\n"
            "  • Traceback parsed successfully.\n"
            "  • AI-powered fix requires an active model (Phase 4).\n"
            "  • Run 'model use <name>' to enable autonomous fixing."
        )

    # ------------------------------------------------------------------
    # Direct interface — called by DebugLoop
    # ------------------------------------------------------------------

    def fix(
        self,
        traceback: "ParsedTraceback",
        filepath: str,
        file_content: str,
    ) -> str:
        """
        Given a parsed traceback and the content of the failing file,
        return the corrected file content.

        Phase 2: returns *file_content* unchanged (signals "no fix").
        Phase 4: calls the LLM to produce a real fix.

        Args:
            traceback:    Structured traceback from :class:`TracebackParser`.
            filepath:     Absolute path to the file that needs fixing.
            file_content: Current content of that file.

        Returns:
            Corrected file content string, or the original content if the
            worker cannot produce a fix.
        """
        mm = self._model_manager
        if mm is None:
            # Phase 2 stub — signal "no change" to DebugLoop
            return file_content

        # Phase 4 — call Ollama directly (no ExecutionContext)
        return self._fix_with_model(mm, traceback, filepath, file_content)

    # ------------------------------------------------------------------
    # AI fix (Phase 4)
    # ------------------------------------------------------------------

    def _fix_with_model(
        self,
        model_manager: Any,
        traceback: "ParsedTraceback",
        filepath: str,
        file_content: str,
    ) -> str:
        """
        Call the LLM to produce a fixed version of *file_content*.

        Best-effort: if the model is unavailable or returns empty output,
        falls back to *file_content* unchanged.
        """
        prompt = self._build_fix_prompt(traceback, filepath, file_content)

        try:
            # Use streaming for longer files; fall back to generate if needed
            response = ""
            if hasattr(model_manager, "chat_stream"):
                for chunk in model_manager.chat_stream(
                    messages=[
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user",   "content": prompt},
                    ]
                ):
                    response += chunk
            elif hasattr(model_manager, "generate"):
                response = model_manager.generate(
                    prompt=prompt,
                    system=self._system_prompt,
                )
            else:
                return file_content

            fixed = response.strip()
            # Strip accidental fenced code block wrapping
            if fixed.startswith("```"):
                lines = fixed.splitlines()
                fixed = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            return fixed if fixed else file_content

        except Exception:  # noqa: BLE001
            return file_content

    @staticmethod
    def _build_fix_prompt(
        traceback: "ParsedTraceback",
        filepath: str,
        file_content: str,
    ) -> str:
        """Build the user prompt for the LLM fix request."""
        rcf = traceback.root_cause_frame
        frame_info = ""
        if rcf:
            frame_info = (
                f"Root cause: {rcf.filepath}:{rcf.lineno} in {rcf.function}\n"
                f"  Code: {rcf.code}"
            )

        # Truncate very large files so we stay within context limits
        content_preview = file_content
        if len(file_content) > 8000:
            content_preview = file_content[:8000] + "\n\n# … [file truncated for context]"

        return (
            f"File to fix: {filepath}\n\n"
            f"Error:\n"
            f"  {traceback.error_type}: {traceback.error_message}\n"
            f"{frame_info}\n\n"
            f"Current file content:\n"
            f"{content_preview}\n\n"
            "Output the complete corrected file content:"
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_model(cls, model_manager: Any) -> "DebugWorker":
        """Create a DebugWorker pre-wired with a ModelManager."""
        return cls(model_manager=model_manager)
