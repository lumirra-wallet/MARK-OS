"""
Safety subsystem — Milestone 4, Part 9.

Provides ``PathValidator``, the single authority that enforces the workspace
sandboxing rule: no tool may access a path outside ``ToolContext.workspace_path``.
``DeleteFileTool`` additionally calls ``check_not_protected_source()`` to
prevent tools from destroying the project's own source code.

Design decisions:
- ``SafetyError`` is a plain ``Exception`` subclass (not a subclass of
  ``PermissionError``) so callers can distinguish a sandbox violation from
  an OS-level access denial.
- ``resolve_safe`` always resolves symlinks before checking containment, so
  a symlink that points outside the workspace is caught even if the link
  itself lives inside it.
- ``_PROTECTED_SOURCE_DIRS`` is intentionally a small, hard-coded frozenset.
  Source protection is a safety invariant, not a user-configurable option —
  an admin should not be able to accidentally disable it via settings.
"""

from __future__ import annotations

from pathlib import Path

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

#: Directory names that tools must never delete or overwrite, regardless
#: of where inside the workspace they live.  Prevents a ``DeleteFileTool``
#: call from wiping out the project's own source or test suite.
_PROTECTED_SOURCE_DIRS: frozenset[str] = frozenset({"smartagent", "tests"})


class SafetyError(Exception):
    """
    Raised when a tool request violates a workspace safety constraint.

    Catching code should treat this as a hard rejection, not a transient
    error — the operation should not be retried without explicit human
    approval, since it tried to escape the sandbox or destroy protected
    source files.
    """


class PathValidator:
    """
    Resolves and validates file paths against a workspace boundary.

    Args:
        workspace_path: Root directory tools are allowed to operate within.
            Resolved to an absolute path on construction; all subsequent
            ``resolve_safe`` calls are checked against this resolved root.
    """

    def __init__(self, workspace_path: str) -> None:
        self._workspace = Path(workspace_path).resolve()

    @property
    def workspace(self) -> Path:
        """The absolute workspace root path this validator enforces."""
        return self._workspace

    def resolve_safe(self, path: str) -> Path:
        """
        Resolve ``path`` relative to the workspace and verify it stays inside.

        ``path`` may be absolute or relative.  If relative it is joined onto
        ``workspace_path`` before resolving.  Absolute paths are resolved as-is
        and then checked for containment.

        Raises:
            SafetyError: If the resolved path would escape the workspace root.

        Returns:
            The resolved, workspace-contained absolute ``Path``.
        """
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self._workspace / candidate
        resolved = candidate.resolve()

        try:
            resolved.relative_to(self._workspace)
        except ValueError:
            raise SafetyError(
                f"Path {path!r} resolves to {resolved} which is outside the "
                f"configured workspace {self._workspace}. Operation rejected for safety."
            )

        logger.debug("Path validated OK: %r -> %s", path, resolved)
        return resolved

    def check_not_protected_source(self, path: Path) -> None:
        """
        Raise ``SafetyError`` if ``path`` contains a protected source directory.

        Checks every component of ``path`` against ``_PROTECTED_SOURCE_DIRS``.
        This prevents tools like ``DeleteFileTool`` from obliterating
        ``smartagent/`` or ``tests/`` even when those directories live inside
        the configured workspace.

        Raises:
            SafetyError: If any part of the path matches a protected directory
                name.
        """
        for part in path.parts:
            if part in _PROTECTED_SOURCE_DIRS:
                raise SafetyError(
                    f"Operation on {path} is rejected: path contains the "
                    f"protected source directory {part!r}.  Use a workspace "
                    f"data directory (e.g. vault/, data/, tmp/) instead of "
                    f"operating on project source files."
                )
