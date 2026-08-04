"""
Turn Taking State Machine.

Manages active conversational state and turn transitions.
"""

from __future__ import annotations

from enum import Enum, auto
import logging
from typing import Callable, List

logger = logging.getLogger("smartagent.voice.conversation.turn_manager")


class TurnState(Enum):
    """Conversational turn states."""

    IDLE = auto()
    USER_SPEAKING = auto()
    ASSISTANT_THINKING = auto()
    ASSISTANT_SPEAKING = auto()
    EXECUTING_TOOL = auto()


class TurnManager:
    """
    Manages conversational turn taking states.
    """

    def __init__(self) -> None:
        self.state = TurnState.IDLE
        self._listeners: List[Callable[[TurnState, TurnState], None]] = []

    def add_listener(self, listener: Callable[[TurnState, TurnState], None]) -> None:
        """Register a callback listener for state transitions."""
        self._listeners.append(listener)

    def transition_to(self, new_state: TurnState) -> None:
        """Transition state machine to new_state and notify listeners."""
        if self.state == new_state:
            return

        old_state = self.state
        self.state = new_state
        logger.info(f"🔄 [TurnManager] Transition: {old_state.name} ➔ {new_state.name}")

        for listener in self._listeners:
            try:
                listener(old_state, new_state)
            except Exception as exc:
                logger.error(f"Error in turn listener: {exc}")
