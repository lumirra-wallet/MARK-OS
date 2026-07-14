"""
StateMachine — Milestone 6, Part 9 (Internal State Engine).

Maintains MARK's current digital state (idle, thinking, planning, ...) and
a full transition history. Deliberately permissive about which transitions
are allowed — the milestone brief doesn't specify a transition table, and
an internal state machine that rejects a legitimate transition (e.g.
`ERROR -> IDLE` after a quick recovery) would be more harmful than one
that logs every transition and lets the caller decide when to use each
state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_MAX_HISTORY = 200


class InternalState(str, Enum):
    """The fixed set of digital states MARK can be in."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    PLANNING = "planning"
    RESEARCHING = "researching"
    EXECUTING = "executing"
    REFLECTING = "reflecting"
    LEARNING = "learning"
    WAITING = "waiting"
    SLEEPING = "sleeping"
    ERROR = "error"
    RECOVERING = "recovering"


@dataclass
class StateTransition:
    """A single recorded state change."""

    from_state: InternalState
    to_state: InternalState
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class StateMachine:
    """
    Tracks MARK's current `InternalState` and every transition made.

    Args:
        initial_state: State to start in. Defaults to `InternalState.IDLE`.
        event_bus: Optional bus to publish `StateChanged` onto.
    """

    def __init__(self, initial_state: InternalState = InternalState.IDLE, event_bus: EventBus | None = None) -> None:
        self.events = event_bus
        self._state = initial_state
        self._history: list[StateTransition] = []

    @property
    def state(self) -> InternalState:
        """The current state."""
        return self._state

    def transition(self, to_state: InternalState, reason: str = "") -> StateTransition:
        """Move to `to_state`, recording the transition and publishing `StateChanged`."""
        record = StateTransition(from_state=self._state, to_state=to_state, reason=reason)
        self._state = to_state
        self._history.append(record)
        del self._history[:-_MAX_HISTORY]

        logger.info("State changed: %s -> %s (%s)", record.from_state.value, record.to_state.value, reason)
        if self.events is not None:
            self.events.publish(
                Events.STATE_CHANGED,
                from_state=record.from_state.value,
                to_state=record.to_state.value,
                reason=reason,
            )
        return record

    def history(self) -> list[StateTransition]:
        """Every transition made so far, oldest first."""
        return list(self._history)

    def is_in(self, *states: InternalState) -> bool:
        """Whether the current state is one of `states`."""
        return self._state in states
