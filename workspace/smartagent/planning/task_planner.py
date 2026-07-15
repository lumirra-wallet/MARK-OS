"""
Task planning.

Defines `PlannedTask` and `TaskPlanner`, the placeholder abstractions for
breaking a `Goal` (see `smartagent.planning.goal_manager`) down into
concrete, orderable steps the brain can act on. No real planning
algorithm (e.g. a language-model-driven decomposition) is implemented
yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from smartagent.planning.goal_manager import Goal


@dataclass
class PlannedTask:
    """A single concrete step produced by breaking down a `Goal`."""

    description: str
    done: bool = False


class TaskPlanner:
    """Breaks goals down into concrete, executable tasks."""

    def plan(self, goal: Goal) -> list[PlannedTask]:
        """
        Produce an ordered list of tasks that accomplish `goal`.

        Placeholder implementation: raises `NotImplementedError` since no
        planning/decomposition backend has been wired up yet.
        """
        # TODO: use a model (see smartagent.models) and/or skills catalog
        # to decompose the goal into concrete, orderable tasks.
        raise NotImplementedError("Task planning is not implemented yet.")
