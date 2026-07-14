"""
ModuleRegistry — Brain v2's directory of capability modules.

Design decision (Milestone 2, Part 4): "The Brain must never hardcode
module names." Concretely, that means `BrainRouter` and `DecisionEngine`
only ever refer to modules by looking them up in this registry — neither
contains an `if module == "memory"` style branch. Whoever wires up a
`SmartAgent` (see `smartagent.brain.module_bindings`) decides which
concrete subsystem backs each name; the routing logic itself stays
agnostic to what memory/skills/tools/etc. actually are.
"""

from __future__ import annotations

from typing import Callable

from smartagent.brain.action_result import ActionResult

# Every registered module is just a callable: take the raw message, return
# a standardized ActionResult. This is intentionally the smallest possible
# contract — it says nothing about *how* a module decides what to do.
ModuleHandler = Callable[[str], ActionResult]


class ModuleRegistry:
    """Holds the set of capability modules currently available to the Brain."""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleHandler] = {}

    def register(self, name: str, handler: ModuleHandler) -> None:
        """Register `handler` under `name`, making it selectable by the Decision Engine."""
        self._modules[name] = handler

    def unregister(self, name: str) -> None:
        """Remove a previously registered module, if present."""
        self._modules.pop(name, None)

    def get(self, name: str) -> ModuleHandler | None:
        """Look up a registered module's handler by name, or None if not found."""
        return self._modules.get(name)

    def is_registered(self, name: str) -> bool:
        """Whether a module is currently registered under `name`."""
        return name in self._modules

    def list_modules(self) -> list[str]:
        """Return the names of every currently registered module."""
        return list(self._modules.keys())
