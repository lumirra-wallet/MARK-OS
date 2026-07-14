"""
Goal management.

Defines `Goal` and `GoalManager`, the placeholder abstractions for
tracking the owner's longer-running objectives (e.g. "launch the new
product page", "learn Rust this quarter"). `TaskPlanner`
(`smartagent.planning.task_planner`) will later break goals down into
concrete tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Goal:
    """A single tracked objective for the owner."""

    name: str
    description: str = ""
    status: str = "active"  # e.g. "active", "paused", "completed"


class GoalManager:
    """Tracks the set of goals MARK is currently helping the owner pursue."""

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}

    def add_goal(self, goal: Goal) -> None:
        """Register a new goal."""
        self._goals[goal.name] = goal

    def get_goal(self, name: str) -> Goal | None:
        """Look up a goal by name, or None if not found."""
        return self._goals.get(name)

    def list_goals(self, status: str | None = None) -> list[Goal]:
        """
        List tracked goals, optionally filtered by status.

        Placeholder implementation: simple in-memory filtering. No
        persistence yet — goals are lost when the process restarts.
        """
        goals = list(self._goals.values())
        if status is not None:
            goals = [g for g in goals if g.status == status]
        return goals

    def update_status(self, name: str, status: str) -> None:
        """Update the status of a tracked goal, if it exists."""
        goal = self._goals.get(name)
        if goal is not None:
            goal.status = status
