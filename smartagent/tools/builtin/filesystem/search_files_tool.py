"""SearchFilesTool — find files by name pattern within the workspace."""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class SearchFilesTool(BaseTool):
    """Recursively search a directory for files matching a glob pattern."""

    @property
    def id(self) -> str:
        return "search_files"

    @property
    def name(self) -> str:
        return "Search Files Tool"

    @property
    def description(self) -> str:
        return "Recursively searches a directory for files matching a glob pattern."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.FILESYSTEM

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.READ_FILES,)

    def validate(self, params: dict[str, Any]) -> bool:
        return bool(params.get("pattern"))

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Glob-search for files.

        Params:
            pattern (str): Glob pattern (e.g. ``"*.md"``, ``"**/*.py"``).
            directory (str, optional): Starting directory.  Defaults to the
                workspace root.
        """
        validator = PathValidator(context.workspace_path)
        directory = params.get("directory", ".")
        try:
            resolved_dir = validator.resolve_safe(directory)
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        if not resolved_dir.is_dir():
            return ActionResult(
                success=False,
                message=f"Search directory not found or not a directory: {directory}",
                source=self.id,
            )

        pattern: str = params["pattern"]
        try:
            matches = sorted(
                str(p.relative_to(resolved_dir)) for p in resolved_dir.rglob(pattern)
                if p.is_file()
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Search failed: {exc}",
                source=self.id,
            )

        if not matches:
            return ActionResult(
                success=True,
                message=f"No files matching {pattern!r} found in {directory}.",
                data={"matches": [], "count": 0},
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=f"Found {len(matches)} file(s) matching {pattern!r}.",
            data={"matches": matches, "count": len(matches)},
            source=self.id,
        )
