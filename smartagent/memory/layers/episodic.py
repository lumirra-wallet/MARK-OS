"""
EpisodicMemory — events: conversations, decisions, mistakes, successes.

Stored as one JSON file per day in ~/.cache/mark/memory/episodic/.
Each file is a list of entries. Recent entries are loaded on demand;
older files are never touched unless explicitly retrieved.

This is MARK's autobiographical memory — "things that happened."
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


class EpisodicMemory:
    """Append-only log of events MARK was part of."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or _MEMORY_ROOT) / "episodic"
        self._root.mkdir(parents=True, exist_ok=True)

    def _today_file(self) -> Path:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._root / f"{today}.json"

    def _load_today(self) -> list[dict]:
        f = self._today_file()
        if not f.exists():
            return []
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return []

    def store(
        self,
        summary: str,
        goal: str = "",
        succeeded: bool = True,
        emotional_state: str = "neutral",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Persist one episodic event and return the stored entry.
        Called after every completed interaction — never silently dropped.
        """
        entry: dict[str, Any] = {
            "ts":            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary":       summary[:400],
            "goal":          goal[:200],
            "succeeded":     succeeded,
            "emotional_state": emotional_state,
            "tags":          tags or [],
        }
        entries = self._load_today()
        entries.append(entry)
        try:
            self._today_file().write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("EpisodicMemory.store failed: %s", exc)
        return entry

    def recent(self, n: int = 10) -> list[dict]:
        """Return the n most recent episodic events, newest first."""
        # Load today's file first, then yesterday's if needed.
        entries = list(reversed(self._load_today()))
        if len(entries) < n:
            for f in sorted(self._root.glob("*.json"), reverse=True)[1:4]:
                try:
                    old = json.loads(f.read_text(encoding="utf-8"))
                    entries.extend(reversed(old))
                except Exception:
                    pass
                if len(entries) >= n:
                    break
        return entries[:n]

    def relevant(self, query: str, n: int = 5) -> list[dict]:
        """Return up to n episodic events whose summary overlaps with query words."""
        words = set(query.lower().split())
        scored: list[tuple[int, dict]] = []
        for entry in self.recent(50):
            text = (entry.get("summary", "") + " " + entry.get("goal", "")).lower()
            score = sum(1 for w in words if w in text)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:n]]

    def count_today(self) -> int:
        return len(self._load_today())
