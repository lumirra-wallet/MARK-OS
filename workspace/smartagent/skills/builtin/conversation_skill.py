"""ConversationSkill — deterministic, rule-based small talk (greetings, thanks, farewells)."""

from __future__ import annotations

from smartagent.skills.base_skill import BaseSkill, SkillCategory, SkillContext

_GREETINGS = ("hello", "hi", "hey", "good morning", "good afternoon", "good evening")
_THANKS = ("thank you", "thanks")
_FAREWELLS = ("bye", "goodbye", "see you")
_HOW_ARE_YOU = ("how are you",)


class ConversationSkill(BaseSkill):
    """
    Handles small talk with fixed, rule-based replies — no AI/model call.

    This is deliberately the lowest-confidence built-in skill: it only
    ever matches short, unambiguous social phrases, so any more specific
    skill (memory, planning, knowledge, research) always gets first
    chance to claim a message that happens to also contain a greeting.
    """

    @property
    def name(self) -> str:
        return "conversation_skill"

    @property
    def description(self) -> str:
        return "Responds to greetings, thanks, farewells, and 'how are you' with a fixed, rule-based reply."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def required_modules(self) -> tuple[str, ...]:
        return ()

    @property
    def category(self) -> SkillCategory:
        return SkillCategory.CONVERSATION

    @property
    def confidence(self) -> float:
        return 0.2

    def validate(self, message: str) -> bool:
        text = message.lower()
        return any(
            phrase in text for phrase in (_GREETINGS + _THANKS + _FAREWELLS + _HOW_ARE_YOU)
        )

    def execute(self, message: str, context: SkillContext) -> str:
        text = message.lower()
        if any(phrase in text for phrase in _HOW_ARE_YOU):
            return f"I'm running smoothly, thanks for asking! You said: {message}"
        if any(phrase in text for phrase in _THANKS):
            return f"You're welcome! You said: {message}"
        if any(phrase in text for phrase in _FAREWELLS):
            return f"Goodbye for now! You said: {message}"
        return f"Hi there — {context.settings.agent_name} here. You said: {message}"
