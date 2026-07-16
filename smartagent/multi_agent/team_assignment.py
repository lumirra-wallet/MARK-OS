"""
team_assignment.py — TeamAssignment and MultiAgentPlan for Milestone 17.

``TeamAssignment``  — the CEO's instruction to one team: sub-goal + context.
``MultiAgentPlan``  — the full CEO decomposition before any execution begins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TeamAssignment:
    """
    The CEO's instruction to a single team.

    Attributes:
        team_name:    Name of the team that should execute this assignment.
        goal:         Specialised sub-goal for this team.
        context:      Optional background passed from the CEO (or prior teams).
        priority:     Execution order hint (lower = earlier).
        dependencies: Names of other teams whose results should be available
                      before this team runs.
    """

    team_name:    str
    goal:         str
    context:      str = ""
    priority:     int = 0
    dependencies: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"TeamAssignment(team={self.team_name!r}, goal={self.goal[:60]!r})"


@dataclass
class MultiAgentPlan:
    """
    The CEO's full decomposition of a goal into per-team assignments.

    Attributes:
        goal:        Original high-level CEO goal.
        plan_id:     Unique identifier.
        assignments: Ordered list of ``TeamAssignment`` objects.
        created_at:  ISO-8601 creation timestamp.
        model:       Name of the model used for decomposition (empty if rule-based).
    """

    goal:        str
    assignments: list[TeamAssignment] = field(default_factory=list)
    plan_id:     str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at:  str = field(default_factory=_now_iso)
    model:       str = ""

    @property
    def team_count(self) -> int:
        """Number of teams in this plan."""
        return len(self.assignments)

    @property
    def team_names(self) -> list[str]:
        """Ordered list of team names."""
        return [a.team_name for a in self.assignments]

    def as_display_lines(self) -> list[str]:
        """Return a human-readable multi-line breakdown of this plan."""
        lines = [
            f"CEO Plan  [{self.plan_id[:8]}]",
            f"Goal: {self.goal}",
            f"Teams: {self.team_count}",
            "",
        ]
        for i, a in enumerate(self.assignments, 1):
            dep_str = f"  (after: {', '.join(a.dependencies)})" if a.dependencies else ""
            lines.append(f"  {i}. [{a.team_name.upper()}]{dep_str}")
            lines.append(f"     {a.goal[:100]}")
            if a.context:
                lines.append(f"     context: {a.context[:80]}")
        return lines

    def __repr__(self) -> str:
        return (
            f"MultiAgentPlan(goal={self.goal[:50]!r}, "
            f"teams={self.team_names}, id={self.plan_id[:8]})"
        )
