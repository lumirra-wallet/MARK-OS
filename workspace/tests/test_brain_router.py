"""
Tests for `BrainRouter`.

Uses small hand-built `ModuleRegistry` instances (not a full `SmartAgent`)
so the router's chain-of-responsibility behavior can be tested in
isolation from any real subsystem.
"""

from smartagent.brain.action_result import ActionResult
from smartagent.brain.events import Events
from smartagent.brain.module_registry import ModuleRegistry
from smartagent.brain.router import BrainRouter


def _failing(source: str):
    def handler(message: str) -> ActionResult:
        return ActionResult(success=False, message=f"{source} could not handle it", source=source)

    return handler


def _succeeding(source: str):
    def handler(message: str) -> ActionResult:
        return ActionResult(success=True, message=f"{source} handled it", source=source)

    return handler


def test_router_picks_the_first_successful_module_in_priority_order():
    registry = ModuleRegistry()
    registry.register("memory", _failing("memory"))
    registry.register("model", _succeeding("model"))
    registry.register("unknown", _succeeding("unknown"))

    router = BrainRouter(registry)
    result = router.route("hello")

    assert result.success is True
    assert result.source == "model"


def test_router_falls_back_to_unknown_when_nothing_else_succeeds():
    registry = ModuleRegistry()
    registry.register("memory", _failing("memory"))
    registry.register("unknown", _succeeding("unknown"))

    router = BrainRouter(registry)
    result = router.route("hello")

    assert result.source == "unknown"
    assert result.success is True


def test_router_returns_a_result_even_with_no_registered_modules():
    registry = ModuleRegistry()
    router = BrainRouter(registry)

    result = router.route("hello")

    assert result.success is False
    assert result.source == "brain_router"


def test_router_publishes_events_for_every_request():
    registry = ModuleRegistry()
    registry.register("unknown", _succeeding("unknown"))
    router = BrainRouter(registry)

    router.route("hello")

    names = [event.name for event in router.events.history()]
    assert Events.REQUEST_RECEIVED in names
    assert Events.BRAIN_DECISION_MADE in names


def test_router_records_execution_time():
    registry = ModuleRegistry()
    registry.register("unknown", _succeeding("unknown"))
    router = BrainRouter(registry)

    result = router.route("hello")

    assert result.execution_time >= 0.0
