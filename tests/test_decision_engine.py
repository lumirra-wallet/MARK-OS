"""Tests for `DecisionEngine`."""

from smartagent.brain.action_result import ActionResult
from smartagent.brain.decision_engine import DecisionEngine, DECISION_PRIORITY
from smartagent.brain.intent_analyzer import Intent
from smartagent.brain.module_registry import ModuleRegistry


def _noop_handler(message: str) -> ActionResult:
    return ActionResult(success=True, message=message)


def test_decide_returns_only_registered_modules_in_priority_order():
    registry = ModuleRegistry()
    registry.register("model", _noop_handler)
    registry.register("memory", _noop_handler)
    registry.register("unknown", _noop_handler)

    candidates = DecisionEngine().decide(Intent.UNKNOWN, registry)

    # Order must follow DECISION_PRIORITY, not registration order.
    assert candidates == ["memory", "model", "unknown"]


def test_decide_excludes_unregistered_modules():
    registry = ModuleRegistry()
    registry.register("memory", _noop_handler)

    candidates = DecisionEngine().decide(Intent.MEMORY, registry)

    assert candidates == ["memory"]


def test_decide_returns_empty_list_when_nothing_registered():
    registry = ModuleRegistry()
    assert DecisionEngine().decide(Intent.UNKNOWN, registry) == []


def test_decision_priority_matches_the_milestone_2_spec():
    assert DECISION_PRIORITY == ("memory", "skills", "tools", "planning", "research", "model", "unknown")
