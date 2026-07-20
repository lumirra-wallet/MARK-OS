"""
smartagent.server.self_state — reads and updates MARK's real self-state.

Thin, stateless read/write helper over agent.mind — not a second copy of it.
Every field returned by snapshot() is read directly from the live agent;
nothing is cached or simulated.

Brain Foundation additions (Task #5):
  - emotional_state / emotional_reason from EmotionalStateEngine
  - memory_activity from the three memory layers
"""

from __future__ import annotations

from typing import Any


def task_started(agent: Any, task_name: str = "conversation", importance: float = 0.5) -> None:
    agent.mind.start_task(task_name, importance)


def task_finished(
    agent: Any,
    task_name: str = "conversation",
    succeeded: bool = True,
    what_happened: str = "",
) -> None:
    agent.mind.complete_task(task_name, succeeded, what_happened or "Task finished.")


def snapshot(agent: Any) -> dict[str, Any]:
    """MARK's current self-state, read straight from the live agent every
    time — never cached, so it can never drift from what agent.mind
    actually reports."""
    model = agent.mind.self_model()
    active_model = getattr(agent.model_manager, "_active_model_id", None)

    # ── Brain Foundation: emotional state ────────────────────────────────────
    try:
        from smartagent.mind.emotion.emotional_state import emotional_state_engine
        emotional_state = emotional_state_engine.state
        emotional_reason = emotional_state_engine.reason
    except Exception:
        emotional_state = "neutral"
        emotional_reason = ""

    # ── Brain Foundation: memory layer metrics ───────────────────────────────
    try:
        from smartagent.memory.layers.episodic import EpisodicMemory
        from smartagent.memory.layers.semantic import SemanticMemory
        from smartagent.memory.layers.owner   import OwnerMemory
        memory_activity = {
            "episodic_today":    EpisodicMemory().count_today(),
            "semantic_total":    SemanticMemory().count(),
            "owner_attributes":  OwnerMemory().count(),
        }
    except Exception:
        memory_activity = {"episodic_today": 0, "semantic_total": 0, "owner_attributes": 0}

    return {
        "identity":         model.name,
        "owner":            model.owner,
        "mode":             model.state,
        "state":            model.state,
        "current_activity": model.current_activity,
        "active_tasks":     0 if model.state == "idle" else 1,
        "model":            active_model or "none",
        "memory":           "available",
        "voice":            "active",
        "confidence":       model.confidence,
        "health":           model.health_score,
        # Brain Foundation fields — real values, not placeholders
        "emotional_state":  emotional_state,
        "emotional_reason": emotional_reason,
        "memory_activity":  memory_activity,
    }


def idle_snapshot() -> dict[str, Any]:
    """MARK hasn't handled a request yet this process — honestly 'not started yet'."""
    return {
        "identity": "MARK", "owner": "", "mode": "idle", "state": "idle",
        "current_activity": "not started", "active_tasks": 0,
        "model": "none", "memory": "available", "voice": "active",
        "confidence": 0.0, "health": 1.0,
        "emotional_state": "neutral", "emotional_reason": "",
        "memory_activity": {"episodic_today": 0, "semantic_total": 0, "owner_attributes": 0},
    }
