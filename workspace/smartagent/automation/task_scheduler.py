"""
Task scheduling and automation triggers.

Defines `TaskScheduler`, the placeholder abstraction for registering and
running background/scheduled tasks (e.g. "check email every 10 minutes",
"send a daily summary at 8am"). No real scheduling loop (e.g. via
`schedule`, `APScheduler`, or a cron-like mechanism) is wired up yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class ScheduledTask:
    """A single automation task registered with the scheduler."""

    name: str
    interval_seconds: float
    action: Callable[[], None]


class TaskScheduler:
    """
    Registers and (eventually) runs recurring automation tasks.

    Placeholder implementation: tasks can be registered, but nothing is
    actually scheduled or executed yet.
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._tasks: list[ScheduledTask] = []

    def register(self, name: str, interval_seconds: float, action: Callable[[], None]) -> None:
        """Add a recurring task definition to the scheduler."""
        self._tasks.append(ScheduledTask(name=name, interval_seconds=interval_seconds, action=action))

    def list_tasks(self) -> list[str]:
        """Return the names of all currently registered tasks."""
        return [task.name for task in self._tasks]

    def start(self) -> None:
        """
        Begin running registered tasks on their configured intervals.

        Placeholder implementation: does nothing yet.
        """
        # TODO: implement an actual scheduling loop (e.g. using `schedule`,
        # `APScheduler`, asyncio, or a simple thread-based timer) that
        # invokes each task's `action` every `interval_seconds`.
        raise NotImplementedError("Task scheduling is not implemented yet.")
