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

# hashlib is used below for suggestion-key hashing and workspace_id

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


# ---------------------------------------------------------------------------
# Workspace analysis git-HEAD tracking — skip full scan when HEAD unchanged.
# Stored in-memory only (per-process); survives tab refreshes within a session
# but resets on server restart (that's intentional — restart = fresh scan).
# ---------------------------------------------------------------------------

_git_head_cache: dict[str, tuple[str, str]] = {}  # workspace → (git_head, git_branch)


def update_workspace_git_head(
    workspace: str, git_head: str, git_branch: str, dirty_count: int = 0
) -> None:
    """Record the git HEAD + branch + dirty-file count from the most recent scan."""
    _git_head_cache[workspace] = (git_head, git_branch, dirty_count)


def get_workspace_git_head(workspace: str) -> "tuple[str, str, int] | None":
    """Return (git_head, git_branch, dirty_count) from the last scan, or None."""
    entry = _git_head_cache.get(workspace)
    if entry is None:
        return None
    # Back-compat: old entries stored only (head, branch)
    if len(entry) == 2:
        return entry[0], entry[1], 0  # type: ignore[return-value]
    return entry  # type: ignore[return-value]


def invalidate_workspace_cache(workspace: str) -> None:
    """Force a fresh scan on the next connection (Cache Invalidation Rule #4).

    Clears both the analysis payload cache and the git-HEAD record so that
    _send_workspace_analysis() finds no valid cache and runs a full scan.
    """
    _workspace_cache.pop(workspace, None)
    _git_head_cache.pop(workspace, None)


# ---------------------------------------------------------------------------
# Idle-suggestion repeat detection — persistent so it survives tab reconnects.
# Prevents the same "No tests for hi.py" item repeating every 45 s.
# ---------------------------------------------------------------------------

_REPORTED_NS = "reported_suggestions"
_REPORTED_TTL_SECS = 86400.0  # 24 hours


def _suggestion_key(suggestion: dict) -> str:
    """Stable, short hash key: title + file path."""
    raw = f"{suggestion.get('title', '')}:{suggestion.get('file', '')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def filter_unreported_suggestions(workspace: str, suggestions: list[dict]) -> list[dict]:
    """Return only suggestions that have NOT been reported to the user in the last 24 h."""
    store = get_storage()
    ns_key = workspace_id(workspace)
    reported: dict[str, float] = store.get_or_default(_REPORTED_NS, ns_key, {})
    cutoff = time.time() - _REPORTED_TTL_SECS
    return [s for s in suggestions if reported.get(_suggestion_key(s), 0) <= cutoff]


def mark_suggestions_reported(workspace: str, suggestions: list[dict]) -> None:
    """Record that these suggestions were just broadcast to the user."""
    store = get_storage()
    ns_key = workspace_id(workspace)
    reported: dict[str, float] = store.get_or_default(_REPORTED_NS, ns_key, {})
    now = time.time()
    cutoff = now - _REPORTED_TTL_SECS
    for s in suggestions:
        reported[_suggestion_key(s)] = now
    # Prune entries older than the TTL to keep storage tidy
    reported = {k: v for k, v in reported.items() if v > cutoff}
    store.set(_REPORTED_NS, ns_key, reported)


# ---------------------------------------------------------------------------
# Last-greeting tracker — detect reconnects within a session window so MARK
# doesn't re-introduce itself or repeat the workspace opening every tab refresh.
# ---------------------------------------------------------------------------

_GREETING_NS = "last_greeting"
RECONNECT_WINDOW_SECS = 1800.0   # 30 minutes


def get_last_greeting_age(workspace: str) -> float:
    """Seconds since MARK last greeted the user on this workspace (∞ if never)."""
    store = get_storage()
    ts = store.get_or_default(_GREETING_NS, workspace_id(workspace), 0.0)
    if not ts:
        return float("inf")
    return time.time() - float(ts)


def record_greeting(workspace: str) -> None:
    """Record that MARK just delivered an opening greeting for this workspace."""
    store = get_storage()
    store.set(_GREETING_NS, workspace_id(workspace), time.time())


# ---------------------------------------------------------------------------
# Memory Hierarchy — four distinct tiers with separate TTLs and purposes.
# These should never be mixed or substituted for one another.
#
#  Tier 1 – SHORT-TERM CONVERSATION MEMORY
#    What it is: the last N conversational turns in this session.
#    Scope:      per workspace, volatile.
#    TTL:        lives for the life of the conversation; capped at _MAX_TURNS.
#    Used for:   injecting recent context into every chat reply so MARK
#                doesn't repeat itself or forget what was just said.
#    Access:     recent_turns(workspace, limit=8)
#
#  Tier 2 – PROJECT MEMORY
#    What it is: the workspace analysis snapshot (files, frameworks, TODOs,
#                git branch, tech stack, etc.).
#    Scope:      per workspace, in-memory only.
#    TTL:        300 s or until git HEAD / branch / dirty-count changes.
#    Used for:   injecting project context into chat replies and opening
#                messages without re-running the full filesystem scan.
#    Access:     get_cached_workspace_context(workspace)
#
#  Tier 3 – LONG-TERM EXECUTIVE MEMORY
#    What it is: the full persisted conversation history up to _MAX_TURNS.
#    Scope:      per workspace, durable (survives server restarts).
#    TTL:        permanent until explicitly cleared.
#    Used for:   understanding the user's patterns, past decisions, and
#                evolving project goals across sessions.
#    Access:     get_history(workspace)
#
#  Tier 4 – REPOSITORY AWARENESS CACHE
#    What it is: the git HEAD commit + branch + dirty-file count from the
#                most recent workspace scan.
#    Scope:      per workspace, in-memory only.
#    TTL:        invalidated on git commit, branch change, or dirty-count
#                change.  Resets on server restart (fresh scan on startup).
#    Used for:   deciding whether to skip the expensive _analyze_workspace()
#                call on every tab reconnect.
#    Access:     get_workspace_git_head(workspace) /
#                update_workspace_git_head(workspace, head, branch, dirty)
# ---------------------------------------------------------------------------

MEMORY_TIERS = {
    "short_term":   "Last 8 turns — recent conversation context",
    "project":      "Workspace analysis snapshot — 300 s TTL, git-HEAD invalidated",
    "long_term":    "Full conversation history — persistent, up to 200 turns",
    "repo_cache":   "Git HEAD + branch + dirty count — in-memory, commit-invalidated",
}


def memory_hierarchy_status(workspace: str) -> dict:
    """Return a snapshot of what each memory tier currently holds for *workspace*."""
    turns = get_history(workspace)
    ctx   = get_cached_workspace_context(workspace)
    head  = get_workspace_git_head(workspace)
    store = get_storage()
    last_greeting_ts = store.get_or_default(_GREETING_NS, workspace_id(workspace), 0.0)
    age = (time.time() - float(last_greeting_ts)) if last_greeting_ts else None
    return {
        "short_term_turns":   min(len(turns), 8),
        "long_term_turns":    len(turns),
        "project_cache_hit":  ctx is not None,
        "repo_cache_head":    head[0][:8] if head else None,
        "repo_cache_branch":  head[1] if head else None,
        "last_greeting_age":  round(age, 1) if age is not None else None,
    }
