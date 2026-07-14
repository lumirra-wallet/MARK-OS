"""ReadMarkdownTool — read a Markdown file and return parsed structure."""

from __future__ import annotations

from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext
from smartagent.tools.safety import PathValidator, SafetyError

_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown", ".mdown", ".mkd"})


class ReadMarkdownTool(BaseTool):
    """
    Read a Markdown file and return its raw content plus a parsed heading structure.

    The heading parse is intentionally simple (no full AST) — it extracts
    ``# Heading`` lines with their level and text, which is enough for
    navigation and summary use-cases without pulling in an external parser.
    """

    @property
    def id(self) -> str:
        return "read_markdown"

    @property
    def name(self) -> str:
        return "Read Markdown Tool"

    @property
    def description(self) -> str:
        return "Reads a Markdown file and returns its content with a parsed heading list."

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
        path = params.get("path", "")
        return bool(path) and any(
            str(path).lower().endswith(ext) for ext in _MARKDOWN_EXTENSIONS
        )

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Read and structurally parse a Markdown file.

        Params:
            path (str): Path to the ``.md`` file (relative or absolute).

        Returns:
            ``ActionResult`` whose ``data`` includes:
                - ``content``: Raw file text.
                - ``headings``: List of ``{"level": int, "text": str}`` dicts.
                - ``heading_count``: Total number of headings found.
        """
        validator = PathValidator(context.workspace_path)
        try:
            resolved = validator.resolve_safe(params["path"])
        except SafetyError as exc:
            return ActionResult(success=False, message=str(exc), source=self.id)

        if resolved.suffix.lower() not in _MARKDOWN_EXTENSIONS:
            return ActionResult(
                success=False,
                message=f"File {params['path']!r} is not a Markdown file.",
                source=self.id,
            )
        if not resolved.exists() or not resolved.is_file():
            return ActionResult(
                success=False,
                message=f"Markdown file not found: {params['path']}",
                source=self.id,
            )

        try:
            content = resolved.read_text(encoding="utf-8")
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Could not read {params['path']!r}: {exc}",
                source=self.id,
            )

        headings = []
        for line in content.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                text = stripped[level:].strip()
                if text:
                    headings.append({"level": level, "text": text})

        return ActionResult(
            success=True,
            message=content,
            data={
                "path": str(resolved),
                "content": content,
                "headings": headings,
                "heading_count": len(headings),
            },
            source=self.id,
        )
