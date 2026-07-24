"""
web_search.py — Elena's internet research capability.

Uses DuckDuckGo (no API key required) to fetch current information.
Results are injected into Elena's context before she responds, and
useful facts are stored in semantic memory so she remembers them.

Trigger detection is conservative — only queries that clearly need
live data trigger a search, so idle conversation stays fast.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Search-trigger patterns ───────────────────────────────────────────────────
# Only triggers when the query clearly benefits from live/current data.
_SEARCH_TRIGGERS = [
    re.compile(r"\b(search|look up|look it up|look for|research|find out|google|find me)\b", re.I),
    re.compile(r"\b(what(\'s| is) (the latest|happening|going on|new about|current)\b)", re.I),
    re.compile(r"\b(latest|recent|current|today\'?s?|news|update|announcement)\b.{0,50}\b(about|on|for|with|from)\b", re.I),
    re.compile(r"\b(who is|who\'s|who was|who were)\b.{0,60}(now|today|recently|currently|2024|2025|2026)\b", re.I),
    re.compile(r"\b(when did|when was|when is|when does)\b", re.I),
    re.compile(r"\b(stock price|stock market|weather|score|results|released|announced)\b", re.I),
    re.compile(r"\b(how (much|many|long|far|old) (is|are|does|do|did))\b", re.I),
    re.compile(r"\b(can you find|can you search|can you look)\b", re.I),
]

# Simple TTL cache so the same query within 60s doesn't re-fetch
_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_CACHE_TTL = 60.0


def should_search(text: str) -> bool:
    """Return True if the utterance likely needs live web data."""
    return any(p.search(text) for p in _SEARCH_TRIGGERS)


def search(query: str, max_results: int = 4) -> list[dict[str, str]]:
    """
    Run a DuckDuckGo text search and return up to max_results results.
    Each result: {"title": str, "url": str, "snippet": str}
    Returns [] on any error — never raises, never blocks > ~5 s.
    """
    key = query.strip().lower()[:120]
    now = time.monotonic()
    if key in _cache and now - _cache[key][0] < _CACHE_TTL:
        logger.debug("web_search: cache hit for %r", key[:50])
        return _cache[key][1]

    try:
        from duckduckgo_search import DDGS
        results: list[dict[str, str]] = []
        with DDGS(timeout=5) as ddgs:
            for r in ddgs.text(query.strip(), max_results=max_results):
                results.append({
                    "title":   r.get("title", "")[:120],
                    "url":     r.get("href", r.get("url", ""))[:200],
                    "snippet": r.get("body", r.get("snippet", ""))[:300],
                })
        _cache[key] = (now, results)
        logger.info("web_search: %d results for %r", len(results), query[:60])
        return results
    except Exception as exc:
        logger.warning("web_search: failed for %r: %s", query[:60], exc)
        return []


def format_for_prompt(results: list[dict[str, str]]) -> str:
    """Format search results as a compact block for injecting into the system prompt."""
    if not results:
        return ""
    lines = ["[Web search — live results]"]
    for r in results:
        title   = r.get("title", "")
        snippet = r.get("snippet", "")
        url     = r.get("url", "")
        lines.append(f"• {title}: {snippet}" + (f" → {url}" if url else ""))
    return "\n".join(lines)


def store_to_semantic(results: list[dict[str, str]], query: str) -> None:
    """Persist useful snippets into SemanticMemory so Elena remembers them."""
    if not results:
        return
    try:
        from smartagent.memory.layers.semantic import SemanticMemory
        mem = SemanticMemory()
        for r in results[:2]:
            snippet = r.get("snippet", "")
            title   = r.get("title", "")
            if len(snippet) > 30:
                fact = f"{title}: {snippet}"[:300]
                mem.store(fact, tags=["web_search", *query.lower().split()[:3]], confidence=0.72, source="web")
    except Exception as exc:
        logger.debug("web_search: semantic store failed: %s", exc)
