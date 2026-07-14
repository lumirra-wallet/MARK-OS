"""DateTimeTool — return the current date and/or time in various formats."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext

_FORMATS = {
    "iso": lambda dt: dt.isoformat(timespec="seconds"),
    "date": lambda dt: dt.strftime("%Y-%m-%d"),
    "time": lambda dt: dt.strftime("%H:%M:%S"),
    "datetime": lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"),
    "unix": lambda dt: str(int(dt.timestamp())),
    "rfc2822": lambda dt: dt.strftime("%a, %d %b %Y %H:%M:%S %z"),
}


class DateTimeTool(BaseTool):
    """
    Return the current UTC date/time in a specified format.

    No permissions required — reading the clock is side-effect free.
    """

    @property
    def id(self) -> str:
        return "date_time"

    @property
    def name(self) -> str:
        return "Date Time Tool"

    @property
    def description(self) -> str:
        return "Returns the current UTC date and/or time in a requested format."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    def validate(self, params: dict[str, Any]) -> bool:
        # No required params.  Optional `format` is validated at execute time.
        return True

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Return the current UTC date/time.

        Params:
            format (str, optional): One of ``"iso"`` (default), ``"date"``,
                ``"time"``, ``"datetime"``, ``"unix"``, ``"rfc2822"``.
        """
        fmt_key = str(params.get("format", "iso")).lower()
        formatter = _FORMATS.get(fmt_key)
        if formatter is None:
            valid = ", ".join(f"{k!r}" for k in _FORMATS)
            return ActionResult(
                success=False,
                message=f"Unknown format {fmt_key!r}. Valid formats: {valid}.",
                source=self.id,
            )

        now = datetime.now(timezone.utc)
        formatted = formatter(now)
        return ActionResult(
            success=True,
            message=formatted,
            data={
                "formatted": formatted,
                "format": fmt_key,
                "iso": now.isoformat(timespec="seconds"),
                "unix": int(now.timestamp()),
            },
            source=self.id,
        )
