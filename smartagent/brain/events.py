"""
EventBus — Brain v2's publish/subscribe mechanism.

Design decision: many parts of SmartAgent need to react to things that
happen elsewhere (e.g. "a memory was saved", "a task finished") without
being tightly coupled to whoever caused it. Rather than having modules
call each other directly, they publish an `Event` onto a shared
`EventBus` and anything interested subscribes to it by name. This keeps
modules independent and replaceable (see SMARTAGENT.md's architecture
philosophy) — a new module can react to `MemorySaved` without `memory`
ever knowing it exists.

`Events` collects the well-known event names used across the codebase so
publishers and subscribers agree on spelling without importing each
other's modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

EventHandler = Callable[["Event"], None]


@dataclass
class Event:
    """A single published event: a name, a timestamp, and an arbitrary payload."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class Events:
    """
    Well-known event names, grouped by the module that publishes them.

    Kept as plain string constants (not an Enum) so any module can publish
    an ad hoc event name too — this is a convenience list, not a closed
    schema enforced by `EventBus`.
    """

    # Memory (smartagent.memory)
    MEMORY_SAVED = "MemorySaved"
    MEMORY_UPDATED = "MemoryUpdated"
    MEMORY_DELETED = "MemoryDeleted"

    # Research (smartagent.research)
    RESEARCH_STARTED = "ResearchStarted"
    RESEARCH_FINISHED = "ResearchFinished"

    # Planning (smartagent.planning)
    TASK_COMPLETED = "TaskCompleted"

    # Skills (smartagent.skills)
    SKILL_EXECUTED = "SkillExecuted"

    # Brain (smartagent.brain) — the routing pipeline itself.
    REQUEST_RECEIVED = "RequestReceived"
    BRAIN_DECISION_MADE = "BrainDecisionMade"


class EventBus:
    """
    A minimal in-process publish/subscribe bus.

    No persistence, no external broker — Memory v1's constraints apply
    here too (no databases). `EventBus` is intentionally synchronous:
    `publish()` calls every subscriber immediately, in registration order,
    so behavior stays simple and deterministic to reason about and test.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        # Keeping a history (not required by any subscriber) makes the bus
        # inspectable in tests and gives a natural audit trail of "what did
        # the Brain do" without adding a separate logging path.
        self._history: list[Event] = []

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register `handler` to be called whenever `event_name` is published."""
        self._subscribers.setdefault(event_name, []).append(handler)

    def publish(self, event_name: str, **payload: Any) -> Event:
        """Publish `event_name` with `payload`, notify subscribers, and return the `Event`."""
        event = Event(name=event_name, payload=payload)
        self._history.append(event)
        logger.info("Event published: %s %s", event.name, event.payload)
        for handler in self._subscribers.get(event_name, []):
            handler(event)
        return event

    def history(self) -> list[Event]:
        """Return every event published on this bus so far, oldest first."""
        return list(self._history)
