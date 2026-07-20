"""
SemanticMemory — permanent facts and structured knowledge.

Stored as a single JSON file: ~/.cache/mark/memory/semantic.json
Each entry is a fact with confidence, tags, and a timestamp.

This is MARK's world knowledge — "things that are true."
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_ROOT = Path(os.environ.get("MARK_MEMORY_DIR", "~/.cache/mark/memory")).expanduser()


class SemanticMemory:
    """Permanent store of facts MARK has learned about the world."""

    def __init__(self, root: Path | None = None) -> None:
        self._path = (root or _MEMORY_ROOT) / "semantic.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, entries: list[dict]) -> None:
        try:
            # Keep most recent 500 facts
            entries = entries[-500:]
            self._path.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("SemanticMemory._save failed: %s", exc)

    def store(
        self,
        fact: str,
        tags: list[str] | None = None,
        confidence: float = 0.8,
        source: str = "conversation",
    ) -> dict[str, Any]:
        """Persist one fact. Returns the stored entry."""
        entry: dict[str, Any] = {
            "ts":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fact":       fact[:300],
            "tags":       tags or [],
            "confidence": round(min(1.0, max(0.0, confidence)), 2),
            "source":     source,
        }
        entries = self._load()
        # Avoid storing near-duplicate facts
        existing_facts = {e.get("fact", "").lower() for e in entries}
        if fact.lower() not in existing_facts:
            entries.append(entry)
            self._save(entries)
        return entry

    def relevant(self, query: str, n: int = 10) -> list[dict]:
        """Return up to n facts relevant to the query (keyword overlap)."""
        words = set(query.lower().split())
        scored: list[tuple[float, dict]] = []
        for entry in self._load():
            text = (entry.get("fact", "") + " " + " ".join(entry.get("tags", []))).lower()
            score = sum(1 for w in words if w in text) * entry.get("confidence", 0.5)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:n]]

    def count(self) -> int:
        return len(self._load())
