"""
Tool registry and base tool interface.

Defines the common `Tool` abstraction that all SmartAgent tools implement,
plus a `ToolRegistry` that the core agent uses to discover and invoke
tools by name. No concrete tools are implemented yet — this module just
establishes the contract future tools (web search, calculator, file
access, etc.) will follow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """
    Base class for all SmartAgent tools.

    Concrete tools (e.g. a web search tool, a calculator tool) should
    subclass this and implement `name`, `description`, and `run`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, machine-readable identifier for this tool."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this tool does, for the agent's reasoning step."""
        raise NotImplementedError

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the tool with the given arguments and return a result."""
        raise NotImplementedError


class ToolRegistry:
    """
    Holds the set of tools currently available to the agent.

    Args:
        enabled_tools: Names of tools that should be active. Currently
            unused since no concrete tools exist yet — kept so
            `SmartAgent` has a stable constructor signature to build
            against.
    """

    def __init__(self, enabled_tools: list[str] | None = None) -> None:
        self.enabled_tools = enabled_tools or []
        # TODO: populate with real Tool instances once they exist, e.g.:
        #   self._tools: dict[str, Tool] = {t.name: t for t in [...]}
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add a tool to the registry, making it callable by name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Look up a registered tool by name, or None if not found."""
        return self._tools.get(name)

    def list_available(self) -> list[str]:
        """Return the names of all currently registered tools."""
        return list(self._tools.keys())
