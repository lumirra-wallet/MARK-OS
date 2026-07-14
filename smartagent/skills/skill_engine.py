"""
SkillEngine — Milestone 3, Part 1 and Part 8.

The single thing the Brain talks to for anything skill-related:

    BrainRouter -> ModuleRegistry["skills"] -> SkillEngine.execute()
        -> (pick the best matching, permitted BaseSkill)
        -> ActionResult

The Brain never knows how a skill works internally, and never imports
`smartagent.skills.builtin` — it only calls `SkillEngine.execute()` and
gets back a standard `ActionResult`, exactly like every other module in
`smartagent.brain.module_registry`.

Dispatch strategy: mirrors `BrainRouter`'s own chain-of-responsibility.
Every enabled skill whose `validate(message)` returns True is a
candidate; candidates are tried most-confident-first, and each is denied
outright (without running `execute()`) if its declared permissions
aren't all granted. This means an unmet permission on the best-matching
skill correctly falls through to the next candidate rather than silently
failing the whole request.
"""

from __future__ import annotations

import time

from smartagent.brain.action_result import ActionResult
from smartagent.brain.events import Events, EventBus
from smartagent.logs.logger import get_logger
from smartagent.skills.base_skill import BaseSkill, SkillContext
from smartagent.skills.permissions import PermissionManager
from smartagent.skills.skill_loader import DEFAULT_SKILLS_PACKAGE, discover_skill_classes
from smartagent.skills.skill_registry import SkillRegistry

logger = get_logger(__name__)


class SkillEngine:
    """
    Registers, loads, and executes skills on the Brain's behalf.

    Args:
        registry: Where skills live. Owned by whoever constructs the
            engine (typically `SmartAgent`) so the same registry can be
            inspected/managed outside the engine too (e.g. a future
            admin UI listing skills).
        permissions: Authority for whether a skill's declared
            permissions are currently granted. See
            `smartagent.skills.permissions`.
        event_bus: Optional bus to publish `SkillExecuted` onto. Shared
            with the rest of the agent so subscribers see skill activity
            alongside everything else the Brain does.
    """

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        permissions: PermissionManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.registry = registry or SkillRegistry()
        self.permissions = permissions or PermissionManager()
        self.events = event_bus

    def register(self, skill: BaseSkill) -> None:
        """Register a single skill instance. Logs "Skill Loaded" per Milestone 3 Part 9."""
        self.registry.register(skill)
        logger.info("Skill Loaded: %s", skill.name)

    def load_skills(self, package: str = DEFAULT_SKILLS_PACKAGE) -> list[str]:
        """
        Discover and register every built-in skill class found in `package`.

        Uses `smartagent.skills.skill_loader` (Part 7) so no skill needs
        a hardcoded import anywhere else in the codebase. Returns the
        names of every skill registered this call.
        """
        registered: list[str] = []
        for skill_class in discover_skill_classes(package):
            skill = skill_class()
            self.register(skill)
            registered.append(skill.name)
        return registered

    def list_available(self) -> list[str]:
        """Names of every registered skill (enabled or not) — used for reporting."""
        return self.registry.list_available()

    def _candidates(self, message: str) -> list[BaseSkill]:
        matching = [skill for skill in self.registry.list(enabled_only=True) if skill.validate(message)]
        matching.sort(key=lambda skill: skill.confidence, reverse=True)
        return matching

    def execute(self, message: str, context: SkillContext) -> ActionResult:
        """
        Find the best enabled, permitted skill for `message` and run it.

        Returns `success=False` (never raises) if no enabled skill
        matches, or if every matching skill is missing a required
        permission — `BrainRouter` treats that exactly like any other
        module declining to help, and falls through to the next
        candidate module (e.g. `tools`, then `model`, then `unknown`).
        """
        candidates = self._candidates(message)
        if not candidates:
            return ActionResult(success=False, message="No skill can handle this request.", source="skills")

        for skill in candidates:
            missing = self.permissions.missing(skill.permissions)
            if missing:
                missing_names = ", ".join(p.value for p in missing)
                logger.info("Permission Requests: %s needs %s (not granted)", skill.name, missing_names)
                logger.warning("Skill Failed: %s denied — missing permissions: %s", skill.name, missing_names)
                continue

            start = time.monotonic()
            try:
                outcome = skill.execute(message, context)
            except Exception as exc:  # noqa: BLE001 - a failing skill must not crash the Brain
                elapsed = time.monotonic() - start
                logger.warning("Skill Failed: %s raised %s: %s", skill.name, type(exc).__name__, exc)
                continue
            elapsed = time.monotonic() - start

            result = self._to_action_result(skill, outcome, elapsed)
            logger.info(
                "Skill Executed: %s success=%s execution_time=%.4fs", skill.name, result.success, elapsed
            )
            if self.events is not None:
                self.events.publish(
                    Events.SKILL_EXECUTED,
                    skill=skill.name,
                    success=result.success,
                    execution_time=elapsed,
                )
            if result.success:
                return result
            # This skill matched but didn't actually resolve the request
            # (e.g. it recognized the message but had nothing to do) —
            # give the next matching skill a chance, same as BrainRouter.

        return ActionResult(
            success=False,
            message="No enabled, permitted skill could handle this request.",
            source="skills",
        )

    @staticmethod
    def _to_action_result(skill: BaseSkill, outcome: object, elapsed: float) -> ActionResult:
        """Normalize whatever a skill's `execute()` returned into a standard `ActionResult`."""
        if isinstance(outcome, ActionResult):
            outcome.source = outcome.source or skill.name
            outcome.execution_time = outcome.execution_time or elapsed
            return outcome
        # Skills are allowed to just return a message string for the
        # common case — wrap it as a successful result so simple skills
        # don't need to import ActionResult themselves.
        return ActionResult(
            success=True,
            message=str(outcome),
            source=skill.name,
            execution_time=elapsed,
            confidence=skill.confidence,
        )
