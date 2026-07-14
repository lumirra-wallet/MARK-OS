"""
Memory commands: remember, recall, search-memory.

All operations go through ``agent.memory`` (MemoryManager).  No second
memory implementation is created here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_remember(agent: "SmartAgent", args: list[str]) -> str:
    """
    Persist a new memory entry.

    Usage: ``remember <content>``
    """
    if not args:
        return "Usage: remember <content>"
    content = " ".join(args)
    try:
        entry = agent.memory.remember(content)
        return f"Remembered [{entry.id[:8]}]: {content}"
    except Exception as exc:
        return f"[error] Could not save memory: {exc}"


def handle_recall(agent: "SmartAgent", args: list[str]) -> str:
    """
    List the most recent memories (up to 10).

    Usage: ``recall``
    """
    try:
        entries = agent.memory.search("", limit=10)
        if not entries:
            return "No memories found."
        lines = ["Recent memories:", ""]
        for i, e in enumerate(entries, 1):
            preview = (e.content[:72] + "…") if len(e.content) > 72 else e.content
            lines.append(f"  {i:>2}. [{e.id[:8]}] {preview}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Could not retrieve memories: {exc}"


def handle_search_memory(agent: "SmartAgent", args: list[str]) -> str:
    """
    Search memories for a query string.

    Usage: ``search-memory <query>``
    """
    if not args:
        return "Usage: search-memory <query>"
    query = " ".join(args)
    try:
        entries = agent.memory.search(query, limit=10)
        if not entries:
            return f'No memories matching "{query}".'
        lines = [f'Memory search: "{query}"', ""]
        for i, e in enumerate(entries, 1):
            preview = (e.content[:72] + "…") if len(e.content) > 72 else e.content
            lines.append(f"  {i:>2}. [{e.id[:8]}] {preview}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Memory search failed: {exc}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(router: CommandRouter) -> None:
    """Register all memory commands with *router*."""
    router.register("remember", handle_remember, "save a new memory", "MEMORY", 0)
    router.register("recall", handle_recall, "list recent memories", "MEMORY", 1)
    router.register("search-memory", handle_search_memory, "search memories", "MEMORY", 2)
