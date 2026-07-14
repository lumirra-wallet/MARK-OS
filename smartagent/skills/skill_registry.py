"""
SkillRegistry — Milestone 3, Part 3.

Upgrades the Milestone 1 placeholder registry (which only supported
`register`/`get`/`list_available`) into the production-ready container
`SkillEngine` uses: register, unregister, enable, disable, reload, list,
find.

Design decision: the registry stores each skill's *factory* (by default
just `type(skill)`, a zero-arg constructor) alongside the live instance,
purely so `reload()` has something to call — it re-instantiates a skill
from scratch rather than mutating it in place, which matches how the
Skill Loader (`skill_loader.py`) will re-discover skills after code
changes without restarting the whole process.
"""

from __future__ import annotations

from typing import Callable

from smartagent.logs.logger import get_logger
from smartagent.skills.base_skill import BaseSkill, SkillCategory, SkillStatus

logger = get_logger(__name__)

SkillFactory = Callable[[], BaseSkill]


class SkillRegistry:
    """Holds every skill currently known to SmartAgent, enabled or not."""

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}
        self._factories: dict[str, SkillFactory] = {}
        self._status: dict[str, SkillStatus] = {}

    def register(self, skill: BaseSkill, factory: SkillFactory | None = None) -> None:
        """
        Add `skill` to the registry under its `name`, enabled by default.

        `factory` defaults to the skill's own class (a zero-arg
        constructor) so `reload()` can build a fresh instance later;
        pass an explicit factory for skills that need constructor
        arguments.
        """
        self._skills[skill.name] = skill
        self._factories[skill.name] = factory or type(skill)
        self._status[skill.name] = SkillStatus.ENABLED
        logger.info("Skill registered: %s (v%s by %s)", skill.name, skill.version, skill.author)

    def unregister(self, name: str) -> None:
        """Remove a skill entirely. A no-op if `name` isn't registered."""
        self._skills.pop(name, None)
        self._factories.pop(name, None)
        self._status.pop(name, None)

    def enable(self, name: str) -> bool:
        """Mark a registered skill enabled. Returns False if `name` is unknown."""
        if name not in self._skills:
            return False
        self._status[name] = SkillStatus.ENABLED
        logger.info("Skill enabled: %s", name)
        return True

    def disable(self, name: str) -> bool:
        """Mark a registered skill disabled (excluded from `list(enabled_only=True)`)."""
        if name not in self._skills:
            return False
        self._status[name] = SkillStatus.DISABLED
        logger.info("Skill disabled: %s", name)
        return True

    def reload(self, name: str) -> BaseSkill | None:
        """
        Re-instantiate a skill from its stored factory, replacing the old instance.

        Preserves the skill's current enabled/disabled status. Returns
        the new instance, or None if `name` isn't registered.
        """
        factory = self._factories.get(name)
        if factory is None:
            return None
        previous_status = self._status.get(name, SkillStatus.ENABLED)
        fresh = factory()
        self._skills[name] = fresh
        self._status[name] = previous_status
        logger.info("Skill reloaded: %s", name)
        return fresh

    def list(self, enabled_only: bool = True, category: SkillCategory | None = None) -> list[BaseSkill]:
        """List registered skills, optionally filtered to enabled-only and/or by category."""
        skills = list(self._skills.values())
        if enabled_only:
            skills = [s for s in skills if self._status.get(s.name) == SkillStatus.ENABLED]
        if category is not None:
            skills = [s for s in skills if s.category == category]
        return skills

    def find(self, name: str) -> BaseSkill | None:
        """Look up a single registered skill by exact name, or None if not found."""
        return self._skills.get(name)

    def is_enabled(self, name: str) -> bool:
        """Whether `name` is registered and currently enabled."""
        return self._status.get(name) == SkillStatus.ENABLED

    def list_available(self) -> list[str]:
        """
        Return the names of every registered skill, enabled or not.

        Kept for backward compatibility with callers that only need the
        name list (e.g. reporting), including Milestone 2's
        `module_bindings.skills_handler` before Skills Engine v1 existed.
        """
        return list(self._skills.keys())
