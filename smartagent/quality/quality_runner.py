"""
QualityRunner — Phase 5: Code Quality.

Automatically runs available code-quality tools and reports results.
Each tool is optional — if it is not installed the result is marked
``skipped`` rather than ``failed``.

Supported tools (run in order):
  1. ``pytest``  — test suite
  2. ``ruff``    — fast linting
  3. ``black``   — formatting check (``--check`` mode, no writes)
  4. ``mypy``    — static type checking

Usage::

    runner = QualityRunner(cwd="/path/to/project")
    report = runner.run_all()
    print("\\n".join(report.as_display_lines()))

    # Run individual tools
    result = runner.run_pytest()
    result = runner.run_ruff()
    result = runner.run_black(check=True)
    result = runner.run_mypy()
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = 300  # seconds per tool


@dataclass
class QualityResult:
    """
    Result from one quality tool run.

    Attributes:
        tool:       Tool name (``"pytest"``, ``"ruff"``, ``"black"``, ``"mypy"``).
        passed:     True when the tool exited with code 0.
        skipped:    True when the tool is not installed / not found.
        output:     Combined stdout + stderr.
        returncode: Exit code (0 = pass, -1 = skipped/error).
        elapsed:    Wall-clock seconds.
    """

    tool: str
    passed: bool
    skipped: bool = False
    output: str = ""
    returncode: int = 0
    elapsed: float = 0.0

    @property
    def icon(self) -> str:
        if self.skipped:
            return "–"
        return "✓" if self.passed else "✗"

    def one_line(self) -> str:
        status = "skipped" if self.skipped else ("PASS" if self.passed else "FAIL")
        return f"{self.icon} {self.tool:<8} [{status}]  ({self.elapsed:.1f}s)"


@dataclass
class QualityReport:
    """
    Aggregate result of all quality tool runs.

    Attributes:
        results:    Per-tool :class:`QualityResult` objects.
        all_passed: True when every non-skipped tool passed.
        total_elapsed: Wall-clock seconds for the full run.
    """

    results: list[QualityResult] = field(default_factory=list)
    all_passed: bool = False
    total_elapsed: float = 0.0

    def as_display_lines(self) -> list[str]:
        """Format the report for console output."""
        icon = "✓" if self.all_passed else "✗"
        label = "ALL PASSED" if self.all_passed else "ISSUES FOUND"
        lines: list[str] = [
            f"{icon} Code Quality: {label}  ({self.total_elapsed:.1f}s)",
            "",
        ]
        for r in self.results:
            lines.append(f"  {r.one_line()}")
            if not r.passed and not r.skipped and r.output:
                tail = r.output.strip().splitlines()[-15:]
                for line in tail:
                    lines.append(f"      {line}")
        return lines

    def failing_tools(self) -> list[str]:
        """Return names of tools that failed (not skipped)."""
        return [r.tool for r in self.results if not r.passed and not r.skipped]

    def get(self, tool: str) -> Optional[QualityResult]:
        """Return the :class:`QualityResult` for *tool*, or ``None``."""
        for r in self.results:
            if r.tool == tool:
                return r
        return None


class QualityRunner:
    """
    Run code-quality tools against a project directory.

    Args:
        cwd:         Working directory for all tool invocations.
        pytest_args: Extra arguments for pytest (e.g. ``"tests/ -x"``).
        ruff_args:   Extra arguments for ruff (e.g. ``"--select E,W"``).
        mypy_args:   Extra arguments for mypy.
        path:        Source path to check (used by ruff, black, mypy).
                     Defaults to ``"."`` (entire cwd).
    """

    def __init__(
        self,
        cwd: str = ".",
        pytest_args: str = "",
        ruff_args: str = "",
        mypy_args: str = "",
        path: str = ".",
    ) -> None:
        import os
        self._cwd = os.path.abspath(cwd)
        self._pytest_args = pytest_args.strip()
        self._ruff_args   = ruff_args.strip()
        self._mypy_args   = mypy_args.strip()
        self._path        = path

    # ------------------------------------------------------------------
    # High-level API
    # ------------------------------------------------------------------

    def run_all(
        self,
        tools: list[str] | None = None,
    ) -> QualityReport:
        """
        Run all (or a subset of) quality tools.

        Args:
            tools: List of tool names to run in order.  Defaults to
                   ``["pytest", "ruff", "black", "mypy"]``.

        Returns:
            :class:`QualityReport` with per-tool results.
        """
        if tools is None:
            tools = ["pytest", "ruff", "black", "mypy"]

        t0 = time.monotonic()
        results: list[QualityResult] = []

        for tool in tools:
            r = self._dispatch(tool)
            results.append(r)
            logger.info("QualityRunner: %s — %s", tool, r.one_line())

        total = time.monotonic() - t0
        non_skipped = [r for r in results if not r.skipped]
        all_passed = bool(non_skipped) and all(r.passed for r in non_skipped)

        return QualityReport(
            results=results,
            all_passed=all_passed,
            total_elapsed=total,
        )

    # ------------------------------------------------------------------
    # Individual tool runners
    # ------------------------------------------------------------------

    def run_pytest(self, args: str = "") -> QualityResult:
        """Run pytest and return the result."""
        extra = args or self._pytest_args
        cmd = f"pytest {extra}".strip()
        return self._run_tool("pytest", cmd)

    def run_ruff(self, path: str = "", args: str = "") -> QualityResult:
        """Run ruff linter and return the result."""
        target = path or self._path
        extra  = args or self._ruff_args
        cmd    = f"ruff check {target} {extra}".strip()
        return self._run_tool("ruff", cmd)

    def run_black(self, path: str = "", check: bool = True, args: str = "") -> QualityResult:
        """
        Run black formatter.

        Args:
            path:  Path to format/check.
            check: When True (default), run in ``--check`` mode (no writes).
        """
        target     = path or self._path
        check_flag = "--check" if check else ""
        extra      = args
        cmd        = f"black {check_flag} {target} {extra}".strip()
        return self._run_tool("black", cmd)

    def run_mypy(self, path: str = "", args: str = "") -> QualityResult:
        """Run mypy static type checker and return the result."""
        target = path or self._path
        extra  = args or self._mypy_args
        cmd    = f"mypy {target} {extra}".strip()
        return self._run_tool("mypy", cmd)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _dispatch(self, tool: str) -> QualityResult:
        """Map a tool name string to the appropriate runner method."""
        dispatch = {
            "pytest": self.run_pytest,
            "ruff":   self.run_ruff,
            "black":  self.run_black,
            "mypy":   self.run_mypy,
        }
        runner = dispatch.get(tool)
        if runner is None:
            return QualityResult(
                tool=tool,
                passed=False,
                skipped=True,
                output=f"Unknown tool: {tool!r}",
                returncode=-1,
            )
        return runner()

    def _run_tool(self, name: str, cmd: str) -> QualityResult:
        """
        Execute *cmd* in a subprocess and return a :class:`QualityResult`.

        If the binary is not found (``FileNotFoundError`` / returncode 127),
        the result is marked ``skipped=True`` rather than ``passed=False``.
        """
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=_TIMEOUT,
            )
            output   = proc.stdout + proc.stderr
            rc       = proc.returncode
            elapsed  = time.monotonic() - t0

            # returncode 127 = command not found (via shell)
            skipped = rc == 127 or _looks_like_not_found(output)

            return QualityResult(
                tool=name,
                passed=rc == 0,
                skipped=skipped,
                output=output,
                returncode=rc,
                elapsed=elapsed,
            )
        except subprocess.TimeoutExpired:
            return QualityResult(
                tool=name,
                passed=False,
                skipped=False,
                output=f"[timeout after {_TIMEOUT}s]",
                returncode=1,
                elapsed=time.monotonic() - t0,
            )
        except OSError as exc:
            return QualityResult(
                tool=name,
                passed=False,
                skipped=True,
                output=str(exc),
                returncode=-1,
                elapsed=time.monotonic() - t0,
            )


def _looks_like_not_found(output: str) -> bool:
    """Heuristic: detect shell 'command not found' messages."""
    low = output.lower()
    return (
        "command not found" in low
        or "no such file or directory" in low
        or "is not recognized" in low
    )
