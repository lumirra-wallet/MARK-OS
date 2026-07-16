"""
team_result.py — TeamResult and MultiAgentResult for Milestone 17.

``TeamResult``       — what one team produced from its TeamRunner execution.
``MultiAgentResult`` — rolled-up view of all teams' results from a CEO run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TeamResult:
    """
    Outcome of running one team against a TeamAssignment.

    Attributes:
        team_name:   Name of the team.
        goal:        The sub-goal this team worked on.
        state:       ``"completed"`` | ``"partial"`` | ``"failed"``.
        summary:     Brief prose summary of what the team produced.
        outputs:     Key artefacts or bullet points the team generated.
        task_count:  Total tasks dispatched.
        completed:   Tasks that finished successfully.
        failed:      Tasks that errored.
        duration:    Wall-clock seconds for the entire team run.
        error:       Error message if the team could not start at all.
    """

    team_name:  str
    goal:       str
    state:      str = "completed"       # completed | partial | failed
    summary:    str = ""
    outputs:    list[str] = field(default_factory=list)
    task_count: int = 0
    completed:  int = 0
    failed:     int = 0
    duration:   float = 0.0
    error:      Optional[str] = None

    @property
    def success_rate(self) -> float:
        """Fraction of tasks that completed successfully (0.0–1.0)."""
        return self.completed / self.task_count if self.task_count else 0.0

    def one_line(self) -> str:
        icon = {"completed": "✓", "partial": "~", "failed": "✗"}.get(self.state, "?")
        return (
            f"{icon} [{self.team_name:13s}]  "
            f"{self.completed}/{self.task_count} tasks  "
            f"{self.duration:.1f}s  "
            f"{self.state}"
        )

    def __repr__(self) -> str:
        return (
            f"TeamResult(team={self.team_name!r}, state={self.state!r}, "
            f"tasks={self.completed}/{self.task_count})"
        )


@dataclass
class MultiAgentResult:
    """
    Aggregated result from a full CEO multi-agent execution.

    Attributes:
        goal:          Original high-level CEO goal.
        plan_id:       Identifier of the ``MultiAgentPlan`` that was executed.
        team_results:  One ``TeamResult`` per team, in execution order.
        overall_state: ``"completed"`` | ``"partial"`` | ``"failed"``.
        summary:       CEO-level prose summary built from team summaries.
        duration:      Total wall-clock seconds for the entire run.
    """

    goal:          str
    plan_id:       str = ""
    team_results:  list[TeamResult] = field(default_factory=list)
    overall_state: str = "completed"
    summary:       str = ""
    duration:      float = 0.0

    # ------------------------------------------------------------------
    # Derived statistics
    # ------------------------------------------------------------------

    @property
    def team_count(self) -> int:
        return len(self.team_results)

    @property
    def completed_teams(self) -> int:
        return sum(1 for r in self.team_results if r.state == "completed")

    @property
    def failed_teams(self) -> int:
        return sum(1 for r in self.team_results if r.state == "failed")

    @property
    def total_tasks(self) -> int:
        return sum(r.task_count for r in self.team_results)

    @property
    def total_completed(self) -> int:
        return sum(r.completed for r in self.team_results)

    @property
    def total_failed(self) -> int:
        return sum(r.failed for r in self.team_results)

    def all_outputs(self) -> list[str]:
        """Flat list of all outputs from every team, labelled by team."""
        out: list[str] = []
        for r in self.team_results:
            for o in r.outputs:
                out.append(f"[{r.team_name}] {o}")
        return out

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def as_display_lines(self) -> list[str]:
        """Return a human-readable multi-line summary."""
        icon = {"completed": "✓", "partial": "~", "failed": "✗"}.get(
            self.overall_state, "?"
        )
        lines = [
            f"{icon} Multi-Agent Result — {self.overall_state.upper()}",
            f"  Goal  : {self.goal}",
            f"  Plan  : {self.plan_id[:8]}",
            f"  Teams : {self.completed_teams}/{self.team_count} completed",
            f"  Tasks : {self.total_completed}/{self.total_tasks} completed",
            f"  Time  : {self.duration:.1f}s",
            "",
            "  Team breakdown:",
        ]
        for r in self.team_results:
            lines.append(f"    {r.one_line()}")
            if r.summary:
                preview = r.summary[:120] + "…" if len(r.summary) > 120 else r.summary
                lines.append(f"      {preview}")
        if self.summary:
            lines += ["", "  CEO summary:", f"    {self.summary}"]
        return lines

    def __repr__(self) -> str:
        return (
            f"MultiAgentResult(state={self.overall_state!r}, "
            f"teams={self.team_count}, tasks={self.total_completed}/{self.total_tasks})"
        )
