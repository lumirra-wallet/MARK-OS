"""
BrainRouter — Milestone 2 Brain v2, Part 1.

Implements the fixed request pipeline every user message passes through:

    Receive User Input
        -> Intent Analyzer
        -> Decision Engine
        -> Select Module (Module Registry)
        -> Execute
        -> Return Response

Design decision: the router never performs a task itself. It only
classifies intent, asks the Decision Engine for an ordered list of
candidate modules, and asks each candidate (via the Module Registry) to
handle the message until one reports success — a chain-of-responsibility
that generalizes Milestone 1's hardcoded "check memory, then fall back to
the model" logic into something any number of registered modules can
participate in, in a configurable priority order.
"""

from __future__ import annotations

import time

from smartagent.brain.action_result import ActionResult
from smartagent.brain.decision_engine import DecisionEngine
from smartagent.brain.events import Events, EventBus
from smartagent.brain.intent_analyzer import IntentAnalyzer
from smartagent.brain.module_registry import ModuleRegistry
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


class BrainRouter:
    """
    Routes every request through Intent Analyzer -> Decision Engine -> Module Registry -> Execute.

    Args:
        registry: The `ModuleRegistry` describing which modules are
            available and how to reach them. Owned by whoever constructs
            the router (typically `SmartAgent`) so different deployments
            can register a different set of modules.
        intent_analyzer: Classifier used to tag each request. Defaults to
            a fresh rule-based `IntentAnalyzer`.
        decision_engine: Strategy used to order candidate modules for a
            given intent. Defaults to a fresh `DecisionEngine`.
        event_bus: Bus to publish routing events onto. Defaults to a
            fresh, private `EventBus` if the caller doesn't share one —
            sharing one (e.g. the same bus used by `MemoryManager`) lets
            subscribers see the full picture of what the Brain is doing.
    """

    def __init__(
        self,
        registry: ModuleRegistry,
        intent_analyzer: IntentAnalyzer | None = None,
        decision_engine: DecisionEngine | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.registry = registry
        self.intent_analyzer = intent_analyzer or IntentAnalyzer()
        self.decision_engine = decision_engine or DecisionEngine()
        self.events = event_bus or EventBus()

    def route(self, message: str) -> ActionResult:
        """Run `message` through the full Brain v2 pipeline and return the winning `ActionResult`."""
        start = time.monotonic()
        self.events.publish(Events.REQUEST_RECEIVED, message=message)

        intent = self.intent_analyzer.analyze(message)
        candidates = self.decision_engine.decide(intent, self.registry)

        result: ActionResult | None = None
        chosen_module = "unknown"
        for module_name in candidates:
            handler = self.registry.get(module_name)
            if handler is None:
                continue
            result = handler(message)
            chosen_module = module_name
            if result.success:
                # First module that can actually help wins — later,
                # lower-priority candidates are never even asked.
                break

        if result is None:
            # No module at all was registered: a configuration problem,
            # not a normal "nothing matched" case. Still return a valid
            # ActionResult so callers never have to null-check the router.
            result = ActionResult(
                success=False,
                message="No modules are registered with the Brain.",
                source="brain_router",
            )

        execution_time = time.monotonic() - start
        # Prefer the module's own timing if it reported one; otherwise
        # fall back to the router's end-to-end measurement.
        result.execution_time = result.execution_time or execution_time

        # Part 7: log every Brain decision (timestamp comes from the
        # logging formatter itself, see smartagent.logs.logger).
        logger.info(
            "intent=%s chosen_module=%s execution_time=%.4fs success=%s",
            intent.value,
            chosen_module,
            execution_time,
            result.success,
        )
        self.events.publish(
            Events.BRAIN_DECISION_MADE,
            intent=intent.value,
            module=chosen_module,
            success=result.success,
            execution_time=execution_time,
        )
        return result
