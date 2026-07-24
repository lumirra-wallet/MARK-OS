"""
api_memory.py — Elena's memory and conversation history REST API.

Exposes what Elena has learned across three memory layers:
  - Episodic: autobiographical events (conversations, decisions, episodes)
  - Semantic: world facts learned from conversations and web searches
  - Owner: the persistent model of who the owner is and what they value

Also exposes the persistent conversation history so the user can see
and review what Elena remembers of past exchanges.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])


# ── Summary endpoint ──────────────────────────────────────────────────────────

@router.get("/summary")
async def memory_summary() -> JSONResponse:
    """
    Return a high-level summary of Elena's memory state:
      - episodic_today: events stored today
      - semantic_total: total persistent facts
      - owner_attributes: owner profile entries
      - recent_facts: the 10 most-recent semantic facts
      - web_searches: facts learned from web searches
    """
    result: dict[str, Any] = {
        "episodic_today":   0,
        "semantic_total":   0,
        "owner_attributes": 0,
        "recent_facts":     [],
        "web_searches":     0,
    }

    try:
        from smartagent.memory.layers.episodic import EpisodicMemory
        result["episodic_today"] = EpisodicMemory().count_today()
    except Exception as exc:
        logger.debug("memory_summary: episodic failed: %s", exc)

    try:
        from smartagent.memory.layers.semantic import SemanticMemory
        sem = SemanticMemory()
        result["semantic_total"] = sem.count()
        # Recent facts for display
        all_facts = sem._load()
        result["recent_facts"] = [
            e.get("fact", "")[:120]
            for e in reversed(all_facts[-10:])
            if e.get("fact")
        ]
        result["web_searches"] = sum(
            1 for e in all_facts if "web_search" in e.get("tags", [])
        )
    except Exception as exc:
        logger.debug("memory_summary: semantic failed: %s", exc)

    try:
        from smartagent.memory.layers.owner import OwnerMemory
        result["owner_attributes"] = OwnerMemory().count()
    except Exception as exc:
        logger.debug("memory_summary: owner failed: %s", exc)

    return JSONResponse(result)


# ── Owner profile endpoint ─────────────────────────────────────────────────────

@router.get("/owner")
async def owner_profile() -> JSONResponse:
    """Return Elena's full model of the owner."""
    try:
        from smartagent.memory.layers.owner import OwnerMemory
        mem = OwnerMemory()
        profile = mem._load()
        return JSONResponse(profile)
    except Exception as exc:
        logger.warning("owner_profile: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Conversation history endpoint ─────────────────────────────────────────────

@router.get("/conversations")
async def conversation_history(workspace: str = "", limit: int = 50) -> JSONResponse:
    """
    Return the recent conversation history for a workspace.

    Query params:
      workspace: path to the workspace (defaults to '' = global)
      limit:     max turns to return (default 50, max 200)
    """
    limit = max(1, min(limit, 200))
    try:
        from smartagent.server import conversation_store
        turns = conversation_store.get_history(workspace)
        return JSONResponse({
            "workspace":   workspace,
            "total_turns": len(turns),
            "turns":       turns[-limit:],
        })
    except Exception as exc:
        logger.warning("conversation_history: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Memory clear (conversations only — never erases episodic or semantic) ──────

@router.delete("/conversations")
async def clear_conversations(workspace: str = "") -> JSONResponse:
    """
    Clear the short-term conversation history for a workspace.
    Does NOT erase episodic, semantic, or owner memory — only the
    per-workspace chat log used for recent-context injection.
    """
    try:
        from smartagent.storage.factory import get_storage
        from smartagent.server.conversation_store import workspace_id, _CHAT_NAMESPACE
        store = get_storage()
        store.set(_CHAT_NAMESPACE, workspace_id(workspace), [])
        return JSONResponse({"cleared": True, "workspace": workspace})
    except Exception as exc:
        logger.warning("clear_conversations: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Episodic events endpoint ──────────────────────────────────────────────────

@router.get("/episodes")
async def recent_episodes(n: int = 20) -> JSONResponse:
    """Return the n most recent episodic events, newest first."""
    n = max(1, min(n, 100))
    try:
        from smartagent.memory.layers.episodic import EpisodicMemory
        episodes = EpisodicMemory().recent(n)
        return JSONResponse({"episodes": episodes, "count": len(episodes)})
    except Exception as exc:
        logger.warning("recent_episodes: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Semantic facts endpoint ────────────────────────────────────────────────────

@router.get("/facts")
async def semantic_facts(query: str = "", limit: int = 20) -> JSONResponse:
    """
    Return semantic facts. If query is provided, returns the most relevant
    facts; otherwise returns the most recent facts.
    """
    limit = max(1, min(limit, 100))
    try:
        from smartagent.memory.layers.semantic import SemanticMemory
        mem = SemanticMemory()
        if query:
            facts = mem.relevant(query, n=limit)
        else:
            all_f = mem._load()
            facts = list(reversed(all_f[-limit:]))
        return JSONResponse({"facts": facts, "count": len(facts)})
    except Exception as exc:
        logger.warning("semantic_facts: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)
