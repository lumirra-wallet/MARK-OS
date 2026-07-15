"""FileWriteTool — write text content to a file within the workspace."""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class FileWriteTool(BaseTool):
    """Write (or overwrite) a text file within the workspace."""

    @property
    def id(self) -> str:
        return "file_write"

    @property
    def name(self) -> str:
        return "File Write Tool"

    @property
    def description(self) -> str:
        return "Writes text content to a file within the workspace."

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
        return (Permission.WRITE_FILES,)

    def validate(self, params: dict[str, Any]) -> bool:
        return bool(params.get("path")) and "content" in params

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Write text to a file, creating parent directories as needed.

        Params:
            path (str): Destination path (relative to workspace or absolute).
            content (str): Text to write.
            overwrite (bool, optional): If ``False`` and the file exists,
                return a failure. Defaults to ``True``.
            encoding (str, optional): File encoding. Defaults to ``"utf-8"``.
        """
        validator = PathValidator(context.workspace_path)
        try:
            resolved = validator.resolve_safe(params["path"])
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        overwrite = params.get("overwrite", True)
        if resolved.exists() and not overwrite:
            return ActionResult(
                success=False,
                message=f"File already exists and overwrite=False: {params['path']}",
                source=self.id,
            )

        encoding = params.get("encoding", "utf-8")
        content: str = params["content"]
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding=encoding)
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Could not write {params['path']!r}: {exc}",
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=f"Written {len(content)} characters to {params['path']}.",
            data={"path": str(resolved), "size_bytes": len(content.encode(encoding))},
            source=self.id,
        )
