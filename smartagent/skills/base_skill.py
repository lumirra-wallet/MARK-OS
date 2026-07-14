"""
BaseSkill — Milestone 3, Part 2.

Defines the abstract contract every SmartAgent skill implements, plus the
supporting metadata/context types (Parts 5 and 8). A `Skill` is a
high-level, user-facing capability that the Brain can invoke without ever
knowing how it works internally — it may use Memory, Tools, Planning,
Models, or Research, but the Brain only ever sees an `ActionResult`
(see `smartagent.brain.action_result`).

This deliberately lives in `smartagent.skills`, not `smartagent.brain` —
skills are a capability package like `tools`/`voice`/`vision`, not part of
the Brain's own routing machinery. `SkillEngine` (the thing the Brain
actually talks to) is what bridges the two, in `skill_engine.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from smartagent.skills.permissions import Permission

if TYPE_CHECKING:
    from smartagent.brain.events import EventBus
    from smartagent.config.settings import Settings
    from smartagent.memory.memory_manager import MemoryManager
    from smartagent.models.model_client import ModelClient
    from smartagent.planning.goal_manager import GoalManager
    from smartagent.research.research_manager import ResearchManager
    from smartagent.tools.tool_engine import ToolEngine
    from smartagent.tools.tool_registry import ToolRegistry


class SkillCategory(str, Enum):
    """Coarse grouping used for discovery/reporting (Part 5's "Category")."""

    MEMORY = "memory"
    RESEARCH = "research"
    PLANNING = "planning"
    KNOWLEDGE = "knowledge"
    CONVERSATION = "conversation"
    SYSTEM = "system"
    GENERAL = "general"


class SkillStatus(str, Enum):
    """Runtime status a skill can be in, managed by `SkillRegistry.enable()`/`disable()`."""

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class SkillMetadata:
    """
    The full metadata a skill exposes, per Milestone 3 Part 5.

    A snapshot, not a live view — built on demand from a `BaseSkill`
    instance via `BaseSkill.metadata()` so callers (the skill loader,
    `SkillEngine.list_available()`, future UIs) have one stable shape to
    report on, regardless of how a specific skill implements its
    properties.
    """

    name: str
    description: str
    version: str
    author: str
    category: SkillCategory
    required_modules: tuple[str, ...]
    dependencies: tuple[str, ...]
    permissions: tuple[Permission, ...]
    confidence: float


@dataclass
class SkillContext:
    """
    Dependency-injection bundle passed into `BaseSkill.execute()`.

    Design decision: skills receive this small, explicit bundle of
    subsystems instead of the full `SmartAgent` instance. Two reasons:
    (1) it keeps `smartagent.skills` from importing `smartagent.brain.agent`
    at all — avoiding a circular import, since `agent.py` constructs the
    skill engine — and (2) it makes each skill's `required_modules`
    declaration meaningful: a skill can only reach the subsystems this
    context actually hands it, not the entire agent.
    """

    memory: "MemoryManager"
    tools: "ToolRegistry"
    goals: "GoalManager"
    research: "ResearchManager"
    model: "ModelClient"
    settings: "Settings"
    events: "EventBus | None" = None
    tool_engine: "ToolEngine | None" = None
    module_names: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)


class BaseSkill(ABC):
    """
    Abstract base class every SmartAgent skill implements.

    Required properties (Milestone 3 Part 2): `name`, `description`,
    `version`, `author`, `required_modules`. Required methods: `execute()`,
    `validate()`, `status()`.

    `category`, `dependencies`, `permissions`, and `confidence` (Part 5's
    extra metadata fields) are given sensible, overridable defaults
    rather than being abstract — most skills only need to override
    `permissions` (almost always non-empty and safety-relevant) and
    `category`, without also being forced to restate empty
    `dependencies`/a default `confidence` every time.
    """

    #: Runtime enabled/disabled flag. `SkillRegistry.enable()`/`disable()`
    #: flip this rather than removing/re-adding the skill instance, so a
    #: disabled skill's state (if any) survives being turned back on.
    _status: SkillStatus = SkillStatus.ENABLED

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, machine-readable identifier for this skill."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this skill does."""
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string for this skill, independent of the project's own version."""
        raise NotImplementedError

    @property
    @abstractmethod
    def author(self) -> str:
        """Who wrote/owns this skill (e.g. "SmartAgent Core Team" for built-ins)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def required_modules(self) -> tuple[str, ...]:
        """
        Names of `SkillContext` subsystems this skill depends on (e.g. `("memory",)`).

        Documentation/introspection only — `SkillContext` always carries
        every subsystem, so this does not currently gate execution the
        way `permissions` does. It exists so a future skill loader or
        health check can report "this skill needs planning, which isn't
        available" without executing the skill to find out.
        """
        raise NotImplementedError

    @property
    def category(self) -> SkillCategory:
        """Coarse category for discovery/reporting. Defaults to `GENERAL`."""
        return SkillCategory.GENERAL

    @property
    def dependencies(self) -> tuple[str, ...]:
        """Names of other skills this one expects to also be registered. Defaults to none."""
        return ()

    @property
    def permissions(self) -> tuple[Permission, ...]:
        """
        Permissions this skill needs to run (Milestone 3 Part 6).

        Defaults to none. Any skill that touches memory, tools, files,
        the network, automation, or system commands must override this —
        `SkillEngine` refuses to execute a skill whose declared
        permissions aren't all granted, regardless of what the skill's
        code would otherwise do.
        """
        return ()

    @property
    def confidence(self) -> float:
        """
        Default self-reported confidence (0.0-1.0) when this skill matches a request.

        Used by `SkillEngine` to order multiple matching skills, most
        confident first. Defaults to a middling 0.5; built-ins override
        this to reflect how narrowly/reliably their `validate()` matches.
        """
        return 0.5

    def metadata(self) -> SkillMetadata:
        """Build a `SkillMetadata` snapshot of this skill's declared properties."""
        return SkillMetadata(
            name=self.name,
            description=self.description,
            version=self.version,
            author=self.author,
            category=self.category,
            required_modules=tuple(self.required_modules),
            dependencies=tuple(self.dependencies),
            permissions=tuple(self.permissions),
            confidence=self.confidence,
        )

    @abstractmethod
    def validate(self, message: str) -> bool:
        """Whether this skill can meaningfully handle `message`. Must be side-effect free."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, message: str, context: SkillContext) -> Any:
        """
        Perform this skill's capability for `message` and return a result.

        Return value is whatever is most natural for the skill to
        produce (a string, a dict, a dataclass, ...) — `SkillEngine` is
        responsible for wrapping it into a standardized `ActionResult`,
        not the skill itself. This keeps individual skills simple and
        free of Brain-specific plumbing.
        """
        raise NotImplementedError

    def status(self) -> SkillStatus:
        """Current enabled/disabled status. Managed by `SkillRegistry`, not the skill itself."""
        return self._status
