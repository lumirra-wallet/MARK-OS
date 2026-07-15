"""MemorySkill — remember/recall/forget requests, backed by `MemoryManager`."""

from __future__ import annotations

from smartagent.skills.base_skill import BaseSkill, SkillCategory, SkillContext
from smartagent.skills.permissions import Permission

_REMEMBER_PREFIXES = ("remember that ", "remember ")
_FORGET_PREFIXES = ("forget that ", "forget ")
_RECALL_KEYWORDS = ("recall", "what did i tell you", "what do you remember")


def _strip_prefix(text: str, prefixes: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return None


class MemorySkill(BaseSkill):
    """Handles explicit remember/recall/forget requests using `SkillContext.memory`."""

    @property
    def name(self) -> str:
        return "memory_skill"

    @property
    def description(self) -> str:
        return "Remembers, recalls, or forgets a specific fact on request."

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
        return SkillCategory.MEMORY

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.READ_MEMORY, Permission.WRITE_MEMORY)

    @property
    def confidence(self) -> float:
        return 0.9

    def validate(self, message: str) -> bool:
        text = message.lower()
        return (
            _strip_prefix(message, _REMEMBER_PREFIXES) is not None
            or _strip_prefix(message, _FORGET_PREFIXES) is not None
            or any(keyword in text for keyword in _RECALL_KEYWORDS)
        )

    def execute(self, message: str, context: SkillContext) -> str:
        remember_content = _strip_prefix(message, _REMEMBER_PREFIXES)
        if remember_content:
            entry = context.memory.remember(remember_content, category="Personal")
            return f"Got it — I'll remember: {entry.content}"

        forget_content = _strip_prefix(message, _FORGET_PREFIXES)
        if forget_content:
            matches = context.memory.search(forget_content, limit=1)
            if matches and context.memory.delete(matches[0].id):
                return f"Forgotten: {matches[0].content}"
            return f"I don't have a memory matching {forget_content!r} to forget."

        # Recall: search on whatever's left after stripping the trigger phrase.
        query = message
        for keyword in _RECALL_KEYWORDS:
            query = query.lower().replace(keyword, "").strip()
        results = context.memory.search(query or message, limit=3)
        if not results:
            return "I don't have anything remembered about that yet."
        return "Here's what I remember: " + "; ".join(entry.content for entry in results)
