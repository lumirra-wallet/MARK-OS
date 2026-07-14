"""DirectoryCreateTool — create a directory (with parents) within the workspace."""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class DirectoryCreateTool(BaseTool):
    """Create a directory inside the workspace, including any missing parents."""

    @property
    def id(self) -> str:
        return "directory_create"

    @property
    def name(self) -> str:
        return "Directory Create Tool"

    @property
    def description(self) -> str:
        return "Creates a directory (and its parents) within the workspace."

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
        return (Permission.CREATE_DIRECTORIES,)

    def validate(self, params: dict[str, Any]) -> bool:
        return bool(params.get("path"))

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Create a directory.  Already existing directories are treated as success.

        Params:
            path (str): Directory path (relative to workspace or absolute).
        """
        validator = PathValidator(context.workspace_path)
        try:
            resolved = validator.resolve_safe(params["path"])
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Could not create directory {params['path']!r}: {exc}",
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=f"Directory ready: {params['path']}",
            data={"path": str(resolved)},
            source=self.id,
        )
