"""
ExecutionDashboard — Phase 6: Execution Dashboard.

A lightweight text-based dashboard that renders a snapshot of MARK's
current execution state.  Designed for use with long-running engineer /
CEO / dev-loop tasks so the user can see what is happening at a glance.

The dashboard is intentionally stateless with respect to the terminal
(no ANSI cursor tricks) so it works in any environment including
piped output, CI, and non-TTY sessions.  Call :meth:`render` to get
a formatted string and print it whenever you want a status update.

Usage::

    dash = ExecutionDashboard()
    dash.start("Build a FastAPI Todo API")
    dash.set("current_worker", "CodingWorker")
    dash.add_completed("Requirement analysis")
    dash.add_file("app/main.py")
    dash.set_tests(passed=12, failed=0)
    print(dash.render())

    dash.complete(success=True)
    print(dash.render())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

_WIDTH  = 62
_BORDER = "=" * _WIDTH
_HR     = "-" * _WIDTH


@dataclass
class _DashState:
    """Internal mutable state for :class:`ExecutionDashboard`."""

    goal:           str           = ""
    current_worker: str           = ""
    completed:      list[str]     = field(default_factory=list)
    running:        list[str]     = field(default_factory=list)
    queued:         list[str]     = field(default_factory=list)
    files_modified: list[str]     = field(default_factory=list)
    tests_passed:   int           = 0
    tests_failed:   int           = 0
    retries:        int           = 0
    current_model:  str           = ""
    tool_calls:     int           = 0
    memory_updates: int           = 0
    knowledge_updates: int        = 0
    started_at:     Optional[float] = None
    finished_at:    Optional[float] = None
    success:        Optional[bool]  = None


class ExecutionDashboard:
    """
    Text-based execution dashboard for long-running MARK tasks.

    All mutating methods return ``self`` to support chaining::

        dash.start("goal").set("current_worker", "Planner").render()
    """

    def __init__(self) -> None:
        self._state = _DashState()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, goal: str) -> "ExecutionDashboard":
        """Initialise the dashboard for a new task."""
        self._state = _DashState(goal=goal, started_at=time.monotonic())
        return self

    def complete(self, success: bool) -> "ExecutionDashboard":
        """Mark the task as finished."""
        self._state.finished_at = time.monotonic()
        self._state.success      = success
        return self

    # ------------------------------------------------------------------
    # State mutators
    # ------------------------------------------------------------------

    def set(self, key: str, value: str) -> "ExecutionDashboard":
        """
        Set a scalar field by name.

        Supported keys: ``"current_worker"``, ``"current_model"``,
        ``"goal"``.
        """
        if hasattr(self._state, key):
            setattr(self._state, key, value)
        return self

    def add_completed(self, task: str) -> "ExecutionDashboard":
        """Mark a task as completed."""
        if task not in self._state.completed:
            self._state.completed.append(task)
        # Also remove from running/queued
        self._state.running = [t for t in self._state.running if t != task]
        self._state.queued  = [t for t in self._state.queued  if t != task]
        return self

    def add_running(self, task: str) -> "ExecutionDashboard":
        """Mark a task as currently running."""
        if task not in self._state.running:
            self._state.running.append(task)
        self._state.queued = [t for t in self._state.queued if t != task]
        return self

    def add_queued(self, task: str) -> "ExecutionDashboard":
        """Add a task to the queue."""
        if task not in self._state.queued:
            self._state.queued.append(task)
        return self

    def add_file(self, path: str) -> "ExecutionDashboard":
        """Record that a file was modified."""
        if path not in self._state.files_modified:
            self._state.files_modified.append(path)
        return self

    def set_tests(self, passed: int, failed: int) -> "ExecutionDashboard":
        """Update test pass/fail counters."""
        self._state.tests_passed = passed
        self._state.tests_failed = failed
        return self

    def increment_retries(self) -> "ExecutionDashboard":
        """Increment the retry counter by one."""
        self._state.retries += 1
        return self

    def increment_tool_calls(self, n: int = 1) -> "ExecutionDashboard":
        """Increment the tool-call counter."""
        self._state.tool_calls += n
        return self

    def increment_memory(self) -> "ExecutionDashboard":
        """Record a memory update."""
        self._state.memory_updates += 1
        return self

    def increment_knowledge(self) -> "ExecutionDashboard":
        """Record a knowledge update."""
        self._state.knowledge_updates += 1
        return self

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Return the full dashboard as a formatted string."""
        s = self._state
        lines: list[str] = [_BORDER, _center("MARK  ·  EXECUTION DASHBOARD"), _BORDER, ""]

        # Status header
        if s.success is None:
            status = "● RUNNING"
        elif s.success:
            status = "✓ COMPLETE"
        else:
            status = "✗ FAILED"

        elapsed = _elapsed(s.started_at, s.finished_at)

        lines += [
            _row("Status", status),
            _row("Elapsed", elapsed),
            _row("Goal", _trunc(s.goal, 44)),
            "",
        ]

        # Workers
        lines.append(_HR)
        lines.append("  WORKERS")
        lines.append("")
        if s.current_worker:
            lines.append(_row("  Active", s.current_worker))
        _list_rows(lines, "  Done",    s.completed,  icon="✓", limit=5)
        _list_rows(lines, "  Running", s.running,    icon="►", limit=3)
        _list_rows(lines, "  Queued",  s.queued,     icon="·", limit=5)
        lines.append("")

        # Files
        lines.append(_HR)
        lines.append("  FILES")
        lines.append("")
        if s.files_modified:
            lines.append(_row("  Modified", str(len(s.files_modified))))
            for fp in s.files_modified[:6]:
                lines.append(f"    + {fp}")
            if len(s.files_modified) > 6:
                lines.append(f"    … and {len(s.files_modified) - 6} more")
        else:
            lines.append("    (none yet)")
        lines.append("")

        # Tests & quality
        lines.append(_HR)
        lines.append("  TESTS & QUALITY")
        lines.append("")
        test_str = f"{s.tests_passed} passed"
        if s.tests_failed:
            test_str += f", {s.tests_failed} failed"
        lines.append(_row("  Tests", test_str))
        lines.append(_row("  Retries", str(s.retries)))
        lines.append("")

        # System
        lines.append(_HR)
        lines.append("  SYSTEM")
        lines.append("")
        lines.append(_row("  Model",    s.current_model or "—"))
        lines.append(_row("  Tools",    str(s.tool_calls)))
        lines.append(_row("  Memory",   str(s.memory_updates)))
        lines.append(_row("  Knowledge", str(s.knowledge_updates)))
        lines.append("")

        lines.append(_BORDER)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # State access (for tests)
    # ------------------------------------------------------------------

    @property
    def state(self) -> _DashState:
        """Access the internal state (read-only by convention)."""
        return self._state


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _center(text: str) -> str:
    return text.center(_WIDTH)


def _row(label: str, value: str) -> str:
    return f"  {label:<18} {value}"


def _trunc(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _elapsed(started: Optional[float], finished: Optional[float]) -> str:
    if started is None:
        return "—"
    end = finished if finished is not None else time.monotonic()
    secs = end - started
    if secs < 60:
        return f"{secs:.1f}s"
    mins = int(secs // 60)
    s    = secs % 60
    return f"{mins}m {s:.0f}s"


def _list_rows(
    lines: list[str],
    label: str,
    items: list[str],
    icon: str,
    limit: int,
) -> None:
    if not items:
        return
    lines.append(f"  {label}:")
    for item in items[:limit]:
        lines.append(f"    {icon} {item}")
    if len(items) > limit:
        lines.append(f"    … and {len(items) - limit} more")
