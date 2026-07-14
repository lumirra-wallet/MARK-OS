"""UUIDTool — generate universally unique identifiers."""

from __future__ import annotations

import uuid
from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext


class UUIDTool(BaseTool):
    """
    Generate a UUID of the requested version.

    No permissions required — pure computation with no I/O side effects.
    Supports versions 1, 3, 4, and 5.  Version 4 (random) is the default.
    """

    @property
    def id(self) -> str:
        return "uuid_generate"

    @property
    def name(self) -> str:
        return "UUID Generate Tool"

    @property
    def description(self) -> str:
        return "Generates a universally unique identifier (UUID)."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.UTILITIES

    def validate(self, params: dict[str, Any]) -> bool:
        # No required params.  Optional `version` validated at execute time.
        return True

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Generate a UUID.

        Params:
            version (int, optional): UUID version.  One of 1, 3, 4 (default), 5.
            namespace (str, optional): Required for versions 3 and 5.
                One of ``"dns"``, ``"url"``, ``"oid"``, ``"x500"``.
            name (str, optional): Name string required for versions 3 and 5.
        """
        version = int(params.get("version", 4))

        _NAMESPACES = {
            "dns": uuid.NAMESPACE_DNS,
            "url": uuid.NAMESPACE_URL,
            "oid": uuid.NAMESPACE_OID,
            "x500": uuid.NAMESPACE_X500,
        }

        try:
            if version == 1:
                result = uuid.uuid1()
            elif version == 4:
                result = uuid.uuid4()
            elif version in (3, 5):
                ns_key = str(params.get("namespace", "dns")).lower()
                namespace = _NAMESPACES.get(ns_key)
                if namespace is None:
                    return ActionResult(
                        success=False,
                        message=f"Unknown namespace {ns_key!r}. Valid: {list(_NAMESPACES)}.",
                        source=self.id,
                    )
                name = str(params.get("name", ""))
                result = uuid.uuid3(namespace, name) if version == 3 else uuid.uuid5(namespace, name)
            else:
                return ActionResult(
                    success=False,
                    message=f"Unsupported UUID version {version}. Supported: 1, 3, 4, 5.",
                    source=self.id,
                )
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"UUID generation failed: {exc}",
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=str(result),
            data={"uuid": str(result), "version": version},
            source=self.id,
        )
