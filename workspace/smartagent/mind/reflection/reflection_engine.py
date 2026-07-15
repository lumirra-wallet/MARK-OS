"""
ReflectionEngine — Milestone 6, Part 11.

After every completed task, ask: what happened, did I succeed, what
failed, should this become a memory, can this improve future performance,
did I learn anything. Reflections are stored **separately from normal
memories** — this engine never writes to `smartagent.memory`'s vault; it
only decides (and records) *whether* something looks memory-worthy,
leaving the actual write to whatever already owns that decision (e.g. a
Skill, or a future Learning Engine per Part 14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_MAX_REFLECTIONS = 200


@dataclass
class Reflection:
    """The outcome of reflecting on one completed task."""

    task_name: str
    succeeded: bool
    what_happened: str
    what_failed: str | None = None
    should_become_memory: bool = False
    could_improve_future_performance: bool = False
    learned: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class ReflectionEngine:
    """
    Reflects on completed tasks and keeps a bounded, separate reflection log.

    Args:
        event_bus: Optional bus to publish `ReflectionFinished` onto.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.events = event_bus
        self._reflections: list[Reflection] = []

    def reflect(
        self,
        task_name: str,
        succeeded: bool,
        what_happened: str,
        what_failed: str | None = None,
        learned: str | None = None,
    ) -> Reflection:
        """
        Build and record a `Reflection` for one completed task.

        `should_become_memory` and `could_improve_future_performance` are
        derived heuristically: a failure, or a task that produced something
        explicitly `learned`, is judged worth remembering / improving from.
        """
        should_become_memory = (not succeeded) or bool(learned)
        could_improve = (not succeeded) or bool(what_failed) or bool(learned)

        reflection = Reflection(
            task_name=task_name,
            succeeded=succeeded,
            what_happened=what_happened,
            what_failed=what_failed,
            should_become_memory=should_become_memory,
            could_improve_future_performance=could_improve,
            learned=learned,
        )
        self._reflections.append(reflection)
        del self._reflections[:-_MAX_REFLECTIONS]

        logger.info("Reflection finished: task=%s succeeded=%s", task_name, succeeded)
        if self.events is not None:
            self.events.publish(Events.REFLECTION_FINISHED, task_name=task_name, succeeded=succeeded)
        return reflection

    def list_reflections(self, succeeded: bool | None = None) -> list[Reflection]:
        """All reflections so far, oldest first, optionally filtered by outcome."""
        if succeeded is None:
            return list(self._reflections)
        return [r for r in self._reflections if r.succeeded == succeeded]

    def memory_worthy(self) -> list[Reflection]:
        """Reflections flagged `should_become_memory` — candidates for a future Learning Engine."""
        return [r for r in self._reflections if r.should_become_memory]
