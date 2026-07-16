"""
CompletionReport — structured result for a long-running execution.

Shows exactly what MARK completed, what remains, and how long it took.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PhaseResult:
    """
    The outcome of one high-level phase (e.g. Backend, Tests, Docs).

    Attributes:
        name:       Human-readable label (e.g. ``"Backend"``, ``"Tests"``).
        success:    Whether this phase completed without errors.
        summary:    One-sentence description of what was done.
        elapsed:    Wall-clock time in seconds.
        team:       Which team / worker handled this phase.
    """

    name:    str
    success: bool
    summary: str = ""
    elapsed: float = 0.0
    team:    str = ""

    @property
    def icon(self) -> str:
        return "✓" if self.success else "✗"

    def __str__(self) -> str:
        time_str = f"  ({self.elapsed:.1f}s)" if self.elapsed else ""
        return f"  {self.icon} {self.name}{time_str}"


@dataclass
class CompletionReport:
    """
    Full report for a long-running CEO execution.

    Attributes:
        goal:          The original goal string.
        completed:     Phases that finished successfully.
        failed:        Phases that failed.
        remaining:     Phases not yet attempted (cut short or planned but skipped).
        total_elapsed: Wall-clock seconds for the whole run.
        success:       True when at least one phase completed and none failed.
        summary:       One-paragraph prose summary from the last team.
    """

    goal:          str
    completed:     list[PhaseResult] = field(default_factory=list)
    failed:        list[PhaseResult] = field(default_factory=list)
    remaining:     list[str]         = field(default_factory=list)
    total_elapsed: float = 0.0
    success:       bool  = False
    summary:       str   = ""

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def as_display_lines(self) -> list[str]:
        """Rich multiline console report."""
        lines: list[str] = [
            f"Long-Run Report: {self.goal[:72]}",
            "─" * 60,
            "",
        ]

        if self.completed:
            lines.append(f"  Completed ({len(self.completed)}):")
            for p in self.completed:
                elapsed = f"  {p.elapsed:.1f}s" if p.elapsed else ""
                lines.append(f"    ✓ {p.name}{elapsed}")
                if p.summary:
                    lines.append(f"      {p.summary[:120]}")
            lines.append("")

        if self.failed:
            lines.append(f"  Failed ({len(self.failed)}):")
            for p in self.failed:
                lines.append(f"    ✗ {p.name}")
                if p.summary:
                    lines.append(f"      {p.summary[:120]}")
            lines.append("")

        if self.remaining:
            lines.append(f"  Remaining ({len(self.remaining)}):")
            for name in self.remaining:
                lines.append(f"    · {name}")
            lines.append("")

        if self.summary:
            lines.append("  Summary:")
            for chunk in [self.summary[i:i+80] for i in range(0, min(len(self.summary), 400), 80)]:
                lines.append(f"    {chunk}")
            lines.append("")

        status = "SUCCESS" if self.success else ("PARTIAL" if self.completed else "FAILED")
        lines.append(f"  Status: {status}  |  Total time: {self.total_elapsed:.1f}s")
        return lines

    def as_short_summary(self) -> str:
        """One-line summary for quick display."""
        done = len(self.completed)
        fail = len(self.failed)
        rem  = len(self.remaining)
        t = f"{self.total_elapsed:.0f}s"
        return (
            f"{'✓' if self.success else '~'} {done} done"
            + (f", {fail} failed" if fail else "")
            + (f", {rem} remaining" if rem else "")
            + f"  [{t}]"
        )
