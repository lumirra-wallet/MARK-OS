"""
DigitalSensorySystem — Milestone 6, Part 12.

Computational sensations: internal signals MARK can detect about its own
state (memory changed, high CPU load, low confidence, ...). These are
explicitly **not** human emotions — they are typed events with a payload,
nothing more. `DigitalSensorySystem` just standardizes detection +
recording + publishing so every part of the Mind reports signals the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_MAX_HISTORY = 200


class SensorySignal(str, Enum):
    """The fixed set of computational signals MARK can detect about itself."""

    MEMORY_CHANGED = "memory_changed"
    HIGH_CPU_LOAD = "high_cpu_load"
    LOW_CONFIDENCE = "low_confidence"
    KNOWLEDGE_CONFLICT = "knowledge_conflict"
    NEW_GOAL = "new_goal"
    TASK_DELAY = "task_delay"
    MODULE_FAILURE = "module_failure"
    RESEARCH_COMPLETED = "research_completed"
    TOOL_FAILURE = "tool_failure"
    PERMISSION_DENIED = "permission_denied"


@dataclass
class SensoryEvent:
    """One detected signal, with whatever context explains it."""

    signal: SensorySignal
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class DigitalSensorySystem:
    """
    Detects and records computational signals, publishing `SensorySignalDetected` for each.

    Args:
        event_bus: Optional bus to publish onto.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.events = event_bus
        self._history: list[SensoryEvent] = []

    def detect(self, signal: SensorySignal, detail: str = "", **payload: Any) -> SensoryEvent:
        """Record `signal` and publish `SensorySignalDetected`."""
        event = SensoryEvent(signal=signal, detail=detail, payload=payload)
        self._history.append(event)
        del self._history[:-_MAX_HISTORY]

        logger.info("Sensory signal detected: %s (%s)", signal.value, detail)
        if self.events is not None:
            self.events.publish(Events.SENSORY_SIGNAL_DETECTED, signal=signal.value, detail=detail, **payload)
        return event

    def history(self, signal: SensorySignal | None = None) -> list[SensoryEvent]:
        """Every detected signal so far, oldest first, optionally filtered by `signal`."""
        if signal is None:
            return list(self._history)
        return [event for event in self._history if event.signal == signal]
