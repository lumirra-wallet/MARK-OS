"""OpenTextFileTool — open a text file and return its content with file metadata."""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class OpenTextFileTool(BaseTool):
    """
    Open and read a plain-text file, returning content plus metadata.

    Distinct from ``FileReadTool`` in that it also reports file metadata
    (line count, encoding used, size) and is categorised under ``TEXT``
    rather than ``FILESYSTEM`` — intended for text-processing workflows that
    need the metadata alongside the content.
    """

    @property
    def id(self) -> str:
        return "open_text_file"

    @property
    def name(self) -> str:
        return "Open Text File Tool"

    @property
    def description(self) -> str:
        return "Opens and reads a plain-text file, returning content and file metadata."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.TEXT

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.READ_FILES,)

    def validate(self, params: dict[str, Any]) -> bool:
        return bool(params.get("path"))

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Read a text file and return its content with metadata.

        Params:
            path (str): File path (relative to workspace or absolute).
            encoding (str, optional): File encoding.  Defaults to ``"utf-8"``.
        """
        validator = PathValidator(context.workspace_path)
        try:
            resolved = validator.resolve_safe(params["path"])
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        if not resolved.exists() or not resolved.is_file():
            return ActionResult(
                success=False,
                message=f"File not found: {params['path']}",
                source=self.id,
            )

        encoding = params.get("encoding", "utf-8")
        try:
            content = resolved.read_text(encoding=encoding)
        except UnicodeDecodeError:
            return ActionResult(
                success=False,
                message=(
                    f"Could not decode {params['path']!r} as {encoding}. "
                    "Try a different encoding."
                ),
                source=self.id,
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Could not open {params['path']!r}: {exc}",
                source=self.id,
            )

        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return ActionResult(
            success=True,
            message=content,
            data={
                "path": str(resolved),
                "encoding": encoding,
                "size_bytes": resolved.stat().st_size,
                "line_count": line_count,
            },
            source=self.id,
        )
