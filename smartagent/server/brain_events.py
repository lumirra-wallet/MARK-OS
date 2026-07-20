"""
smartagent/server/brain_events.py

Brain Event Broadcaster — the single channel through which MARK's cognitive
events reach the dashboard.

The contract: every state visible in the dashboard must originate here.
The UI is an observer, never an author, of MARK's state.

Events:
  thinking_started    — MARK began reasoning (with the goal)
  thinking_finished   — reasoning complete (with latency_ms)
  memory_written      — a real memory was persisted (layer + summary)
  knowledge_created   — a new concept was committed to the knowledge graph
  emotion_changed     — MARK's emotional state changed (state + reason)
  voice_started       — VAD detected speech start
  voice_interrupted   — user spoke while MARK was speaking; inference cancelled
  voice_finished      — utterance complete (transcript)
  cognitive_event     — a pipeline step for the Cognitive Timeline
  reflection_complete — idle self-reflection cycle finished
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def emit(event_name: str, data: dict[str, Any]) -> None:
    """Broadcast one named brain event to all connected dashboard clients."""
    try:
        from smartagent.server.websocket import connection_manager
        await connection_manager.broadcast({
            "type":      "event",
            "name":      "BrainEvent",
            "payload":   {"event": event_name, **data},
            "timestamp": _now_iso(),
        })
    except Exception as exc:
        logger.debug("brain_events.emit %r failed: %s", event_name, exc)


async def thinking_started(goal: str) -> None:
    await emit("thinking_started", {"goal": goal[:120]})
    await cognitive_event("reasoning", goal[:80])


async def thinking_finished(latency_ms: int) -> None:
    await emit("thinking_finished", {"latency_ms": latency_ms})
    await cognitive_event("decision_made", f"{latency_ms}ms")


async def memory_written(layer: str, summary: str) -> None:
    """Called whenever a real memory is persisted — episodic, semantic, or owner."""
    await emit("memory_written", {"layer": layer, "summary": summary[:100]})
    await cognitive_event("memory_retrieved", summary[:60])


async def knowledge_created(concept: str) -> None:
    await emit("knowledge_created", {"concept": concept[:80]})
    await cognitive_event("knowledge_matched", concept[:60])


async def emotion_changed(state: str, reason: str = "") -> None:
    await emit("emotion_changed", {"state": state, "reason": reason[:80]})


async def voice_started() -> None:
    await emit("voice_started", {})
    await cognitive_event("listening", "")


async def voice_interrupted() -> None:
    await emit("voice_interrupted", {})
    await cognitive_event("voice_interrupted", "inference cancelled")


async def voice_finished(transcript: str) -> None:
    await emit("voice_finished", {"transcript": transcript[:200]})


async def cognitive_event(step: str, detail: str = "") -> None:
    """A single observable pipeline step for the Cognitive Timeline."""
    await emit("cognitive_event", {"step": step, "detail": detail})


async def reflection_complete(lesson: str = "", concepts_added: int = 0) -> None:
    await emit("reflection_complete", {
        "lesson": lesson[:200],
        "concepts_added": concepts_added,
    })
    await cognitive_event("reflection_complete", lesson[:60] if lesson else "reflection done")
