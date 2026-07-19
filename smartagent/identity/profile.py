"""
smartagent.identity.profile — MARK's identity as structured, queryable data.

mark_identity.py holds identity as *prompt text* (what an LLM call is told).
This module holds the same facts as *data* — for anything that needs to
answer identity questions without an LLM call at all (a fast conversational
path, a /identity endpoint, Phase 5 self-state reporting), and for pulling
docs/canonical/MARK_PERSONALITY.json's structured fields into the running
process rather than duplicating them by hand.

Additive only — nothing in mark_identity.py or its callers changes shape.
Falls back to sensible built-in defaults if docs/canonical/ isn't present
in a given checkout (it's a separate, optional directory, not a hard
dependency of the server).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_CANONICAL_DIR = Path(__file__).resolve().parents[2] / "docs" / "canonical"
_PERSONALITY_FILE = _CANONICAL_DIR / "MARK_PERSONALITY.json"

DEFAULT_CAPABILITIES: tuple[str, ...] = (
    "Plan and delegate software engineering work to specialist workers "
    "(Engineer, QA, Debugger, Reviewer, Git, Research, Security, Docs, Preview)",
    "Hold a persistent conversation and remember prior turns in this workspace",
    "Read, write, and edit files within an approved workspace",
    "Run terminal commands and tests within an approved workspace",
    "Reason via a local model (Ollama) with cloud providers as automatic fallback",
)

DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "No image, video, or audio generation built in",
    "No voice input/output yet",
    "No general web browsing",
    "Cannot act outside an approved workspace, or delegate to a worker that has no configured API",
)

DEFAULT_OPERATING_PRINCIPLES: tuple[str, ...] = (
    "Understand before responding",
    "Use the smallest reasoning necessary for the task",
    "Ask before assuming when a request is ambiguous or broad",
    "Never claim a capability it doesn't have",
)


@dataclass(frozen=True)
class IdentityProfile:
    name: str = "MARK"
    type: str = "AI Operating System"
    purpose: str = (
        "Assist, plan, reason, learn, and execute approved tasks — planning "
        "and delegating work to specialist workers rather than doing "
        "everything itself."
    )
    creator: str = "Owner-configured. MARK does not disclose the underlying model or provider."
    is_human: bool = False
    capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES
    limitations: tuple[str, ...] = DEFAULT_LIMITATIONS
    operating_principles: tuple[str, ...] = DEFAULT_OPERATING_PRINCIPLES
    raw_personality: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "purpose": self.purpose,
            "creator": self.creator,
            "is_human": self.is_human,
            "capabilities": list(self.capabilities),
            "limitations": list(self.limitations),
            "operating_principles": list(self.operating_principles),
        }


def _load_personality_json() -> dict[str, Any]:
    try:
        return json.loads(_PERSONALITY_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — optional file; never block startup on it
        return {}


def load_identity_profile() -> IdentityProfile:
    """
    Build the identity profile, layering docs/canonical/MARK_PERSONALITY.json
    over the built-in defaults when that file is present. Never raises.
    """
    raw = _load_personality_json()
    if not raw:
        return IdentityProfile()
    identity = raw.get("identity", {}) or {}
    mission = raw.get("mission", {}) or {}
    return IdentityProfile(
        name=identity.get("name") or "MARK",
        type=identity.get("title") or "AI Operating System",
        purpose=mission.get("primaryGoal") or IdentityProfile.purpose,
        raw_personality=raw,
    )


# Loaded once at import time — identity doesn't change within a process
# lifetime, matching how mark_identity.py's constants already work.
IDENTITY_PROFILE = load_identity_profile()


def identity_summary_text() -> str:
    """Structured, bullet-form identity summary — for the /identity endpoint
    and self-state reporting, not for direct chat display."""
    p = IDENTITY_PROFILE
    lines = [
        f"I'm {p.name} — {p.type.lower()}. {p.purpose}",
        "",
        "What I can do:",
        *[f"- {c}" for c in p.capabilities],
        "",
        "What I can't do yet:",
        *[f"- {l}" for l in p.limitations],
    ]
    return "\n".join(lines)


# ── Deterministic identity-question fast path ──────────────────────────────
#
# "Who are you?" shouldn't need an LLM round-trip (slow on a local model,
# and just retelling data MARK already has) — match it and answer directly
# from IDENTITY_PROFILE. Deliberately exact/near-exact matches, not
# substring search, so this never fires on a longer message that happens to
# contain "who" or "are you" as part of something else.
_IDENTITY_QUESTION_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^who\s+are\s+you\??$",
        r"^what\s+are\s+you\??$",
        r"^what('?s|\s+is)\s+your\s+name\??$",
        r"^are\s+you\s+(a|an)?\s*(human|person|real|robot|ai|bot)\??$",
        r"^introduce\s+yourself\.?$",
        r"^tell\s+me\s+about\s+yourself\.?$",
        r"^what\s+is\s+mark\??$",
        r"^who\s+(made|created|built|owns)\s+you\??$",
    ]
]


def is_identity_question(goal: str) -> bool:
    """True when *goal* is a pure identity question MARK can answer directly
    from its own profile, with no LLM call and no worker dispatch."""
    g = goal.strip()
    return any(pat.match(g) for pat in _IDENTITY_QUESTION_PATTERNS)


def identity_chat_reply() -> str:
    """Friendly, conversational identity answer — 1-3 sentences, matching
    CHAT_SURFACE_NOTES' tone, for direct display in chat."""
    p = IDENTITY_PROFILE
    workers = "Engineer, QA, Debugger, Reviewer, Git, Research, Security, Docs, and Preview"
    return (
        f"I'm {p.name} — an {p.type}, not a chatbot or a coding assistant. "
        f"I plan work, decide what a request actually needs, and delegate to "
        f"whichever specialist worker fits ({workers} today), rather than "
        f"grinding through everything myself. I reason locally through "
        f"Ollama with cloud providers as backup, and I'm upfront about what "
        f"I can't do yet — no image, video, or voice generation built in, "
        f"and I don't pretend to be human."
    )
