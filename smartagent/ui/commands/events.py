"""
Events command: events.

Shows recent events from the shared EventBus without adding any new
pub/sub infrastructure — it reads ``agent.events.history()`` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

_MAX_EVENTS = 20


def handle_events(agent: "SmartAgent", args: list[str]) -> str:
    """Show the most recent EventBus events (up to 20)."""
    try:
        history = agent.events.history()
        if not history:
            return "No events recorded yet."

        recent = history[-_MAX_EVENTS:]
        lines = [
            f"Recent events (showing {len(recent)} of {len(history)} total)",
            "",
        ]
        for ev in recent:
            ts = ev.timestamp if hasattr(ev, "timestamp") else "?"
            name = ev.name if hasattr(ev, "name") else str(ev)
            # Show a compact payload preview (first 60 chars).
            payload = ev.payload if hasattr(ev, "payload") else {}
            payload_str = ""
            if payload:
                raw = str(payload)
                payload_str = "  " + ((raw[:60] + "…") if len(raw) > 60 else raw)
            lines.append(f"  [{ts}] {name}")
            if payload_str:
                lines.append(payload_str)
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Could not retrieve events: {exc}"


def register(router: CommandRouter) -> None:
    """Register the events command with *router*."""
    router.register("events", handle_events, "show recent EventBus events", "EVENTS", 0)
