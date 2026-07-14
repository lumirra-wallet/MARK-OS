"""
Tests for the tool interface and `ToolRegistry`.

No concrete tools exist yet, so these tests only exercise the registry
mechanics (register/get/list) against a minimal dummy tool.
"""

from typing import Any

from smartagent.tools.tool_registry import Tool, ToolRegistry


class _EchoTool(Tool):
    """Minimal concrete `Tool` used only for testing the registry."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Returns whatever input it is given."

    def run(self, **kwargs: Any) -> Any:
        return kwargs.get("text")


def test_register_and_get_tool():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    tool = registry.get("echo")
    assert tool is not None
    assert tool.run(text="hi") == "hi"


def test_list_available_returns_registered_names():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    assert registry.list_available() == ["echo"]


def test_get_unknown_tool_returns_none():
    registry = ToolRegistry()
    assert registry.get("does-not-exist") is None
