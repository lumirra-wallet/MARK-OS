"""KnowledgeSkill — notes and recalls facts in memory's dedicated "Knowledge" category."""

from __future__ import annotations

from smartagent.skills.base_skill import BaseSkill, SkillCategory, SkillContext
from smartagent.skills.permissions import Permission

_NOTE_PREFIXES = ("note:", "note that ")
_QUERY_KEYWORDS = ("what do you know about", "explain", "define", "knowledge:")


class KnowledgeSkill(BaseSkill):
    """
    Stores/retrieves structured facts using memory's "Knowledge" category.

    Distinct from `MemorySkill`: this skill is specifically about
    durable, reusable facts ("Python was created by Guido van Rossum")
    rather than personal remember/forget requests, so it files things
    under `Knowledge` instead of `Personal`.
    """

    @property
    def name(self) -> str:
        return "knowledge_skill"

    @property
    def description(self) -> str:
        return "Notes a fact into the Knowledge category, or explains what's already known about a topic."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def required_modules(self) -> tuple[str, ...]:
        return ("memory",)

    @property
    def category(self) -> SkillCategory:
        return SkillCategory.KNOWLEDGE

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.READ_MEMORY, Permission.WRITE_MEMORY)

    @property
    def confidence(self) -> float:
        return 0.6

    def validate(self, message: str) -> bool:
        text = message.lower()
        return any(text.startswith(prefix) for prefix in _NOTE_PREFIXES) or any(
            keyword in text for keyword in _QUERY_KEYWORDS
        )

    def execute(self, message: str, context: SkillContext) -> str:
        text = message.strip()
        lowered = text.lower()
        for prefix in _NOTE_PREFIXES:
            if lowered.startswith(prefix):
                fact = text[len(prefix):].strip()
                if not fact:
                    return "Tell me what to note, e.g. 'note: the API rate limit is 100/min'."
                context.memory.remember(fact, category="Knowledge")
                return f"Noted: {fact}"

        topic = text
        for keyword in _QUERY_KEYWORDS:
            topic = topic.lower().replace(keyword, "").strip(" :.")
        results = context.memory.search(topic or text, category="Knowledge", limit=3)
        if not results:
            return f"I don't have any knowledge notes about {topic or text!r} yet."
        return "Here's what I know: " + "; ".join(entry.content for entry in results)
