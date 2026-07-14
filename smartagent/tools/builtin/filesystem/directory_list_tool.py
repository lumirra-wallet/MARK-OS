"""DirectoryListTool — list the contents of a directory within the workspace."""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class DirectoryListTool(BaseTool):
    """List files and subdirectories within a workspace directory."""

    @property
    def id(self) -> str:
        return "directory_list"

    @property
    def name(self) -> str:
        return "Directory List Tool"

    @property
    def description(self) -> str:
        return "Lists the contents of a directory within the workspace."

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
        return bool(params.get("path"))

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        List directory contents.

        Params:
            path (str): Directory path (relative to workspace or absolute).
        """
        validator = PathValidator(context.workspace_path)
        try:
            resolved = validator.resolve_safe(params["path"])
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        if not resolved.exists():
            return ActionResult(
                success=False,
                message=f"Directory not found: {params['path']}",
                source=self.id,
            )
        if not resolved.is_dir():
            return ActionResult(
                success=False,
                message=f"Path is not a directory: {params['path']}",
                source=self.id,
            )

        try:
            entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
            items = [
                {"name": e.name, "type": "file" if e.is_file() else "directory"}
                for e in entries
            ]
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Could not list {params['path']!r}: {exc}",
                source=self.id,
            )

        summary = f"{len(items)} item(s) in {params['path']}"
        return ActionResult(
            success=True,
            message=summary,
            data={"path": str(resolved), "items": items},
            source=self.id,
        )
