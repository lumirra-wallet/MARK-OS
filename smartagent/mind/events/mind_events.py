"""
Mind event names — Milestone 6, Part 10.

The Mind does not run its own event bus; it publishes onto the same
`smartagent.brain.events.EventBus` every other subsystem uses (Milestone 2's
shared-bus design). The well-known Mind event *names* themselves are added
directly to `Events` in `smartagent/brain/events.py` (under a "Mind"
section), exactly like Milestone 5 added its `MODEL_*` constants — this
module just re-exports them plus a small helper so Mind engines don't each
need to know `EventBus` might be `None`.
"""

from __future__ import annotations

from typing import Any

from smartagent.brain.events import Events, EventBus

__all__ = ["Events", "publish_mind_event"]


def publish_mind_event(event_bus: EventBus | None, event_name: str, **payload: Any) -> None:
    """
    Publish `event_name` with `payload` onto `event_bus`, if one was given.

    Every Mind engine accepts an optional `EventBus` (consistent with
    `ToolEngine`/`ModelManager`) so it stays fully usable — and testable —
    standalone, without a `SmartAgent`. Centralizing the `None` guard here
    keeps every call site a one-liner.
    """
    if event_bus is None:
        return
    event_bus.publish(event_name, **payload)
