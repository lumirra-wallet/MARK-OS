"""
smartagent/server/learning_pipeline.py

Post-conversation learning pipeline.

After every completed interaction, this module:
  1. Extracts simple factual claims from the conversation
  2. Detects owner signals and updates OwnerMemory
  3. Proposes new concepts to the KnowledgeManager
  4. Stores an episodic memory entry
  5. Returns a summary of what was learned for broadcast

This runs in a background thread (asyncio.to_thread) so it never delays
the response to the user.

The contract: only real knowledge is stored. No fabrication. If extraction
yields nothing, nothing is written.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Simple patterns for extracting factual claims from a conversation turn.
# These are intentionally conservative — better to miss a fact than to store
# a hallucination. Real concept extraction would use an NLP model; this uses
# pattern matching as a reliable, zero-latency approximation.

_FACT_PATTERNS = [
    # "X is a Y" / "X is used for Y"
    re.compile(r"([A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)?)\s+is\s+(?:a\s+|an\s+|used\s+(?:for|to)\s+)(.{10,80})", re.I),
    # "X stores/handles/manages Y"
    re.compile(r"([A-Z][a-zA-Z0-9_]+)\s+(?:stores|handles|manages|processes|returns|provides)\s+(.{10,80})", re.I),
]

# Max characters for text passed to the knowledge manager
_MAX_DESC = 200


def run(
    goal: str,
    reply: str,
    succeeded: bool,
    emotional_state: str,
    knowledge_manager: Any | None,
) -> dict[str, Any]:
    """
    Extract and persist everything learnable from one completed conversation turn.

    Returns a summary dict with:
      episodic_stored: bool
      owner_signals:   list of detected owner preference strings
      concepts_proposed: list of concept titles proposed to KnowledgeManager
    """
    from smartagent.memory.layers.episodic import EpisodicMemory
    from smartagent.memory.layers.owner import OwnerMemory

    episodic = EpisodicMemory()
    owner = OwnerMemory()

    # ── 1. Episodic memory — every interaction gets stored ────────────────────
    summary = _summarize(goal, reply, succeeded)
    episodic.store(
        summary=summary,
        goal=goal,
        succeeded=succeeded,
        emotional_state=emotional_state,
        tags=_extract_tags(goal),
    )
    episodic_stored = True

    # ── 2. Owner signals ──────────────────────────────────────────────────────
    owner_signals = owner.extract_and_update(goal)

    # ── 3. Knowledge — only when the LLM actually replied (not a failure) ─────
    concepts_proposed: list[str] = []
    if succeeded and knowledge_manager is not None and reply:
        for concept_title, description in _extract_concepts(reply):
            try:
                knowledge_manager.propose_concept(
                    title=concept_title,
                    description=description[:_MAX_DESC],
                    confidence=0.65,
                    source="conversation",
                )
                concepts_proposed.append(concept_title)
            except Exception as exc:
                logger.debug("learning_pipeline: propose_concept failed: %s", exc)

    return {
        "episodic_stored":    episodic_stored,
        "owner_signals":      [s["signal"] for s in owner_signals],
        "concepts_proposed":  concepts_proposed,
        "emotional_state":    emotional_state,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _summarize(goal: str, reply: str, succeeded: bool) -> str:
    """Build a compact episodic summary from a conversation turn."""
    status = "Completed" if succeeded else "Failed"
    reply_snippet = reply[:120].replace("\n", " ").strip()
    return f"{status}: {goal[:80]}. Reply: {reply_snippet}"


def _extract_tags(text: str) -> list[str]:
    """Extract 1–3 topical tags from text (simple keyword approach)."""
    _TECH_WORDS = {
        "python", "javascript", "typescript", "react", "fastapi", "postgres",
        "mongodb", "redis", "docker", "git", "api", "database", "llm", "ai",
        "voice", "memory", "knowledge", "test", "debug", "deploy",
    }
    words = re.findall(r"[a-zA-Z]+", text.lower())
    tags = [w for w in words if w in _TECH_WORDS]
    return list(dict.fromkeys(tags))[:3]  # unique, preserve order, cap at 3


def _extract_concepts(text: str) -> list[tuple[str, str]]:
    """
    Extract (title, description) pairs from reply text using conservative patterns.
    Returns at most 3 pairs to avoid flooding the knowledge graph.
    """
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern in _FACT_PATTERNS:
        for m in pattern.finditer(text):
            title = m.group(1).strip().title()
            desc = m.group(0).strip()
            if len(title) < 3 or len(title) > 50:
                continue
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            results.append((title, desc))
            if len(results) >= 3:
                return results
    return results
