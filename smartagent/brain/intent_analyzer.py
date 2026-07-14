"""
IntentAnalyzer — Milestone 2 Brain v2, Part 2.

Classifies a raw user message into a coarse `Intent` category using
simple, transparent, rule-based keyword matching. Deliberately **not**
AI-driven yet ("Do NOT use AI yet" — Milestone 2 rules): the goal for v1
is a predictable, debuggable classifier that the Decision Engine (and,
later, a real model-driven classifier) can be benchmarked against.
"""

from __future__ import annotations

from enum import Enum


class Intent(str, Enum):
    """The categories a request can be classified into."""

    MEMORY = "memory"
    RESEARCH = "research"
    TOOL = "tool"
    SKILL = "skill"
    VISION = "vision"
    VOICE = "voice"
    PLANNING = "planning"
    MODEL = "model"
    AUTOMATION = "automation"
    UNKNOWN = "unknown"


# Keyword -> Intent rules, checked in order. A dict (not a set) so the
# iteration order is stable and each intent's keyword list stays easy to
# read/extend independently. Order matters when a message could plausibly
# match more than one category (e.g. "remember" wins over "plan" if both
# appear) — declared roughly most-specific-first.
_INTENT_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.MEMORY: ("remember", "recall", "forget", "what did i tell you", "my favorite"),
    Intent.RESEARCH: ("research", "look up", "find out about", "search for information"),
    Intent.PLANNING: ("goal", "plan ", "roadmap", "task list", "to-do", "todo"),
    Intent.VOICE: ("speak", "say this out loud", "transcribe", "voice message"),
    Intent.VISION: ("this image", "this photo", "this picture", "this screenshot", "look at this"),
    Intent.AUTOMATION: ("schedule", "every day", "every hour", "automate", "remind me every"),
    Intent.TOOL: ("calculate", "convert ", "run the ", "use the tool"),
    Intent.SKILL: ("skill:",),
}


class IntentAnalyzer:
    """Rule-based classifier that maps a message to a single `Intent`."""

    def analyze(self, message: str) -> Intent:
        """
        Classify `message` into an `Intent`.

        Returns `Intent.UNKNOWN` when no keyword rule matches — this is
        the expected, common case for v1 and is not an error; the Decision
        Engine still has a well-defined fallback chain for it.
        """
        text = message.lower()
        for intent, keywords in _INTENT_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return intent
        return Intent.UNKNOWN
