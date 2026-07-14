"""
Skill registry and base skill interface.

Defines the common `Skill` abstraction that all SmartAgent skills
implement, plus a `SkillRegistry` the core agent uses to discover and
invoke skills by name. No concrete skills are implemented yet — this
module only establishes the contract future skills will follow.

A skill differs from a tool (see `smartagent.tools.tool_registry`) in that
a skill represents a complete user-facing capability that may internally
use memory, one or more tools, and the language model to get its job
done, whereas a tool is a single, low-level action.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Skill(ABC):
    """
    Base class for all SmartAgent skills.

    Concrete skills (e.g. "set a reminder", "summarize recent notes")
    should subclass this and implement `name`, `description`, and
    `execute`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, machine-readable identifier for this skill."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this skill does, for the agent's reasoning step."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Perform the skill with the given arguments and return a result."""
        raise NotImplementedError


class SkillRegistry:
    """Holds the set of skills currently available to the agent."""

    def __init__(self) -> None:
        # TODO: populate with real Skill instances once they exist, e.g.:
        #   self._skills: dict[str, Skill] = {s.name: s for s in [...]}
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Add a skill to the registry, making it callable by name."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """Look up a registered skill by name, or None if not found."""
        return self._skills.get(name)

    def list_available(self) -> list[str]:
        """Return the names of all currently registered skills."""
        return list(self._skills.keys())
