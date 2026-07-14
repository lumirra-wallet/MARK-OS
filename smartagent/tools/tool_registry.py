"""
ToolRegistry — Milestone 4, Part 3.

Backward compatibility note
---------------------------
The Milestone 1 placeholder ``tool_registry`` exported a ``Tool`` ABC (with
``name``, ``description``, and ``run()`` abstract methods) and a
``ToolRegistry.get(name)`` method. Both are preserved as-is so the three
existing placeholder tests (and any external code) continue working without
modification. New tools should use ``BaseTool`` from ``base_tool.py``.


Upgrades the Milestone 1 placeholder registry (which only supported
``register``/``get``/``list_available`` for the old ``Tool`` ABC with a
``run()`` method) into a full production-ready container: register,
unregister, find, list, reload, enable, disable, health_check, statistics.

Design mirrors ``SkillRegistry`` exactly: each tool's *factory* (default:
``type(tool)``, a zero-arg constructor) is stored alongside its live
instance so ``reload()`` can re-instantiate without mutating the object in
place.

Backward compatibility:
    - Constructor still accepts ``enabled_tools: list[str] | None`` (ignored
      for execution gating but stored so ``SmartAgent.__init__`` doesn't
      need changes).
    - ``list_available()`` still returns ``list[str]`` of tool ids.
    - The old ``Tool`` ABC (with ``run()``) is re-exported as a deprecated
      alias; new code should use ``BaseTool`` from ``base_tool.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from smartagent.logs.logger import get_logger
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolStatus

# ---------------------------------------------------------------------------
# Legacy Tool ABC — kept for backward compatibility with Milestone 1 code.
# New tools should subclass BaseTool from smartagent.tools.base_tool instead.
# ---------------------------------------------------------------------------


class Tool(ABC):
    """
    **Deprecated** base class for SmartAgent tools.

    Kept so that Milestone 1 / Milestone 2 code (and the tests written
    against that era) can continue to import ``Tool`` from this module
    without modification.  Use ``BaseTool`` for all new development.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, machine-readable identifier for this tool."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this tool does."""
        raise NotImplementedError

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        """Execute the tool with the given arguments and return a result."""
        raise NotImplementedError

logger = get_logger(__name__)

ToolFactory = Callable[[], BaseTool]


