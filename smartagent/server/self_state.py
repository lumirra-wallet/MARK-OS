"""
smartagent.server.self_state — reads and updates MARK's real self-state.

Used to hold its own standalone ExecutiveController — a second, separate
self-model living next to whichever SmartAgent happened to handle a given
request. That was already wrong (two selves instead of one), but it also
sat on top of a deeper problem: SmartAgent itself was being rebuilt from
scratch on every /run call, so nothing was actually persistent underneath
either copy.

Now that smartagent.server.api keeps ONE SmartAgent for the life of the
server process (see api.py's _get_mark_agent), there is only one
self-model to report on: agent.mind. This module is a thin, stateless
read/write helper over it — not a second copy of it.
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
    return {
        "identity": model.name,
        "owner": model.owner,
        "mode": model.state,
        "state": model.state,
        "current_activity": model.current_activity,
        "active_tasks": 0 if model.state == "idle" else 1,
        "model": active_model or "none",
        "memory": "available",
        "voice": "disabled",  # honest — voice hasn't been built
        "confidence": model.confidence,
        "health": model.health_score,
    }


def idle_snapshot() -> dict[str, Any]:
    """MARK hasn't handled a request yet this process, so no agent exists
    to report on — distinct from a real self-model snapshot that exists
    but happens to be idle; this one is honestly "not started yet"."""
    return {
        "identity": "MARK", "owner": "", "mode": "idle", "state": "idle",
        "current_activity": "not started", "active_tasks": 0,
        "model": "none", "memory": "available", "voice": "disabled",
        "confidence": 0.0, "health": 1.0,
    }
