"""
FileEditMixin — Milestone 19: auto-extract and write code blocks from worker output.

When mixed into a worker class, overrides ``execute()`` to:

  1. Call the parent ``execute()`` (from WorkerToolMixin / OllamaWorkerMixin).
  2. Parse the result text for fenced code blocks annotated with filenames.
  3. Write each block via the workspace ``FileEditor`` (or fallback to
     ``write_output_file`` when no FileEditor is injected).
  4. Append a ``"Files written: …"`` footer to the result string.

Filename annotation formats supported:

  **Pattern A** — first-line comment::

      ```python
      # filename: auth.py
      <code>
      ```

  **Pattern B** — fence label::

      ```python auth.py
      <code>
      ```

  **Pattern C** — MARK file marker::

      ```python
      # ---FILE: routes/api.py---
      <code>
      ```

MRO insertion point (before WorkerToolMixin)::

    class CodingWorker(FileEditMixin, WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
        ...
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for extracting named code blocks
# ---------------------------------------------------------------------------

# ```lang optional_filename.ext\n<content>```
# Captures: lang (optional), fence_name (optional), content
_FENCE_RE = re.compile(
    r"```(?P<lang>[a-zA-Z0-9_+\-]*)[ \t]*(?P<fence_name>[^\s`\n]+\.[a-zA-Z0-9]+)?[ \t]*\n"
    r"(?P<content>.*?)"
    r"```",
    re.DOTALL,
)

# Matches first-line filename comments inside a code block.
# Order matters: more specific patterns (filename: file:) must come before
# the short FILE pattern so the alternation doesn't consume "file" in "filename".
_FIRSTLINE_NAME_RE = re.compile(
    r"^#[ \t]*(?:-{0,3}filename:|-{0,3}file:|-{0,3}FILE[-:]?)[ \t]*"
    r"(?P<name>[^\s\-#`]+)",
    re.IGNORECASE,
)


class FileEditMixin:
    """
    Mixin that auto-extracts fenced code blocks with filenames and writes
    them to the active workspace.

    Must be the **leftmost** class in the worker MRO so its ``execute()``
    wraps all downstream implementations::

        class CodingWorker(FileEditMixin, WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
            ...

    When no ``FileEditor`` or ``Workspace`` is present in
    ``context.metadata``, the mixin is a transparent pass-through —
    all existing tests continue to pass without modification.
    """

    # ------------------------------------------------------------------
    # execute() override — wraps the full downstream chain
    # ------------------------------------------------------------------

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        """
        Run the parent execute() then write any fenced code blocks as files.
        """
        result: str = super().execute(task, context)  # type: ignore[misc]
        written = self._write_output_files(result, context)
        if written:
            names = ", ".join(written)
            result = result + f"\n\n[Files written: {names}]"
        return result

    # ------------------------------------------------------------------
    # Code block extraction
    # ------------------------------------------------------------------

    def _extract_file_blocks(self, text: str) -> list[tuple[str, str]]:
        """
        Parse *text* for fenced code blocks annotated with filenames.

        Returns a list of ``(filename, content)`` tuples.  Blocks without
        a determinable filename are silently skipped.
        """
        blocks: list[tuple[str, str]] = []

        for m in _FENCE_RE.finditer(text):
            raw_content = m.group("content") or ""
            fence_name  = (m.group("fence_name") or "").strip()

            filename = ""
            content  = raw_content

            if fence_name:
                # Pattern B — filename on the fence line
                filename = fence_name
            else:
                # Patterns A and C — filename in a first-line comment
                first_line, _, rest = raw_content.partition("\n")
                fm = _FIRSTLINE_NAME_RE.match(first_line.strip())
                if fm:
                    raw_name = fm.group("name").strip("-").strip()
                    # Validate: must look like a file path with an extension
                    if "." in raw_name and not raw_name.startswith("."):
                        filename = raw_name
                        content  = rest  # drop the comment line

            if not filename:
                continue

            # Normalise: strip leading ./ or /
            filename = filename.lstrip("/").lstrip("./")
            if not filename:
                continue

            blocks.append((filename, content.rstrip("\n")))

        return blocks

    # ------------------------------------------------------------------
    # File writing
    # ------------------------------------------------------------------

    def _write_output_files(
        self,
        text: str,
        context: "ExecutionContext",
    ) -> list[str]:
        """
        Extract code blocks from *text* and write each one as a file.

        Priority:
          1. ``context.metadata["file_editor"]`` — :class:`FileEditor` instance
          2. ``context.metadata["workspace"]``   — write via ``write_output_file``
          3. Neither available                   — no-op (returns empty list)

        Returns a list of filenames that were successfully written.
        """
        blocks = self._extract_file_blocks(text)
        if not blocks:
            return []

        file_editor = context.metadata.get("file_editor")
        workspace   = context.metadata.get("workspace")

        written: list[str] = []

        if file_editor is not None:
            for filename, content in blocks:
                try:
                    result = file_editor.create(filename, content)
                    if result.success:
                        written.append(filename)
                        logger.info("FileEditMixin: %s", result)
                    else:
                        logger.warning("FileEditMixin: %s", result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "FileEditMixin: error writing %r via FileEditor: %s",
                        filename, exc,
                    )

        elif workspace is not None:
            from smartagent.workspace.file_output import write_output_file
            for filename, content in blocks:
                try:
                    write_output_file(workspace, filename, content)
                    written.append(filename)
                    logger.info("FileEditMixin: wrote %r (fallback path)", filename)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "FileEditMixin: error writing %r via fallback: %s",
                        filename, exc,
                    )

        else:
            logger.debug(
                "FileEditMixin: no file_editor or workspace in context; skipping file writes"
            )

        return written
