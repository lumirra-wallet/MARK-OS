"""FileReadTool — read the text content of a file within the workspace."""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class FileReadTool(BaseTool):
    """Read the full UTF-8 (or specified encoding) text content of a file."""

    @property
    def id(self) -> str:
        return "file_read"

    @property
    def name(self) -> str:
        return "File Read Tool"

    @property
    def description(self) -> str:
        return "Reads the text content of a file within the workspace."

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
        Read a file and return its text content.

        Params:
            path (str): Path to the file (relative to workspace or absolute).
            encoding (str, optional): File encoding. Defaults to ``"utf-8"``.
        """
        validator = PathValidator(context.workspace_path)
        try:
            resolved = validator.resolve_safe(params["path"])
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

        encoding = params.get("encoding", "utf-8")
        try:
            content = resolved.read_text(encoding=encoding)
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Could not read {params['path']!r}: {exc}",
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=content,
            data={"path": str(resolved), "size_bytes": len(content.encode(encoding))},
            source=self.id,
        )
