"""SystemInfoTool — report OS and Python runtime information."""

from __future__ import annotations

import platform
import sys
from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext


class SystemInfoTool(BaseTool):
    """Return a snapshot of OS, Python version, and platform information."""

    @property
    def id(self) -> str:
        return "system_info"

    @property
    def name(self) -> str:
        return "System Info Tool"

    @property
    def description(self) -> str:
        return "Returns OS, architecture, and Python version information."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.SYSTEM

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.READ_SYSTEM_INFO,)

    def validate(self, params: dict[str, Any]) -> bool:
        # No required params — any dict (including empty) is valid.
        return True

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Collect and return system information.

        Returns a dict with: ``os``, ``os_version``, ``machine``,
        ``processor``, ``python_version``, ``python_implementation``.
        """
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
        }
        summary = (
            f"{info['os']} {info['os_release']} | "
            f"Python {info['python_version']} ({info['python_implementation']})"
        )
        return ActionResult(
            success=True,
            message=summary,
            data=info,
            source=self.id,
        )
