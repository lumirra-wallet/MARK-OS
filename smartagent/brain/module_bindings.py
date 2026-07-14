"""
Module bindings — wires each SmartAgent subsystem into the Brain's `ModuleRegistry`.

Design decision: this is the *only* file that imports both `brain`
(`ActionResult`/`ModuleRegistry`) and every capability subpackage (memory,
skills, tools, planning, research, models, voice, vision, automation).
Concentrating that dependency here — rather than having each subpackage
import back into `brain` to "self-register" — avoids a circular import
(`brain.agent` already depends on those subpackages to construct them;
having them depend back on `brain.action_result` would invert that) while
still satisfying Milestone 2's Part 4 requirement that the Brain's control
flow (`BrainRouter`, `DecisionEngine`) never hardcodes module *names* —
only this wiring step knows which concrete subsystem sits behind each
registry name.

Every handler here is intentionally a thin, honest, read-only probe for
now: none of skills/tools/planning/research/voice/vision/automation can
act on arbitrary free text yet (teaching them to would be a new feature —
out of scope per the Milestone 2 rule "Do NOT add random features"), so
each one reports it has nothing to offer (`success=False`) except where
real behavior already exists (memory search, and the model call which at
least tries before hitting its `NotImplementedError`). The final
`unknown` module always succeeds, guaranteeing `BrainRouter`'s
chain-of-responsibility always terminates with *some* response.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from smartagent.brain.action_result import ActionResult
from smartagent.brain.module_registry import ModuleRegistry
from smartagent.models.manager.model_manager import NoActiveModelError

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

# What each subsystem probe returns before it's wrapped into a timed
# ActionResult: (success, message, data).
_ProbeResult = tuple[bool, str, Any]


def _timed(source: str, confidence: float, probe: Callable[[], _ProbeResult]) -> ActionResult:
    """Run `probe`, time it, and wrap its outcome into a standardized `ActionResult`."""
    start = time.monotonic()
    success, message, data = probe()
    elapsed = time.monotonic() - start
    return ActionResult(
        success=success,
        message=message,
        data=data,
        source=source,
        execution_time=elapsed,
        confidence=confidence if success else 0.0,
    )


def _probe_memory(agent: "SmartAgent", message: str) -> _ProbeResult:
    hits = agent.memory.search(message, limit=3)
    if not hits:
        return False, "No relevant memory found.", []
    recalled = "; ".join(hit.content for hit in hits)
    return True, f"Here's what I remember: {recalled}", hits


def _build_skill_context(agent: "SmartAgent") -> "SkillContext":
    """
    Build a fresh `SkillContext` for one skill dispatch.

    Built per-call (not cached) so `module_names`/`skill_names` always
    reflect whatever is registered *right now* — cheap since it's just
    bundling references the agent already owns, not copying any data.

    Milestone 4: `tool_engine` is now included so Skills can call
    `context.tool_engine.run(tool_id, tool_ctx, **params)` without a
    direct dependency on `SmartAgent` or any concrete tool class.
    """
    from smartagent.skills.base_skill import SkillContext

    return SkillContext(
        memory=agent.memory,
        tools=agent.tools,
        goals=agent.goals,
        research=agent.research,
        model=agent.model,
        settings=agent.settings,
        events=agent.events,
        tool_engine=agent.tool_engine,
        module_names=agent.modules.list_modules(),
        skill_names=agent.skill_engine.list_available(),
    )


def register_default_modules(registry: ModuleRegistry, agent: "SmartAgent") -> None:
    """
    Register a handler for every subsystem `agent` owns.

    Called once from `SmartAgent.__init__`. Kept as a free function (not a
    method on `SmartAgent`) so the wiring logic — and the reasoning behind
    each module's placeholder behavior — lives in one dedicated, testable
    place.
    """
    agent_name = agent.settings.agent_name

    def memory_handler(message: str) -> ActionResult:
        return _timed("memory", 0.8, lambda: _probe_memory(agent, message))

    def skills_handler(message: str) -> ActionResult:
        # Milestone 3: the Brain no longer probes skills directly — it
        # only ever asks the Skill Engine, which owns picking (and
        # permission-checking) the actual matching skill. This keeps the
        # Brain's control flow unaware of how any specific skill works.
        return agent.skill_engine.execute(message, _build_skill_context(agent))

    def tools_handler(message: str) -> ActionResult:
        # Milestone 4: report what's available via ToolEngine.  The Brain
        # cannot route NL text to a specific tool without an AI model, so
        # this handler remains success=False (skills are the routing layer).
        # confidence=0.0 ensures the Brain never stops here on success.
        available = agent.tool_engine.list_available()
        msg = agent.tool_engine.describe()
        return _timed("tools", 0.0, lambda: (False, msg, available))

    def planning_handler(message: str) -> ActionResult:
        return _timed(
            "planning",
            0.5,
            lambda: (False, "Planning has no goal matching this request yet.", agent.goals.list_goals()),
        )

    def research_handler(message: str) -> ActionResult:
        return _timed(
            "research",
            0.5,
            lambda: (
                False,
                "Research requires an explicit topic and owner approval; not wired to free-text requests yet.",
                agent.research.list_pending(),
            ),
        )

    def model_handler(message: str) -> ActionResult:
        # Milestone 5: routed through `ModelManager`, never a provider or
        # the legacy `ModelClient` directly (Part 11). Out of the box no
        # default model is configured (`Settings.default_model_id == ""`),
        # so this raises `NoActiveModelError` and honestly reports
        # `success=False`, exactly like the old `ModelClient.generate()`
        # raising `NotImplementedError` — preserving the fallback chain's
        # existing behavior until a deployment opts into a real model.
        def probe() -> _ProbeResult:
            try:
                response = agent.model_manager.generate(message)
            except NoActiveModelError as exc:
                return False, str(exc), None
            return True, response.text, response

        return _timed("model", 0.4, probe)

    def voice_handler(message: str) -> ActionResult:
        return _timed("voice", 0.3, lambda: (False, "Voice input/output is not implemented yet.", None))

    def vision_handler(message: str) -> ActionResult:
        return _timed("vision", 0.3, lambda: (False, "Vision is not implemented yet.", None))

    def automation_handler(message: str) -> ActionResult:
        return _timed(
            "automation",
            0.3,
            lambda: (False, "Automation is not implemented yet.", agent.automation.list_tasks()),
        )

    def unknown_handler(message: str) -> ActionResult:
        # Guaranteed final fallback (Decision Engine priority #7): always
        # succeeds so BrainRouter's chain never comes back empty-handed.
        return ActionResult(
            success=True,
            message=f"[{agent_name} placeholder] You said: {message}",
            data=None,
            source="unknown",
            execution_time=0.0,
            confidence=0.1,
        )

    registry.register("memory", memory_handler)
    registry.register("skills", skills_handler)
    registry.register("tools", tools_handler)
    registry.register("planning", planning_handler)
    registry.register("research", research_handler)
    registry.register("model", model_handler)
    registry.register("voice", voice_handler)
    registry.register("vision", vision_handler)
    registry.register("automation", automation_handler)
    registry.register("unknown", unknown_handler)
