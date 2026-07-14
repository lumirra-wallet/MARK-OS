"""CopyFileTool — copy a file within the workspace."""

from __future__ import annotations

import shutil
from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError


class CopyFileTool(BaseTool):
    """Copy a file from one location to another within the workspace."""

    @property
    def id(self) -> str:
        return "copy_file"

    @property
    def name(self) -> str:
        return "Copy File Tool"

    @property
    def description(self) -> str:
        return "Copies a file within the workspace."

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
        return (Permission.READ_FILES, Permission.WRITE_FILES)

    def validate(self, params: dict[str, Any]) -> bool:
        return bool(params.get("src")) and bool(params.get("dst"))

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Copy a file.

        Params:
            src (str): Source file path (relative or absolute within workspace).
            dst (str): Destination path (relative or absolute within workspace).
            overwrite (bool, optional): If ``False`` and destination exists,
                return a failure.  Defaults to ``False``.
        """
        validator = PathValidator(context.workspace_path)
        try:
            src = validator.resolve_safe(params["src"])
            dst = validator.resolve_safe(params["dst"])
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        if not src.exists() or not src.is_file():
            return ActionResult(
                success=False,
                message=f"Source file not found: {params['src']}",
                source=self.id,
            )

        overwrite = params.get("overwrite", False)
        if dst.exists() and not overwrite:
            return ActionResult(
                success=False,
                message=f"Destination already exists and overwrite=False: {params['dst']}",
                source=self.id,
            )

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Copy failed: {exc}",
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=f"Copied {params['src']} -> {params['dst']}",
            data={"src": str(src), "dst": str(dst)},
            source=self.id,
        )
