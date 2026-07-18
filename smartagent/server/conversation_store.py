"""
conversation_store.py — persisted per-workspace conversation history, plus
a short-lived cache of the workspace analysis snapshot.

Built on smartagent.storage.factory.get_storage() so it works against
whatever backend is active (local JSON today, MongoDB once B5/B6 land)
with zero changes here when the storage provider is swapped.

This is the fix for MARK's chat calls being stateless: _do_chat() in
api.py used to send only the system prompt + the current message, with no
memory of earlier turns and no workspace context beyond a one-time
snapshot computed at connect time. See docs/mark-operating-system.md and
the B3 plan note for the live symptom this addresses (near-duplicate
openers, no continuity across turns).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from smartagent.storage.factory import get_storage

_CHAT_NAMESPACE = "chat"
_MAX_TURNS = 200


def workspace_id(workspace: str) -> str:
    """Stable, storage-safe key for a workspace path."""
    return hashlib.sha256(workspace.encode("utf-8")).hexdigest()[:16]


def get_history(workspace: str) -> list[dict[str, str]]:
    """Full persisted turn list for *workspace*, oldest first."""
    store = get_storage()
    return store.get_or_default(_CHAT_NAMESPACE, workspace_id(workspace), [])


def append_turn(workspace: str, role: str, content: str) -> None:
    """Append one {role, content} turn, trimmed to the last _MAX_TURNS."""
    store = get_storage()
    key = workspace_id(workspace)
    history = store.get_or_default(_CHAT_NAMESPACE, key, [])
    history.append({"role": role, "content": content})
    if len(history) > _MAX_TURNS:
        history = history[-_MAX_TURNS:]
    store.set(_CHAT_NAMESPACE, key, history)


def recent_turns(workspace: str, limit: int = 8) -> list[dict[str, str]]:
    """Last *limit* turns, suitable for inserting into a chat messages list."""
    history = get_history(workspace)
    return history[-limit:] if limit > 0 else []


# ---------------------------------------------------------------------------
# Workspace-analysis cache — avoid recomputing a full analyze_workspace()
# scan on every chat turn; the opening-message flow already computes it once
# per connection, this just makes that result reusable for a short window.
# ---------------------------------------------------------------------------

_WORKSPACE_CACHE_TTL = 300.0  # seconds
_workspace_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def cache_workspace_context(workspace: str, payload: dict[str, Any]) -> None:
    _workspace_cache[workspace] = (time.monotonic(), payload)


def get_cached_workspace_context(workspace: str) -> dict[str, Any] | None:
    entry = _workspace_cache.get(workspace)
    if entry is None:
        return None
    cached_at, payload = entry
    if time.monotonic() - cached_at > _WORKSPACE_CACHE_TTL:
        return None
    return payload
