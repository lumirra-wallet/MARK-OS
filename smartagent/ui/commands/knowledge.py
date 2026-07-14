"""
Knowledge commands: knowledge, graph, inbox, approve, reject.

All operations go through ``agent.knowledge`` (KnowledgeManager).
No direct sub-engine imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pending_items(agent: "SmartAgent") -> list:
    """Return pending inbox items as a list, empty list on any failure."""
    try:
        return agent.knowledge.list_pending_inbox()
    except Exception:
        return []


def _resolve_item_id(agent: "SmartAgent", token: str) -> str | None:
    """
    Resolve *token* to an inbox item id.

    *token* can be a 1-based index (e.g. ``"1"``) or a raw item id.
    Returns ``None`` if nothing matches.
    """
    items = _pending_items(agent)

    # Try as a 1-based index first.
    if token.isdigit():
        idx = int(token) - 1
        if 0 <= idx < len(items):
            return items[idx].id
        return None

    # Fall back to treating as a raw id.
    ids = {item.id for item in items}
    return token if token in ids else None


# ---------------------------------------------------------------------------
# Sub-command dispatch for `knowledge …`
# ---------------------------------------------------------------------------


def _knowledge_add(agent: "SmartAgent", args: list[str]) -> str:
    if not args:
        return "Usage: knowledge add <title>"
    title = " ".join(args)
    try:
        item = agent.knowledge.propose_concept(title=title, description="")
        return (
            f"Concept proposed and added to inbox.\n"
            f"  Inbox ID : {item.id[:8]}…\n"
            f"  Title    : {title}\n"
            f"  Status   : pending\n"
            f'Type "inbox" to review or "approve <number>" to confirm.'
        )
    except Exception as exc:
        return f"[error] Could not propose concept: {exc}"


def _knowledge_search(agent: "SmartAgent", args: list[str]) -> str:
    if not args:
        return "Usage: knowledge search <query>"
    query = " ".join(args)
    try:
        results = agent.knowledge.search(query, limit=10)
        if not results:
            return f'No concepts found matching "{query}".'
        lines = [f'Knowledge search: "{query}"', ""]
        for i, r in enumerate(results, 1):
            c = r.concept
            conf = f"{c.confidence:.2f}"
            summary = (c.summary or c.description or "")[:60]
            if len(summary) == 60:
                summary += "…"
            lines.append(f"  {i:>2}. [{conf}] {c.title}")
            if summary:
                lines.append(f"       {summary}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Knowledge search failed: {exc}"


def _knowledge_graph_concept(agent: "SmartAgent", args: list[str]) -> str:
    if not args:
        return "Usage: knowledge graph <title>"
    query = " ".join(args)
    try:
        results = agent.knowledge.search(query, limit=1)
        if not results:
            return f'No concept found matching "{query}".'
        concept = results[0].concept
        # Collect relationships from the graph.
        rels = agent.knowledge.query.find_related(concept.id)
        lines = [f"Knowledge graph: {concept.title}", ""]
        if not rels:
            lines.append("  (no relationships)")
        else:
            for r in rels[:15]:
                arrow = "──►" if r.direction in ("forward", "bidirectional") else "◄──"
                # Resolve target concept title.
                target_id = r.to_concept_id if r.from_concept_id == concept.id else r.from_concept_id
                try:
                    target = agent.knowledge._storage.load_concept(target_id)
                    target_title = target.title if target else target_id[:8]
                except Exception:
                    target_title = target_id[:8]
                lines.append(f"  ─({r.relation_type.value}){arrow} {target_title}")
            if len(rels) > 15:
                lines.append(f"  … and {len(rels) - 15} more")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Graph lookup failed: {exc}"


def _knowledge_stats(agent: "SmartAgent", args: list[str]) -> str:
    try:
        s = agent.knowledge.stats()
        lines = [
            "Knowledge statistics",
            "",
            f"  Concepts      : {s.total_concepts}",
            f"  Relationships : {s.total_relationships}",
            f"  Sources       : {s.total_sources}",
            f"  Evidence      : {s.total_evidence}",
            f"  Categories    : {s.total_categories}",
            f"  Avg confidence: {s.average_confidence:.2f}",
            f"  High confidence (≥0.8): {s.high_confidence_concepts}",
            f"  Low confidence (<0.5) : {s.low_confidence_concepts}",
            f"  Verified      : {s.verified_concepts}",
            f"  Unverified    : {s.unverified_concepts}",
            f"  Contradicted  : {s.contradicted_concepts}",
            f"  Inbox pending : {s.pending_inbox_items}",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Stats unavailable: {exc}"


_KNOWLEDGE_SUBCOMMANDS = {
    "add": _knowledge_add,
    "search": _knowledge_search,
    "graph": _knowledge_graph_concept,
    "stats": _knowledge_stats,
}


# ---------------------------------------------------------------------------
# Top-level handlers
# ---------------------------------------------------------------------------


def handle_knowledge(agent: "SmartAgent", args: list[str]) -> str:
    """
    Dispatch knowledge sub-commands.

    Usage::

        knowledge add <title>
        knowledge search <query>
        knowledge graph <title>
        knowledge stats
    """
    if not args:
        return (
            "Usage:\n"
            "  knowledge add <title>    — propose a new concept\n"
            "  knowledge search <query> — search concepts\n"
            "  knowledge graph <title>  — show concept relationships\n"
            "  knowledge stats          — show statistics"
        )
    sub = args[0].lower()
    handler = _KNOWLEDGE_SUBCOMMANDS.get(sub)
    if handler is None:
        return f'Unknown knowledge sub-command: "{sub}"'
    return handler(agent, args[1:])


def handle_inbox(agent: "SmartAgent", args: list[str]) -> str:
    """List pending knowledge inbox items."""
    try:
        items = _pending_items(agent)
        if not items:
            return "Knowledge inbox is empty."
        lines = [f"Knowledge inbox ({len(items)} pending)", ""]
        for i, item in enumerate(items, 1):
            status = item.status.value if hasattr(item.status, "value") else str(item.status)
            conf = f"{item.confidence:.2f}" if hasattr(item, "confidence") else "?"
            lines.append(
                f"  {i:>2}. [{item.id[:8]}] [{status}] [{conf}] {item.concept.title}"
            )
        lines.append("")
        lines.append('Type "approve <number>" or "reject <number>".')
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Could not list inbox: {exc}"


def handle_approve(agent: "SmartAgent", args: list[str]) -> str:
    """
    Approve an inbox item by number or id.

    Usage: ``approve <number>``
    """
    if not args:
        return "Usage: approve <number>"
    item_id = _resolve_item_id(agent, args[0])
    if item_id is None:
        return f'No pending inbox item matching "{args[0]}".'
    try:
        concept = agent.knowledge.approve_concept(item_id)
        return f"Approved: {concept.title} [{concept.id[:8]}] added to knowledge graph."
    except Exception as exc:
        return f"[error] Approval failed: {exc}"


def handle_reject(agent: "SmartAgent", args: list[str]) -> str:
    """
    Reject an inbox item by number or id.

    Usage: ``reject <number>``
    """
    if not args:
        return "Usage: reject <number>"
    item_id = _resolve_item_id(agent, args[0])
    if item_id is None:
        return f'No pending inbox item matching "{args[0]}".'
    notes = " ".join(args[1:]) or "Rejected via console."
    try:
        agent.knowledge.reject_concept(item_id, notes=notes)
        return f"Rejected inbox item {args[0]}."
    except Exception as exc:
        return f"[error] Rejection failed: {exc}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(router: CommandRouter) -> None:
    """Register all knowledge commands with *router*."""
    router.register("knowledge", handle_knowledge, "knowledge sub-commands (add/search/graph/stats)", "KNOWLEDGE", 0)
    router.register("graph", lambda a, args: _knowledge_graph_concept(a, args), "show concept relationships", "KNOWLEDGE", 1)
    router.register("inbox", handle_inbox, "list pending knowledge inbox items", "KNOWLEDGE", 2)
    router.register("approve", handle_approve, "approve an inbox item", "KNOWLEDGE", 3)
    router.register("reject", handle_reject, "reject an inbox item", "KNOWLEDGE", 4)