class ToolRegistry:
    """
    Holds every tool currently known to SmartAgent, enabled or not.

    Args:
        enabled_tools: Kept for backward compatibility with code that passes
            ``enabled_tools=settings.enabled_tools`` to the constructor.
            In Milestone 4 the registry enables/disables tools via
            ``enable()``/``disable()``, not this list — all registered tools
            start enabled by default.
    """

    def __init__(self, enabled_tools: list[str] | None = None) -> None:
        self.enabled_tools = enabled_tools or []
        self._tools: dict[str, BaseTool] = {}
        self._factories: dict[str, ToolFactory] = {}
        self._status: dict[str, ToolStatus] = {}
        self._execution_count: dict[str, int] = {}
        # Legacy storage for old Tool (ABC with run()) instances.
        self._legacy: dict[str, Tool] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, tool: "BaseTool | Tool", factory: ToolFactory | None = None) -> None:
        """
        Add ``tool`` to the registry, enabled by default.

        Accepts both:
        - New-style ``BaseTool`` instances (registered under ``tool.id``).
        - Legacy ``Tool`` instances (registered under ``tool.name`` in a
          separate store; accessible via ``get()`` for backward compat).

        Args:
            tool: A ``BaseTool`` or legacy ``Tool`` instance.
            factory: Zero-arg callable for ``reload()``. Defaults to
                ``type(tool)``. Only used for ``BaseTool`` registrations.
        """
        if isinstance(tool, BaseTool):
            self._tools[tool.id] = tool
            self._factories[tool.id] = factory or type(tool)
            self._status[tool.id] = ToolStatus.ENABLED
            self._execution_count[tool.id] = 0
            tool.initialize()
            logger.info(
                "Tool registered: %s (%s v%s by %s)",
                tool.id,
                tool.name,
                tool.version,
                tool.author,
            )
        else:
            # Legacy Tool (Milestone 1 interface) — store separately.
            self._legacy[tool.name] = tool
            logger.info("Legacy tool registered: %s", tool.name)

    def unregister(self, tool_id: str) -> None:
        """
        Remove a tool entirely and call its ``shutdown()`` hook.

        A no-op if ``tool_id`` is not registered.
        """
        tool = self._tools.pop(tool_id, None)
        self._factories.pop(tool_id, None)
        self._status.pop(tool_id, None)
        self._execution_count.pop(tool_id, None)
        if tool is not None:
            tool.shutdown()
            logger.info("Tool unregistered: %s", tool_id)

    def find(self, tool_id: str) -> BaseTool | None:
        """Look up a single registered tool by exact id, or ``None`` if not found."""
        return self._tools.get(tool_id)

    def list(
        self,
        enabled_only: bool = True,
        category: ToolCategory | None = None,
    ) -> list[BaseTool]:
        """
        List registered tools, optionally filtered to enabled-only and/or by category.

        Args:
            enabled_only: When ``True`` (default), only enabled tools are returned.
            category: When given, only tools in this category are returned.

        Returns:
            The filtered list of ``BaseTool`` instances.
        """
        tools = list(self._tools.values())
        if enabled_only:
            tools = [t for t in tools if self._status.get(t.id) == ToolStatus.ENABLED]
        if category is not None:
            tools = [t for t in tools if t.category == category]
        return tools

    def reload(self, tool_id: str) -> BaseTool | None:
        """
        Re-instantiate a tool from its stored factory, replacing the old instance.

        Calls ``shutdown()`` on the old instance and ``initialize()`` on the
        new one. Preserves the tool's current enabled/disabled status.

        Returns:
            The fresh ``BaseTool`` instance, or ``None`` if ``tool_id`` is
            not registered.
        """
        factory = self._factories.get(tool_id)
        if factory is None:
            return None
        old_tool = self._tools.get(tool_id)
        if old_tool is not None:
            old_tool.shutdown()
        previous_status = self._status.get(tool_id, ToolStatus.ENABLED)
        fresh = factory()
        self._tools[tool_id] = fresh
        self._status[tool_id] = previous_status
        fresh.initialize()
        logger.info("Tool reloaded: %s", tool_id)
        return fresh

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    def enable(self, tool_id: str) -> bool:
        """
        Mark a registered tool as enabled.

        Returns:
            ``True`` if the tool was found and enabled, ``False`` if it was
            not registered.
        """
        if tool_id not in self._tools:
            return False
        self._status[tool_id] = ToolStatus.ENABLED
        logger.info("Tool enabled: %s", tool_id)
        return True

    def disable(self, tool_id: str) -> bool:
        """
        Mark a registered tool as disabled (excluded from ``list(enabled_only=True)``).

        Returns:
            ``True`` if the tool was found and disabled, ``False`` if it was
            not registered.
        """
        if tool_id not in self._tools:
            return False
        self._status[tool_id] = ToolStatus.DISABLED
        logger.info("Tool disabled: %s", tool_id)
        return True

    def is_enabled(self, tool_id: str) -> bool:
        """Whether ``tool_id`` is registered and currently enabled."""
        return self._status.get(tool_id) == ToolStatus.ENABLED

    # ------------------------------------------------------------------
    # Health and statistics
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """
        Collect and return a health snapshot for every registered tool.

        Returns:
            A dict mapping each tool id to that tool's ``health()`` output,
            plus a top-level ``"healthy"`` key that is ``True`` only if
            every tool reports healthy.
        """
        per_tool: dict[str, Any] = {}
        all_healthy = True
        for tool_id, tool in self._tools.items():
            report = tool.health()
            # Respect current enabled/disabled status over tool's own report
            report["status"] = self._status.get(tool_id, ToolStatus.ENABLED).value
            per_tool[tool_id] = report
            if not report.get("healthy", True):
                all_healthy = False
        return {"healthy": all_healthy, "tools": per_tool}

    def statistics(self) -> dict[str, Any]:
        """
        Return registry-level statistics.

        Returns:
            Total, enabled, and disabled tool counts; per-tool execution
            counts accumulated via ``record_execution()``.
        """
        total = len(self._tools)
        enabled = sum(
            1 for s in self._status.values() if s == ToolStatus.ENABLED
        )
        return {
            "total": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "execution_counts": dict(self._execution_count),
        }

    def record_execution(self, tool_id: str) -> None:
        """Increment the execution counter for ``tool_id``. Called by ``ToolEngine``."""
        if tool_id in self._execution_count:
            self._execution_count[tool_id] += 1

    # ------------------------------------------------------------------
    # Backward-compatible interface
    # ------------------------------------------------------------------

    def get(self, name: str) -> "BaseTool | Tool | None":
        """
        Look up a registered tool by name/id.

        Checks the new ``BaseTool`` store (by id) first, then the legacy
        ``Tool`` store (by name). Returns ``None`` if nothing is found in
        either store.

        Kept for backward compatibility with Milestone 1 / Milestone 2 code
        that called ``registry.get(name)``.
        """
        result = self._tools.get(name)
        if result is not None:
            return result
        return self._legacy.get(name)

    def list_available(self) -> list[str]:
        """
        Return the ids/names of every registered tool, enabled or not.

        Includes both new ``BaseTool`` ids and legacy ``Tool`` names, so
        callers that only need the name list see the complete picture.
        """
        return list(self._tools.keys()) + list(self._legacy.keys())
