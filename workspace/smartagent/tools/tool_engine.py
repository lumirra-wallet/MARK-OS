"""
ToolEngine — Milestone 4, Part 1.

The single thing Skills talk to for anything tool-related:

    Skill.execute()
        -> SkillContext.tool_engine.run("file_read", ctx, path="...")
            -> ToolEngine.run()
                -> (permission check, find tool, execute)
                -> ActionResult

The Brain never calls ``ToolEngine`` directly — only Skills do (via
``SkillContext.tool_engine``), and the Brain's ``tools`` module handler
remains a reporting endpoint that lists what's available.

Dispatch strategy mirrors ``SkillEngine``:
- Locate the tool by id.
- Deny if not enabled.
- Deny if declared permissions are not all granted.
- Validate params; deny if ``validate()`` returns False.
- Time execution; wrap result in ``ActionResult``.
- Publish ``ToolExecuted`` onto the shared ``EventBus``.
- Never raise — all errors surface as ``success=False`` ``ActionResult``s.
"""

from __future__ import annotations

import time
from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.brain.events import Events, EventBus
from smartagent.logs.logger import get_logger
from smartagent.skills.permissions import PermissionManager
from smartagent.tools.base_tool import BaseTool, ToolContext
from smartagent.tools.tool_loader import DEFAULT_TOOLS_PACKAGE, discover_tool_classes
from smartagent.tools.tool_registry import ToolRegistry

logger = get_logger(__name__)


class ToolEngine:
    """
    Registers, loads, and executes tools on a Skill's behalf (Part 1).

    Args:
        registry: Where tools live. Owned by whoever constructs the engine
            (typically ``SmartAgent``) so the same registry can be inspected
            outside the engine (e.g. ``agent.tools.list_available()``).
        permissions: Authority for whether a tool's declared permissions are
            currently granted. Shared with ``SkillEngine`` — one
            ``PermissionManager`` governs both layers.
        event_bus: Optional bus to publish ``ToolExecuted`` / ``ToolLoaded``
            onto. Shared with the rest of the agent so subscribers see tool
            activity alongside skill and memory events.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        permissions: PermissionManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.permissions = permissions or PermissionManager()
        self.events = event_bus

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool: BaseTool) -> None:
        """Register a single tool instance. Logs ``"Tool Loaded"`` (Part 10)."""
        self.registry.register(tool)
        logger.info("Tool Loaded: %s (%s)", tool.id, tool.name)
        if self.events is not None:
            self.events.publish(Events.TOOL_LOADED, tool_id=tool.id, tool_name=tool.name)

    def load_tools(self, package: str = DEFAULT_TOOLS_PACKAGE) -> list[str]:
        """
        Discover and register every built-in tool class found in ``package``.

        Uses ``discover_tool_classes()`` (Part 4) — no hardcoded imports.
        Returns the ids of every tool registered this call.
        """
        registered: list[str] = []
        for tool_class in discover_tool_classes(package):
            tool = tool_class()
            self.register(tool)
            registered.append(tool.id)
        return registered

    def list_available(self) -> list[str]:
        """Ids of every registered tool (enabled or not) — used for reporting."""
        return self.registry.list_available()

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        tool_id: str,
        context: ToolContext,
        **params: Any,
    ) -> ActionResult:
        """
        Execute the tool identified by ``tool_id`` with the given ``params``.

        Args:
            tool_id: The tool's ``id`` property (e.g. ``"file_read"``).
            context: Dependency-injection bundle for the tool (workspace path,
                settings, event bus). Build this from ``SkillContext`` — see
                ``module_bindings._build_tool_context()``.
            **params: Keyword arguments forwarded to the tool as a dict.

        Returns:
            An ``ActionResult`` describing the outcome.  Never raises —
            errors are wrapped into a ``success=False`` result.
        """
        tool = self.registry.find(tool_id)

        # --- Unknown tool -----------------------------------------------
        if tool is None:
            logger.warning("Tool Execution Failed: unknown tool id %r", tool_id)
            return ActionResult(
                success=False,
                message=f"No tool registered with id {tool_id!r}.",
                source="tool_engine",
            )

        # --- Disabled tool -----------------------------------------------
        if not self.registry.is_enabled(tool_id):
            logger.warning("Tool Execution Failed: tool %r is disabled", tool_id)
            return ActionResult(
                success=False,
                message=f"Tool {tool_id!r} is currently disabled.",
                source=tool_id,
            )

        # --- Permission check -------------------------------------------
        missing = self.permissions.missing(tool.permissions)
        if missing:
            missing_names = ", ".join(p.value for p in missing)
            logger.info(
                "Permission Requests: tool %r needs %s (not granted)", tool_id, missing_names
            )
            logger.warning(
                "Tool Execution Failed: %r denied — missing permissions: %s",
                tool_id,
                missing_names,
            )
            return ActionResult(
                success=False,
                message=(
                    f"Tool {tool_id!r} requires permissions that have not been "
                    f"granted: {missing_names}."
                ),
                source=tool_id,
            )

        # --- Param validation -------------------------------------------
        if not tool.validate(params):
            logger.warning(
                "Tool Execution Failed: %r rejected params %s", tool_id, list(params.keys())
            )
            return ActionResult(
                success=False,
                message=(
                    f"Tool {tool_id!r} rejected the supplied parameters. "
                    f"Check the required fields: {list(params.keys())}."
                ),
                source=tool_id,
            )

        # --- Execute --------------------------------------------------------
        start = time.monotonic()
        try:
            result = tool.execute(params, context)
        except Exception as exc:  # noqa: BLE001 — a failing tool must not crash the Skill
            elapsed = time.monotonic() - start
            logger.warning(
                "Tool Execution Failed: %r raised %s: %s", tool_id, type(exc).__name__, exc
            )
            return ActionResult(
                success=False,
                message=f"Tool {tool_id!r} raised an unexpected error: {exc}",
                source=tool_id,
                execution_time=elapsed,
            )
        elapsed = time.monotonic() - start

        # Ensure source and timing are set even when the tool omits them
        if not result.source:
            result.source = tool_id
        if result.execution_time == 0.0:
            result.execution_time = elapsed

        self.registry.record_execution(tool_id)

        # --- Logging --------------------------------------------------------
        if result.success:
            logger.info(
                "Tool Executed: %s success=True execution_time=%.4fs", tool_id, elapsed
            )
        else:
            logger.warning(
                "Tool Execution Failed: %s success=False execution_time=%.4fs — %s",
                tool_id,
                elapsed,
                result.message,
            )

        # --- Event publishing -----------------------------------------------
        if self.events is not None:
            self.events.publish(
                Events.TOOL_EXECUTED,
                tool_id=tool_id,
                success=result.success,
                execution_time=elapsed,
            )

        return result

    # ------------------------------------------------------------------
    # Health / reporting
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Delegate to ``ToolRegistry.health_check()`` and return its report."""
        return self.registry.health_check()

    def describe(self) -> str:
        """
        Return a one-line human-readable summary of registered tools.

        Used by ``module_bindings.tools_handler`` to answer "what tools do
        you have?" questions from the Brain without executing anything.
        """
        available = self.list_available()
        if not available:
            return "No tools are currently registered."
        return (
            f"{len(available)} tool(s) available: {', '.join(available)}. "
            "Tools are invoked by Skills, not directly via free-text requests."
        )
