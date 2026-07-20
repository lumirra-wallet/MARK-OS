"""
OwnerMemory — everything MARK learns about the owner over time.

Stored as a single JSON file: ~/.cache/mark/memory/owner.json

Contains structured preferences, habits, communication style,
engineering philosophy, and recurring projects. MARK should consult
this before making decisions, personalizing responses, and understanding
what the owner cares about.

This is MARK's model of the person — "who I work for and what they value."
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_ROOT = Path(os.environ.get("MARK_MEMORY_DIR", "~/.cache/mark/memory")).expanduser()

# Patterns that signal an owner preference or habit in natural language
_PREFERENCE_PATTERNS = [
    (re.compile(r"\b(?:i\s+(?:always|usually|prefer|like|want|need|use|hate|avoid))\s+(.{5,80})", re.I), "preference"),
    (re.compile(r"\b(?:don't|do not|never)\s+(?:use|do|put|add|write)\s+(.{5,60})", re.I), "avoidance"),
    (re.compile(r"\bmy\s+(?:style|approach|rule|convention|standard)\s+(?:is|:)\s*(.{5,100})", re.I), "style"),
    (re.compile(r"\b(?:keep|make)\s+(?:it|things|code|everything)\s+(.{5,60})", re.I), "principle"),
]


def extract_owner_signals(text: str) -> list[dict[str, str]]:
    """
    Parse a message for explicit owner preference/habit signals.
    Returns a list of {type, signal} dicts — may be empty.
    """
    signals: list[dict[str, str]] = []
    for pattern, signal_type in _PREFERENCE_PATTERNS:
        for m in pattern.finditer(text):
            snippet = m.group(1).strip().rstrip(".,;!?")
            if len(snippet) >= 5:
                signals.append({"type": signal_type, "signal": snippet})
    return signals[:5]  # cap per message


class OwnerMemory:
    """MARK's model of the owner — built up incrementally over conversations."""

    def __init__(self, root: Path | None = None) -> None:
        self._path = (root or _MEMORY_ROOT) / "owner.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"preferences": [], "habits": [], "style": [], "projects": [], "updated_at": ""}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {"preferences": [], "habits": [], "style": [], "projects": [], "updated_at": ""}

    def _save(self, profile: dict[str, Any]) -> None:
        profile["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            self._path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("OwnerMemory._save failed: %s", exc)

    def update(self, key: str, value: str, confidence: float = 0.9) -> dict[str, Any]:
        """
        Add or update one owner profile attribute.
        key is the category: "preference", "habit", "style", "project".
        """
        profile = self._load()
        bucket = profile.get(key + "s", profile.get("preferences", []))
        # Avoid near-duplicates
        existing = {e.get("value", "").lower() for e in bucket}
        if value.lower() not in existing:
            bucket.append({
                "value":      value[:200],
                "confidence": round(confidence, 2),
                "ts":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            # Keep most recent 50 per category
            bucket = bucket[-50:]
            profile[key + "s"] = bucket
            self._save(profile)
        return {"key": key, "value": value}

    def extract_and_update(self, text: str) -> list[dict[str, str]]:
        """
        Parse text for owner signals, persist any found, return what was stored.
        """
        signals = extract_owner_signals(text)
        stored: list[dict[str, str]] = []
        for sig in signals:
            self.update(sig["type"], sig["signal"])
            stored.append(sig)
        return stored

    def profile_summary(self, max_chars: int = 600) -> str:
        """
        Return a compact text block summarising what MARK knows about the owner.
        Injected into the system prompt before reasoning.
        """
        profile = self._load()
        lines: list[str] = []
        for key, label in [("preferences", "Prefers"), ("habits", "Usually"), ("style", "Style")]:
            for entry in profile.get(key, [])[-5:]:
                v = entry.get("value", "")
                if v:
                    lines.append(f"{label}: {v}")
        text = "\n".join(lines)
        return text[:max_chars] if text else ""

    def count(self) -> int:
        profile = self._load()
        return sum(len(v) for v in profile.values() if isinstance(v, list))
