"""HashTool — compute cryptographic hashes of string content."""

from __future__ import annotations

import hashlib
from typing import Any

from smartagent.brain.action_result import ActionResult
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext

_SUPPORTED_ALGORITHMS = frozenset(hashlib.algorithms_guaranteed)


class HashTool(BaseTool):
    """
    Compute a cryptographic hash of provided string content.

    No permissions required — pure computation, no I/O.
    Supports any algorithm available in Python's ``hashlib.algorithms_guaranteed``
    (e.g. ``"sha256"``, ``"md5"``, ``"sha512"``, ``"blake2b"``).
    """

    @property
    def id(self) -> str:
        return "hash_compute"

    @property
    def name(self) -> str:
        return "Hash Compute Tool"

    @property
    def description(self) -> str:
        return "Computes a cryptographic hash of the given string content."

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
        return "content" in params

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        """
        Compute a hash.

        Params:
            content (str): The string to hash.
            algorithm (str, optional): Hash algorithm name.  Defaults to
                ``"sha256"``.  Must be in ``hashlib.algorithms_guaranteed``.
            encoding (str, optional): Encoding used to turn ``content`` into
                bytes.  Defaults to ``"utf-8"``.
        """
        algorithm = str(params.get("algorithm", "sha256")).lower()
        if algorithm not in _SUPPORTED_ALGORITHMS:
            return ActionResult(
                success=False,
                message=(
                    f"Unsupported algorithm {algorithm!r}. "
                    f"Supported: {sorted(_SUPPORTED_ALGORITHMS)}."
                ),
                source=self.id,
            )

        content: str = str(params["content"])
        encoding: str = str(params.get("encoding", "utf-8"))

        try:
            digest = hashlib.new(algorithm, content.encode(encoding)).hexdigest()
        except Exception as exc:
            return ActionResult(
                success=False,
                message=f"Hash computation failed: {exc}",
                source=self.id,
            )

        return ActionResult(
            success=True,
            message=digest,
            data={
                "algorithm": algorithm,
                "digest": digest,
                "content_length": len(content),
                "encoding": encoding,
            },
            source=self.id,
        )
