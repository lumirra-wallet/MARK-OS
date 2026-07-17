"""
FastPathBuilder — single-shot code generation for TRIVIAL/SMALL tasks.

Execution tier 1 (the "fast path"):
    Intent Detection → Generate Files (1 LLM call) → Write Files → Optional Test → Return

No research, no architecture, no documentation, no planning workers, no DevLoop.
Typical completion: under 10 seconds for tasks like:
    - create hello.py
    - create README
    - fix one typo
    - add one function
    - rename a file
    - update one test
    - create index.html
    - add a CSS file

The LLM must return ONLY fenced code blocks with the filename on the fence line:

    ```python hello.py
    print("Hello World")
    ```

Files are written directly by FileEditor — no additional AI calls.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Fence parser — same Pattern B used by FileEditMixin
# ---------------------------------------------------------------------------

_FENCE_RE: re.Pattern = re.compile(
    r"```(?P<lang>\w+)?\s+(?P<filename>[\w/.\-]+\.\w+)\n(?P<code>.*?)```",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert code generator. Produce ONLY fenced code blocks.
Put the filename directly on the opening fence line. Example:

```python hello.py
print("Hello World")
```

Rules:
- Output ONLY code blocks, no prose, no explanations.
- One block per file.
- Use the appropriate language tag (python, html, css, js, markdown, text, …).
- Make the code complete and working — do not use placeholders.
"""

# ---------------------------------------------------------------------------
# Result dataclass (duck-types LoopResult for SoftwareEngineerReport)
# ---------------------------------------------------------------------------

@dataclass
class FastPathResult:
    """
    Result from :class:`FastPathBuilder.build`.

    Designed to be a drop-in substitute for ``LoopResult`` when assembling a
    :class:`~smartagent.engineer.software_engineer.SoftwareEngineerReport`.
    """

    goal:           str
    success:        bool               = False
    files_created:  list               = field(default_factory=list)
    files_modified: list               = field(default_factory=list)
    project_dir:    str                = ""
    total_elapsed:  float              = 0.0
    stop_reason:    str                = "fast_path_done"
    final_summary:  str                = ""
    # For LoopResult duck-typing
    iterations:     list               = field(default_factory=list)

    def as_display_lines(self) -> list[str]:
        status = "✓" if self.success else "~"
        lines: list[str] = [
            f"{status} Fast Path  (single LLM call — no pipeline)",
            f"  Files   : {len(self.files_created)} created",
        ]
        for f in self.files_created:
            lines.append(f"    + {f}")
        if self.project_dir:
            lines.append(f"    (in {self.project_dir})")
        if self.total_elapsed:
            lines.append(f"  Elapsed : {self.total_elapsed:.1f}s")
        return lines


# ---------------------------------------------------------------------------
# FastPathBuilder
# ---------------------------------------------------------------------------

