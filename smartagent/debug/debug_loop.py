"""
DebugLoop — Milestone 20: Self Debugging.

Run a shell command, read the failure traceback, call a :class:`DebugWorker`
to produce a fix, apply it, and loop until the tests pass or the attempt
budget is exhausted — exactly like an experienced developer.

Usage::

    from smartagent.debug.debug_loop import DebugLoop

    loop   = DebugLoop(max_attempts=5)
    result = loop.run("pytest tests/test_auth.py")
    print("\\n".join(result.as_display_lines()))

Wiring in a worker::

    worker = DebugWorker()
    loop   = DebugLoop(max_attempts=5, debug_worker=worker)
    result = loop.run("pytest tests/")

The loop calls ``debug_worker.fix(traceback, filepath, file_content)``
for each unique failing file, writes the returned fixed content, then
re-runs the command.  If ``debug_worker`` is ``None`` the loop still runs
(useful for pure test-running without AI fix capability).
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from smartagent.debug.traceback_parser import ParsedTraceback, TracebackParser
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DebugAttempt:
    """
    Record of one run-then-fix cycle.

    Attributes:
        attempt_num:  1-based cycle number.
        command:      The shell command that was run.
        exit_code:    Subprocess exit code (0 = pass).
        output:       Combined stdout + stderr from the run.
        elapsed:      Seconds the subprocess took.
        tracebacks:   All tracebacks found in *output*.
        fix_applied:  Whether the worker applied at least one fix.
        files_fixed:  Paths of files the worker patched.
        fix_summary:  Short description of what was fixed.
    """

    attempt_num: int
    command: str
    exit_code: int
    output: str
    elapsed: float
    tracebacks: list[ParsedTraceback] = field(default_factory=list)
    fix_applied: bool = False
    files_fixed: list[str] = field(default_factory=list)
    fix_summary: str = ""

    @property
    def passed(self) -> bool:
        """True when the command exited with code 0."""
        return self.exit_code == 0


@dataclass
class DebugResult:
    """
    Aggregate result of the full debug loop.

    Attributes:
        success:       True if the final attempt passed.
        attempts:      All run+fix cycles performed.
        final_output:  stdout+stderr from the last run.
        total_elapsed: Total wall-clock time in seconds.
    """

    success: bool
    attempts: list[DebugAttempt] = field(default_factory=list)
    final_output: str = ""
    total_elapsed: float = 0.0

    def as_display_lines(self) -> list[str]:
        """Format the result as a human-readable console report."""
        icon  = "✓" if self.success else "✗"
        label = "PASSED" if self.success else "FAILED"
        lines: list[str] = [
            f"{icon} Debug loop: {label}",
            f"  Attempts   : {len(self.attempts)}",
            f"  Total time : {self.total_elapsed:.1f}s",
            "",
        ]

        for a in self.attempts:
            status = "PASS" if a.passed else "FAIL"
            lines.append(
                f"  Attempt {a.attempt_num} [{status}]  ({a.elapsed:.1f}s)"
            )
            for tb in a.tracebacks[:3]:
                lines.append(f"    ✗ {tb.one_line()}")
            if len(a.tracebacks) > 3:
                lines.append(f"    … and {len(a.tracebacks) - 3} more")
            if a.fix_applied:
                fixed = ", ".join(a.files_fixed[:5])
                lines.append(f"    ↳ Fixed: {fixed}")

        if not self.success and self.final_output:
            lines += ["", "  Last output (tail):"]
            tail = self.final_output.splitlines()[-25:]
            for line in tail:
                lines.append(f"    {line}")

        return lines


# ---------------------------------------------------------------------------
# DebugLoop
# ---------------------------------------------------------------------------

class DebugLoop:
    """
    Run–Parse–Fix loop for autonomous test debugging.

    Args:
        max_attempts: Maximum run+fix cycles before giving up.  Default 5.
        debug_worker: Object with a ``fix(traceback, filepath, file_content)``
                      method that returns the corrected file content.
                      If ``None``, the loop runs tests and reports failures
                      but cannot apply fixes.
        file_editor:  :class:`~smartagent.workspace.file_editor.FileEditor`
                      instance.  When provided, fixes are written via it
                      (using workspace-relative paths if possible) rather
                      than directly to the filesystem.
        timeout:      Per-run subprocess timeout in seconds.  Default 120.
        cwd:          Working directory for subprocess calls.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        debug_worker: Any | None = None,
        file_editor: Any | None = None,
        timeout: int = 120,
        cwd: str = ".",
    ) -> None:
        self._max_attempts  = max_attempts
        self._debug_worker  = debug_worker
        self._file_editor   = file_editor
        self._timeout       = timeout
        self._cwd           = os.path.abspath(cwd)
        self._parser        = TracebackParser()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, command: str) -> DebugResult:
        """
        Execute *command* in a subprocess and, on failure, attempt automated
        fixes until the command passes or :attr:`max_attempts` is exhausted.

        Args:
            command: Shell command string, e.g. ``"pytest tests/"`` or
                     ``"python -m pytest tests/test_auth.py -x"``.

        Returns:
            :class:`DebugResult` describing all attempts and the final outcome.
        """
        t_start    = time.monotonic()
        attempts:  list[DebugAttempt] = []

        for cycle in range(1, self._max_attempts + 1):
            logger.info(
                "DebugLoop: attempt %d/%d — %r",
                cycle, self._max_attempts, command,
            )

            # --- Run the command -----------------------------------------
            t0               = time.monotonic()
            output, exit_code = self._run_command(command)
            elapsed           = time.monotonic() - t0

            tracebacks = self._parser.parse_all(output)

            attempt = DebugAttempt(
                attempt_num=cycle,
                command=command,
                exit_code=exit_code,
                output=output,
                elapsed=elapsed,
                tracebacks=tracebacks,
            )
            attempts.append(attempt)

            if exit_code == 0:
                logger.info("DebugLoop: tests passed on attempt %d", cycle)
                break

            # --- No worker → report failure, stop loop -------------------
            if self._debug_worker is None:
                logger.info("DebugLoop: no debug_worker; stopping after failure")
                break

            # --- Try to fix -----------------------------------------------
            if not tracebacks:
                logger.info("DebugLoop: no tracebacks parsed; cannot fix")
                break

            fixed_any = self._apply_fixes(attempt, tracebacks)
            if not fixed_any:
                logger.info("DebugLoop: no fixes applied; stopping")
                break

        total_elapsed = time.monotonic() - t_start
        return DebugResult(
            success=bool(attempts and attempts[-1].passed),
            attempts=attempts,
            final_output=attempts[-1].output if attempts else "",
            total_elapsed=total_elapsed,
        )

    # ------------------------------------------------------------------
    # Subprocess execution
    # ------------------------------------------------------------------

    def _run_command(self, command: str) -> tuple[str, int]:
        """
        Run *command* in a subprocess.

        Returns:
            ``(combined_output, exit_code)`` — output is stdout + stderr.
        """
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=self._timeout,
            )
            return proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired:
            return f"[timeout after {self._timeout}s]", 1
        except OSError as exc:
            return f"[error running command: {exc}]", 1

    # ------------------------------------------------------------------
    # Fix application
    # ------------------------------------------------------------------

    def _apply_fixes(
        self,
        attempt: DebugAttempt,
        tracebacks: list[ParsedTraceback],
    ) -> bool:
        """
        Ask the :attr:`debug_worker` to fix each unique failing file.

        Returns ``True`` if at least one fix was successfully applied.
        """
        seen_files: set[str] = set()
        fixed_files: list[str] = []

        for tb in tracebacks:
            frame = tb.root_cause_frame
            if frame is None:
                continue

            fp = frame.filepath
            # Make path absolute relative to cwd when it's relative
            if not os.path.isabs(fp):
                fp = os.path.join(self._cwd, fp)
            fp = os.path.normpath(fp)

            if fp in seen_files:
                continue
            seen_files.add(fp)

            if not os.path.isfile(fp):
                logger.warning("DebugLoop: traceback file not found: %s", fp)
                continue

            try:
                with open(fp, "r", encoding="utf-8") as f:
                    original_content = f.read()
            except OSError as exc:
                logger.warning("DebugLoop: cannot read %s: %s", fp, exc)
                continue

            # Call the worker's fix() method
            try:
                fixed_content = self._debug_worker.fix(
                    traceback=tb,
                    filepath=fp,
                    file_content=original_content,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("DebugLoop: worker.fix() failed for %s: %s", fp, exc)
                continue

            if not fixed_content or fixed_content == original_content:
                logger.info("DebugLoop: worker returned no change for %s", fp)
                continue

            # Write the fix
            wrote = self._write_fix(fp, fixed_content)
            if wrote:
                fixed_files.append(fp)
                logger.info("DebugLoop: fix applied to %s", fp)

        if fixed_files:
            attempt.fix_applied = True
            attempt.files_fixed = fixed_files
            attempt.fix_summary = f"Fixed {len(fixed_files)} file(s)"

        return bool(fixed_files)

    def _write_fix(self, filepath: str, content: str) -> bool:
        """
        Write *content* to *filepath*.

        Uses :attr:`file_editor` when available and the file is within its
        base directory; otherwise writes directly to the filesystem.

        Returns ``True`` on success.
        """
        if self._file_editor is not None:
            base = getattr(self._file_editor, "base_dir", None)
            if base and filepath.startswith(base):
                rel = os.path.relpath(filepath, base)
                result = self._file_editor.edit(rel, content)
                return result.success

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except OSError as exc:
            logger.warning("DebugLoop: cannot write fix to %s: %s", filepath, exc)
            return False
