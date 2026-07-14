"""EnvironmentTool — read non-sensitive environment variables."""

from __future__ import annotations

import os
from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.skills.permissions import Permission
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext

#: Substrings that mark an env-var name as potentially sensitive.
#: Case-insensitive comparison is used at runtime.
_SENSITIVE_SUBSTRINGS = frozenset({
    "key", "secret", "token", "password", "passwd", "pass",
    "credential", "auth", "private", "cert", "api",
})


def _is_sensitive(name: str) -> bool:
    """Return True if the variable name looks like a secret."""
    lower = name.lower()
    return any(sub in lower for sub in _SENSITIVE_SUBSTRINGS)


class EnvironmentTool(BaseTool):
    """
    Read environment variables, automatically filtering out sensitive names.

    Any variable whose name contains a word from ``_SENSITIVE_SUBSTRINGS``
    is replaced with ``"<redacted>"`` in the output — values are never
    returned for such variables.
    """

    @property
    def id(self) -> str:
        return "environment_info"

    @property
    def name(self) -> str:
        return "Environment Tool"

    @property
    def description(self) -> str:
        return "Returns non-sensitive environment variables (sensitive names are redacted)."

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
        return True

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Return environment variables.

        Params:
            key (str, optional): If given, return just this one variable.
                If the key is sensitive the value is redacted.  If the key
                does not exist, ``success=False`` is returned.
        """
        specific_key = params.get("key")

        if specific_key:
            value = os.environ.get(specific_key)
            if value is None:
                return ActionResult(
                    success=False,
                    message=f"Environment variable {specific_key!r} is not set.",
                    source=self.id,
                )
            display = "<redacted>" if _is_sensitive(specific_key) else value
            return ActionResult(
                success=True,
                message=f"{specific_key}={display}",
                data={"key": specific_key, "value": display, "redacted": _is_sensitive(specific_key)},
                source=self.id,
            )

        # Return all variables, redacting sensitive ones.
        env_vars: dict[str, str] = {}
        redacted_count = 0
        for name, value in sorted(os.environ.items()):
            if _is_sensitive(name):
                env_vars[name] = "<redacted>"
                redacted_count += 1
            else:
                env_vars[name] = value

        return ActionResult(
            success=True,
            message=(
                f"{len(env_vars)} environment variable(s) found "
                f"({redacted_count} redacted)."
            ),
            data={"variables": env_vars, "redacted_count": redacted_count},
            source=self.id,
        )
