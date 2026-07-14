"""SystemInfoSkill — reports which Brain modules and skills are currently registered."""

from __future__ import annotations

from smartagent.skills.base_skill import BaseSkill, SkillCategory, SkillContext
from smartagent.skills.permissions import Permission

_KEYWORDS = ("system info", "system status", "what modules", "list modules", "what skills", "list skills")


class SystemInfoSkill(BaseSkill):
    """
    Reports the agent's own registered modules/skills.

    Requires `SYSTEM_COMMANDS`, which is NOT granted by default — treating
    "introspect what MARK can currently do" as a conservative, opt-in
    capability rather than something any request can trigger for free.
    This is a deliberate demonstration of Milestone 3's permission rule
    ("nothing is granted automatically"), not a sign the skill is broken.
    """

    @property
    def name(self) -> str:
        return "system_info_skill"

    @property
    def description(self) -> str:
        return "Reports which Brain modules and skills are currently registered."

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
        return SkillCategory.SYSTEM

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.SYSTEM_COMMANDS,)

    @property
    def confidence(self) -> float:
        return 0.8

    def validate(self, message: str) -> bool:
        text = message.lower()
        return any(keyword in text for keyword in _KEYWORDS)

    def execute(self, message: str, context: SkillContext) -> str:
        modules = ", ".join(context.module_names) or "none"
        skills = ", ".join(context.skill_names) or "none"
        return f"Registered modules: {modules}. Registered skills: {skills}."
