"""DeleteFileTool — permanently delete a file within the workspace.

Safety: this tool applies two layers of protection:
1. ``PathValidator.resolve_safe()`` — rejects paths outside the workspace.
2. ``PathValidator.check_not_protected_source()`` — rejects any path whose
   parts include ``"smartagent"`` or ``"tests"``, preventing the tool from
   wiping out the project's own source code even when those directories
   happen to sit inside the configured workspace.
"""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class DeleteFileTool(BaseTool):
    """Permanently delete a single file within the workspace."""

    @property
    def id(self) -> str:
        return "delete_file"

    @property
    def name(self) -> str:
        return "Delete File Tool"

    @property
    def description(self) -> str:
        return "Permanently deletes a file within the workspace."

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
        return (Permission.DELETE_FILES,)

    def validate(self, params: dict[str, Any]) -> bool:
        return bool(params.get("path"))

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Delete a file.

        Params:
            path (str): File path (relative to workspace or absolute).
        """
        validator = PathValidator(context.workspace_path)
        try:
            resolved = validator.resolve_safe(params["path"])
            validator.check_not_protected_source(resolved)
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        if not resolved.exists():
            return ActionResult(
                success=False,
                message=f"File not found: {params['path']}",
                source=self.id,
            )
        if not resolved.is_file():
            return ActionResult(
                success=False,
                message=f"Path is not a file: {params['path']}",
                source=self.id,
            )

        try:
            resolved.unlink()
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Could not delete {params['path']!r}: {exc}",
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=f"Deleted: {params['path']}",
            data={"path": str(resolved)},
            source=self.id,
        )
