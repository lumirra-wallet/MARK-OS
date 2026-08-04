"""
event_bus.py — Elena's async event nervous system.

The EventBus is the single channel through which all runtime subsystems
communicate without directly importing each other.  Publishers fire events;
subscribers react.  Neither side holds a reference to the other.

Design principles
─────────────────
• Fully async — all handlers are awaited (or scheduled on the loop).
• Weakly coupled — publishers and subscribers never import each other.
• Ordered — handlers for the same event type are called in subscription order.
• Non-crashing — a failing handler logs the error and lets others proceed.
• Observable — every event carries a timestamp and optional correlation ID.

Usage
─────
    bus = EventBus()

    # Subscribe
    async def on_turn_started(event: Event) -> None:
        print("turn started:", event.data)

    bus.subscribe("turn.started", on_turn_started)

    # Publish
    await bus.publish(Event("turn.started", data={"text": "Hello"}))

    # One-shot (auto-unsubscribed after first delivery)
    await bus.subscribe_once("session.ended", on_session_ended)

    # Wildcard  (receives ALL events — useful for logging / audit)
    bus.subscribe("*", audit_logger)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

# A handler is an async callable that receives one Event.
Handler = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass
class Event:
    """
    An immutable event payload flowing through the EventBus.

    Attributes
    ──────────
    type        Dotted-path string identifying the event, e.g. "turn.started".
    data        Arbitrary JSON-serialisable payload dict (default: {}).
    source      Name of the subsystem that emitted this event.
    event_id    UUID — unique per emission, useful for de-duplication.
    timestamp   Unix epoch float at creation time.
    """

    type:      str
    data:      Dict[str, Any]    = field(default_factory=dict)
    source:    str               = ""
    event_id:  str               = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float             = field(default_factory=time.time)

    def __repr__(self) -> str:
        return (
            f"Event(type={self.type!r}, source={self.source!r}, "
            f"data={self.data!r})"
        )


class EventBus:
    """
    Async publish/subscribe event bus.

    Thread safety: designed for single-threaded asyncio usage.  If you need
    cross-thread publishing, call ``asyncio.run_coroutine_threadsafe``.
    """

    # Well-known event type constants — use these instead of raw strings to
    # prevent typos causing silent missed events.
    TURN_STARTED        = "turn.started"
    TURN_ENDED          = "turn.ended"
    SESSION_STARTED     = "session.started"
    SESSION_ENDED       = "session.ended"
    SPEECH_START        = "speech.start"         # user started speaking
    SPEECH_END          = "speech.end"           # user stopped speaking
    ELENA_SPEAKING_START = "elena.speaking.start" # Elena's audio began
    ELENA_SPEAKING_END   = "elena.speaking.end"   # Elena's audio ended
    PROVIDER_CHANGED    = "provider.changed"
    MEMORY_STORED       = "memory.stored"
    MEMORY_RETRIEVED    = "memory.retrieved"
    IDENTITY_ASSERTED   = "identity.asserted"    # identity challenge handled
    ERROR               = "error"
    SHUTDOWN            = "runtime.shutdown"

    def __init__(self) -> None:
        # Maps event_type → list of (handler, one_shot)
        self._handlers: Dict[str, List[tuple[Handler, bool]]] = defaultdict(list)
        self._history: List[Event] = []
        self._history_max: int = 200   # keep last N events for replay/debug
        self._lock = asyncio.Lock()

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """
        Register a persistent handler for ``event_type``.

        Use ``"*"`` to receive every event (wildcard).

        The same handler can be registered for multiple event types.
        Registering the same (event_type, handler) pair twice is a no-op.
        """
        for h, _ in self._handlers[event_type]:
            if h is handler:
                return          # already registered
        self._handlers[event_type].append((handler, False))

    def subscribe_once(self, event_type: str, handler: Handler) -> None:
        """Register a handler that auto-unsubscribes after first delivery."""
        self._handlers[event_type].append((handler, True))

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        """Remove a previously registered handler.  Silent if not found."""
        self._handlers[event_type] = [
            (h, o) for h, o in self._handlers[event_type] if h is not handler
        ]

    # ── Publish ───────────────────────────────────────────────────────────────

    async def publish(self, event: Event) -> None:
        """
        Deliver ``event`` to all matching subscribers.

        Delivery order:
          1. Exact-match handlers for ``event.type``
          2. Wildcard handlers subscribed to ``"*"``

        A handler that raises is logged and skipped; other handlers still run.
        One-shot handlers are removed after delivery.
        """
        # Record in history
        self._history.append(event)
        if len(self._history) > self._history_max:
            self._history.pop(0)

        targets = list(self._handlers.get(event.type, []))
        wildcards = [
            entry for entry in self._handlers.get("*", [])
            if entry not in targets
        ]

        to_remove_exact: list[tuple[Handler, bool]] = []
        to_remove_wild:  list[tuple[Handler, bool]] = []

        for entry in targets:
            handler, one_shot = entry
            await self._call(handler, event)
            if one_shot:
                to_remove_exact.append(entry)

        for entry in wildcards:
            handler, one_shot = entry
            await self._call(handler, event)
            if one_shot:
                to_remove_wild.append(entry)

        for entry in to_remove_exact:
            try:
                self._handlers[event.type].remove(entry)
            except ValueError:
                pass
        for entry in to_remove_wild:
            try:
                self._handlers["*"].remove(entry)
            except ValueError:
                pass

    def publish_nowait(self, event: Event) -> None:
        """
        Schedule ``event`` delivery without awaiting.

        Use from synchronous code.  The event is dispatched on the running
        event loop; handlers execute on the next loop iteration.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event), name=f"event:{event.type}")
        except RuntimeError:
            # No running loop — log and drop.
            logger.warning("event_bus: no running loop — dropping %s", event.type)

    # ── Introspection ─────────────────────────────────────────────────────────

    def recent(self, n: int = 20) -> List[Event]:
        """Return the last ``n`` published events (oldest first)."""
        return list(self._history[-n:])

    def handler_count(self, event_type: str = "*") -> int:
        """Return the number of registered handlers for ``event_type``."""
        if event_type == "*":
            return sum(len(v) for v in self._handlers.values())
        return len(self._handlers.get(event_type, []))

    def clear(self) -> None:
        """Remove all handlers and history.  Mainly for testing."""
        self._handlers.clear()
        self._history.clear()

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    async def _call(handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "event_bus: handler %r raised on event %r",
                getattr(handler, "__name__", handler),
                event.type,
            )
