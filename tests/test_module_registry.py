"""Tests for `ModuleRegistry`."""

from smartagent.brain.action_result import ActionResult
from smartagent.brain.module_registry import ModuleRegistry


def _echo_handler(message: str) -> ActionResult:
    return ActionResult(success=True, message=message, source="echo")


def test_register_and_get():
    registry = ModuleRegistry()
    registry.register("echo", _echo_handler)

    handler = registry.get("echo")
    assert handler is not None
    assert handler("hi").message == "hi"


def test_is_registered():
    registry = ModuleRegistry()
    assert registry.is_registered("echo") is False
    registry.register("echo", _echo_handler)
    assert registry.is_registered("echo") is True


def test_get_unknown_module_returns_none():
    registry = ModuleRegistry()
    assert registry.get("does-not-exist") is None


def test_list_modules_returns_registered_names():
    registry = ModuleRegistry()
    registry.register("echo", _echo_handler)
    registry.register("memory", _echo_handler)
    assert set(registry.list_modules()) == {"echo", "memory"}


def test_unregister_removes_a_module():
    registry = ModuleRegistry()
    registry.register("echo", _echo_handler)
    registry.unregister("echo")
    assert registry.is_registered("echo") is False


def test_unregister_missing_module_is_a_no_op():
    registry = ModuleRegistry()
    registry.unregister("does-not-exist")  # should not raise