class FastPathBuilder:
    """
    Single-shot file generator for TRIVIAL/SMALL tasks.

    Bypasses: DevLoop, Planner, Scheduler, Orchestrator, and all specialist
    workers.  Makes exactly ONE LLM call via ``model_manager.chat_stream()``,
    parses the fenced code blocks in the response, and writes each block to
    disk via ``FileEditor``.

    Args:
        model_manager: Any object with a ``chat_stream(messages, **kwargs)``
                       method that returns an iterable of string chunks.
                       When ``None``, the builder returns an empty result.
        project_dir:   Absolute path where generated files are written.
                       Defaults to the current working directory.
    """

    def __init__(
        self,
        model_manager: Any | None = None,
        project_dir: str = ".",
    ) -> None:
        self._mm = model_manager
        self._project_dir = os.path.abspath(project_dir)

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def build(
        self,
        goal: str,
        test_cmd: str = "pytest",
        run_tests: bool = False,
    ) -> FastPathResult:
        """
        Generate files for *goal* in a single LLM call.

        Args:
            goal:      Natural-language task description.
            test_cmd:  Shell command to run after generating files.
                       Pass ``run_tests=True`` to actually execute it.
            run_tests: When True, run *test_cmd* (or a scoped pytest call)
                       after writing files.

        Returns:
            :class:`FastPathResult`
        """
        t0 = time.monotonic()
        result = FastPathResult(goal=goal, project_dir=self._project_dir)

        logger.info("[fast] Generating: %s", goal[:70])

        # ── Step 1: one LLM call ──────────────────────────────────────
        response = self._call_llm(goal)
        logger.debug("[fast] LLM response length=%d chars", len(response))

        # ── Step 2: parse + write files ──────────────────────────────
        created = self._write_files(response)
        result.files_created = created

        # ── Step 3: optional test run ────────────────────────────────
        if run_tests and created:
            result.success = self._run_tests(test_cmd, created)
        else:
            # No tests requested — success as long as the LLM responded.
            # A non-empty response means the model handled the goal; absence
            # of file fences just means the task had no file output (e.g. a
            # conversational goal or a pure-text request).
            result.success = bool(response)

        logger.info(
            "[fast] Done.  %d file(s) written in %.1fs  success=%s",
            len(created), time.monotonic() - t0, result.success,
        )

        result.total_elapsed = time.monotonic() - t0
        result.stop_reason   = "fast_path_done"
        result.final_summary = (
            f"Fast path: generated {len(created)} file(s) in "
            f"{result.total_elapsed:.1f}s"
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm(self, goal: str) -> str:
        """Make one chat_stream call and return the full response text."""
        if self._mm is None:
            logger.warning("FastPathBuilder: no model_manager — returning empty response")
            return ""

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": goal},
        ]

        chunks: list[str] = []
        try:
            for chunk in self._mm.chat_stream(messages):
                if chunk:
                    chunks.append(chunk)
        except Exception as exc:
            logger.warning("FastPathBuilder: LLM call failed: %s", exc)

        return "".join(chunks)

    def _write_files(self, response: str) -> list[str]:
        """
        Parse fenced code blocks from *response* and write each to disk.

        Returns the list of filenames successfully written.
        """
        try:
            from smartagent.workspace.file_editor import FileEditor
        except Exception as exc:
            logger.warning("FastPathBuilder: could not import FileEditor: %s", exc)
            return []

        editor  = FileEditor(self._project_dir)
        created: list[str] = []

        for m in _FENCE_RE.finditer(response):
            filename = m.group("filename")
            code     = m.group("code")

            logger.debug("[fast] Writing %s ...", filename)
            try:
                edit_result = editor.create(filename, code)
                if edit_result.success:
                    created.append(filename)
                    logger.debug("FastPathBuilder: wrote %s", filename)
                else:
                    logger.warning(
                        "FastPathBuilder: FileEditor.create(%s) failed", filename
                    )
            except Exception as exc:
                logger.warning("FastPathBuilder: write error for %s: %s", filename, exc)

        return created

    def _run_tests(self, test_cmd: str, files_created: list[str]) -> bool:
        """
        Run tests and return True if they pass.

        If *test_cmd* is the default "pytest", scopes the call to any
        test files that were just created.  Otherwise runs *test_cmd* verbatim.
        """
        if test_cmd == "pytest":
            # Scope to generated test files so we don't hit SmartAgent's suite
            test_files = [
                f for f in files_created
                if os.path.basename(f).startswith("test_")
                or f.endswith("_test.py")
            ]
            if not test_files:
                return True  # Nothing to test — treat as success
            cmd = "pytest " + " ".join(test_files)
        else:
            cmd = test_cmd

        logger.info("[fast] Running tests: %s", cmd)
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=self._project_dir,
            )
            return proc.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("FastPathBuilder: tests timed out")
            return False
        except Exception as exc:
            logger.warning("FastPathBuilder: test run failed: %s", exc)
            return False
