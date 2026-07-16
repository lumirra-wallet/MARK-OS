"""
LoopResult and LoopIteration — data models for the autonomous dev loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoopIteration:
    """
    One complete Receive→Plan→Code→Test→Debug→Reflect cycle.

    Attributes:
        iteration:     1-based cycle number.
        phase:         Which phase this record covers (``"planning"``,
                       ``"coding"``, ``"testing"``, ``"debugging"``,
                       ``"reflection"``).
        success:       Whether this phase produced a passing result.
        notes:         Human-readable description of what happened.
        tests_passed:  Number of tests that passed (if known).
        tests_failed:  Number of tests that failed (if known).
        elapsed:       Wall-clock seconds this phase took.
    """

    iteration:    int
    phase:        str
    success:      bool
    notes:        str  = ""
    tests_passed: int  = 0
    tests_failed: int  = 0
    elapsed:      float = 0.0

    @property
    def icon(self) -> str:
        return "✓" if self.success else "✗"


@dataclass
class LoopResult:
    """
    Aggregate result of the full autonomous development loop.

    Attributes:
        goal:           Original goal string.
        success:        True if the final state is all tests green.
        iterations:     All cycle records in execution order.
        final_summary:  Prose summary from the last completed phase.
        total_elapsed:  Total wall-clock time in seconds.
        stop_reason:    Why the loop stopped (``"success"``,
                        ``"max_iterations"``, ``"error"``).
        files_created:  Paths of files created by workers in this run.
        files_modified: Paths of files edited/patched by workers in this run.
        project_dir:    Absolute path where generated files were written.
    """

    goal:           str
    success:        bool
    iterations:     list[LoopIteration] = field(default_factory=list)
    final_summary:  str   = ""
    total_elapsed:  float = 0.0
    stop_reason:    str   = "unknown"
    files_created:  list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    project_dir:    str   = ""

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def as_display_lines(self) -> list[str]:
        icon  = "✓" if self.success else "✗"
        label = "SUCCESS" if self.success else "NOT COMPLETE"
        lines: list[str] = [
            f"{icon} Dev Loop: {label}",
            f"  Goal      : {self.goal[:72]}",
            f"  Stop      : {self.stop_reason}",
            f"  Cycles    : {self._cycle_count()}",
            f"  Elapsed   : {self.total_elapsed:.1f}s",
            "",
        ]

        # Files created / modified during this run
        if self.files_created or self.files_modified:
            lines.append("  Files:")
            for f in self.files_created:
                lines.append(f"    + {f}")
            for f in self.files_modified:
                lines.append(f"    ~ {f}")
            if self.project_dir:
                lines.append(f"    (in {self.project_dir})")
            lines.append("")

        if self.iterations:
            lines.append("  Trace:")
            for it in self.iterations:
                elapsed_str = f"  ({it.elapsed:.1f}s)" if it.elapsed else ""
                lines.append(
                    f"    [{it.iteration}] {it.icon} {it.phase.title()}{elapsed_str}"
                )
                if it.notes:
                    lines.append(f"        {it.notes[:100]}")
                if it.tests_failed or it.tests_passed:
                    lines.append(
                        f"        Tests: {it.tests_passed} passed, "
                        f"{it.tests_failed} failed"
                    )
            lines.append("")

        if self.final_summary:
            lines.append("  Summary:")
            for chunk in [
                self.final_summary[i:i+80]
                for i in range(0, min(len(self.final_summary), 400), 80)
            ]:
                lines.append(f"    {chunk}")

        return lines

    def _cycle_count(self) -> int:
        if not self.iterations:
            return 0
        return max(it.iteration for it in self.iterations)
