"""ResearchSkill — queues/summarizes research requests via `ResearchManager`."""

from __future__ import annotations

from smartagent.skills.base_skill import BaseSkill, SkillCategory, SkillContext
from smartagent.skills.permissions import Permission

_KEYWORDS = ("research", "look up", "find out about", "search for information")


class ResearchSkill(BaseSkill):
    """
    Attempts a research request through `SkillContext.research`.

    Requires `NETWORK_ACCESS`, which is NOT in `SmartAgent`'s default
    granted permissions (see `smartagent.skills.permissions`) — by design,
    this skill is denied out of the box, demonstrating that declaring a
    permission is not the same as having it. Even once granted, actual
    web search is still unimplemented (`ResearchManager.search()` raises
    `NotImplementedError`); this skill surfaces that honestly rather than
    pretending to have researched something.
    """

    @property
    def name(self) -> str:
        return "research_skill"

    @property
    def description(self) -> str:
        return "Looks up information on a topic through the research workflow."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def required_modules(self) -> tuple[str, ...]:
        return ("research",)

    @property
    def category(self) -> SkillCategory:
        return SkillCategory.RESEARCH

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.NETWORK_ACCESS,)

    @property
    def confidence(self) -> float:
        return 0.7

    def validate(self, message: str) -> bool:
        text = message.lower()
        return any(keyword in text for keyword in _KEYWORDS)

    def execute(self, message: str, context: SkillContext) -> str:
        topic = message
        for keyword in _KEYWORDS:
            topic = topic.lower().replace(keyword, "").strip(" :.")
        topic = topic or message
        try:
            context.research.search(topic)
        except NotImplementedError as exc:
            return f"I can't research {topic!r} yet: {exc}"
        return f"Researching {topic!r}."
