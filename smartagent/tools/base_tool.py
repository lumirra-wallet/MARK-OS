"""
BaseTool — Milestone 4, Part 2.

Defines the abstract contract every SmartAgent tool implements, plus
the supporting metadata/context types. A ``Tool`` is a low-level, atomic
action executor that a Skill can call through the ``ToolEngine`` when it
needs to do something concrete (read a file, hash a string, generate a
UUID). The Brain never calls a tool directly — only Skills do, and only
via ``ToolEngine.run()``.

Design deliberately mirrors ``BaseSkill``:

- Properties declare identity/metadata.
- ``execute()`` does the work and always returns an ``ActionResult``.
- ``ToolContext`` carries dependency-injection rather than the full agent
  instance, avoiding circular imports and keeping each tool's surface tiny.

Unlike skills, tools receive *structured* ``params: dict`` rather than a
natural-language message. The caller (typically a Skill) is responsible for
mapping its message onto concrete parameter names before calling
``ToolEngine.run()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission

if TYPE_CHECKING:
    from smartagent.brain.events import EventBus
    from smartagent.config.settings import Settings


class ToolCategory(str, Enum):
    """Organises tools into deployment-visible buckets (Milestone 4 Part 6)."""

    FILESYSTEM = "filesystem"
    SYSTEM = "system"
    UTILITIES = "utilities"
    TEXT = "text"
    FUTURE = "future"   # reserved namespace for upcoming tools


class ToolStatus(str, Enum):
    """Runtime status managed by ``ToolRegistry.enable()`` / ``disable()``."""

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ToolMetadata:
    """
    Frozen snapshot of a tool's declared properties.

    Built on demand via ``BaseTool.metadata()`` so callers (the loader,
    ``ToolEngine.list_available()``, future UIs) have one stable, hashable
    shape regardless of the concrete tool implementation.
    """

    id: str
    name: str
    description: str
    version: str
    author: str
    category: ToolCategory
    permissions: tuple[Permission, ...]
    required_os: tuple[str, ...]
    required_dependencies: tuple[str, ...]


@dataclass
class ToolContext:
    """
    Dependency-injection bundle passed into ``BaseTool.execute()``.

    Provides exactly what a tool needs:

    - ``settings``: the current ``Settings`` instance (config values, etc.).
    - ``workspace_path``: filesystem root tools are sandboxed within.
      ``PathValidator`` uses this as the sandboxing boundary; every tool
      that touches the filesystem must pass paths through it.
    - ``events``: optional shared ``EventBus`` so tools can publish events
      (e.g. ``ToolExecuted``) without a hard dependency on the Brain.
    """

    settings: "Settings"
    workspace_path: str
    events: "EventBus | None" = None


class BaseTool(ABC):
    """
    Abstract base class every SmartAgent tool must implement (Part 2).

    **Required** abstract properties: ``id``, ``name``, ``description``,
    ``version``, ``author``, ``category``.

    **Required** abstract methods: ``validate()``, ``execute()``.

    **Optional** overridable properties: ``permissions`` (default: none),
    ``required_os`` (default: any), ``required_dependencies`` (default: none).

    **Optional** lifecycle hooks: ``initialize()``, ``shutdown()``, ``health()``.
    """

    #: Runtime enabled/disabled flag. Managed by ``ToolRegistry``, not the tool
    #: itself — so a disabled tool retains its state across disable→re-enable.
    _status: ToolStatus = ToolStatus.ENABLED

    # ------------------------------------------------------------------
    # Required abstract identity properties
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique, machine-readable identifier (e.g. ``"file_read"``)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name (e.g. ``"File Read Tool"``)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """One-sentence description of what this tool does."""
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string, independent of the project version."""
        raise NotImplementedError

    @property
    @abstractmethod
    def author(self) -> str:
        """Author/owner of this tool (e.g. ``"SmartAgent Core Team"``)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def category(self) -> ToolCategory:
        """Coarse category for discovery and reporting."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Optional overridable metadata properties
    # ------------------------------------------------------------------

    @property
    def permissions(self) -> tuple[Permission, ...]:
        """
        Permissions this tool needs to run (Part 7).

        ``ToolEngine`` denies execution if any declared permission is not
        currently granted by ``PermissionManager``. Defaults to empty —
        pure-computation tools (``DateTimeTool``, ``UUIDTool``, etc.) need
        no permission at all.
        """
        return ()

    @property
    def enabled(self) -> bool:
        """Whether this tool is currently enabled (driven by ``ToolRegistry``)."""
        return self._status == ToolStatus.ENABLED

    @property
    def required_os(self) -> tuple[str, ...]:
        """
        OS platforms this tool supports (``"Linux"``, ``"Darwin"``, ``"Windows"``).

        Empty means the tool runs on any OS. Tools that call OS-specific
        syscalls should declare their constraint here for health-check
        reporting.
        """
        return ()

    @property
    def required_dependencies(self) -> tuple[str, ...]:
        """
        Names of Python packages beyond stdlib that this tool requires.

        All built-in tools use stdlib only (``pathlib``, ``shutil``,
        ``hashlib``, ``platform``, etc.) so this defaults to empty. Future
        tools that need third-party packages (a PDF tool needing
        ``pypdf``, a vision tool needing ``Pillow``, etc.) declare them here
        for health-check reporting.
        """
        return ()

    # ------------------------------------------------------------------
    # Metadata snapshot
    # ------------------------------------------------------------------

    def metadata(self) -> ToolMetadata:
        """Build a ``ToolMetadata`` frozen snapshot of this tool's declared properties."""
        return ToolMetadata(
            id=self.id,
            name=self.name,
            description=self.description,
            version=self.version,
            author=self.author,
            category=self.category,
            permissions=tuple(self.permissions),
            required_os=tuple(self.required_os),
            required_dependencies=tuple(self.required_dependencies),
        )

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """
        Called once when the tool is registered with ``ToolRegistry``.

        Override to set up resources (open a connection, warm a cache, etc.).
        Default is a no-op so simple tools do not need to override.
        """

    @abstractmethod
    def validate(self, params: dict[str, Any]) -> bool:
        """
        Return ``True`` if this tool can handle the given ``params``.

        Must be side-effect free. ``ToolEngine`` calls this before
        ``execute()`` to verify the caller supplied all required parameters.
        Return ``False`` (do not raise) when a required key is missing or
        has an invalid type — ``ToolEngine`` will surface this as a failed
        ``ActionResult``.
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Execute the tool's action and return an ``ActionResult``.

        Unlike ``BaseSkill.execute()`` (which may return any value and lets
        the engine normalise it), tools always return ``ActionResult``
        directly — they are lower-level and premature normalisation would
        hide errors from the calling Skill.

        Implementations must:
        - Never raise (catch all exceptions and return ``success=False``).
        - Validate paths through ``PathValidator`` when touching the filesystem.
        - Set ``source=self.id`` on every ``ActionResult`` they return.
        """
        raise NotImplementedError

    def shutdown(self) -> None:
        """
        Called when the tool is unregistered from ``ToolRegistry``.

        Override to release resources (close connections, flush buffers, etc.).
        Default is a no-op.
        """

    def health(self) -> dict[str, Any]:
        """
        Return a health snapshot for this tool.

        Default reports the tool as healthy with its current status and
        dependency list. Override when the tool has external dependencies
        whose availability should be probed at runtime.
        """
        return {
            "id": self.id,
            "name": self.name,
            "status": self._status.value,
            "healthy": True,
            "required_dependencies": list(self.required_dependencies),
        }

    def status(self) -> ToolStatus:
        """Current enabled/disabled status. Managed by ``ToolRegistry``, not the tool."""
        return self._status
