"""
AttentionManager — Milestone 6, Part 5.

Computational attention: decides what MARK should focus on right now,
ranks candidate tasks by importance, caps how many things can be "in
focus" concurrently, and supports being interrupted (with a resume stack)
by something more important. This is the primitive future multitasking
would be built on top of — not multitasking itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_CONCURRENT = 3


@dataclass
class FocusItem:
    """A single candidate for MARK's attention."""

    name: str
    importance: float = 0.5
    source: str = "unknown"


class AttentionManager:
    """
    Ranks and tracks what MARK is currently focused on.

    Args:
        max_concurrent: How many items can be in focus at once (Part 5:
            "Limit concurrent thinking"). Attempting to focus on more than
            this evicts the lowest-importance current focus item.
        event_bus: Optional bus to publish `AttentionShifted` onto.
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT, event_bus: EventBus | None = None) -> None:
        self.max_concurrent = max_concurrent
        self.events = event_bus
        self._focus: list[FocusItem] = []
        self._interrupt_stack: list[list[FocusItem]] = []

    def rank(self, items: list[FocusItem]) -> list[FocusItem]:
        """Return `items` sorted most-important-first (stable for equal importance)."""
        return sorted(items, key=lambda item: item.importance, reverse=True)

    def focus_on(self, item: FocusItem) -> list[FocusItem]:
        """
        Add `item` to the current focus set, evicting the least important item(s)
        if that would exceed `max_concurrent`. Publishes `AttentionShifted`.
        """
        self._focus.append(item)
        self._focus = self.rank(self._focus)[: self.max_concurrent]
        logger.info("Attention shifted: focusing on %s (importance=%.2f)", item.name, item.importance)
        if self.events is not None:
            self.events.publish(Events.ATTENTION_SHIFTED, focus=[i.name for i in self._focus])
        return self.current_focus()

    def current_focus(self) -> list[FocusItem]:
        """The items currently in focus, most important first."""
        return list(self._focus)

    def drop(self, name: str) -> bool:
        """Remove an item from focus by name. Returns whether it was present."""
        before = len(self._focus)
        self._focus = [item for item in self._focus if item.name != name]
        return len(self._focus) != before

    def interrupt(self, item: FocusItem) -> list[FocusItem]:
        """
        Push the current focus set aside and focus solely on `item` (Part 5:
        "Handle interruption"). Call `resume()` to restore what was interrupted.
        """
        self._interrupt_stack.append(list(self._focus))
        self._focus = []
        return self.focus_on(item)

    def resume(self) -> list[FocusItem]:
        """Restore the focus set from before the most recent `interrupt()`, if any."""
        if not self._interrupt_stack:
            return self.current_focus()
        self._focus = self._interrupt_stack.pop()
        if self.events is not None:
            self.events.publish(Events.ATTENTION_SHIFTED, focus=[i.name for i in self._focus])
        return self.current_focus()

    def clear(self) -> None:
        """Drop all focus and interruption history."""
        self._focus = []
        self._interrupt_stack = []
