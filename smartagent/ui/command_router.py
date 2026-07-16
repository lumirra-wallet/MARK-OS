"""
CommandRouter — maps command names to handler functions.

Design goals:
- No ``if/elif`` chains in the REPL.  Each command module registers its
  handlers here once at startup.
- Easy to extend: new milestone adds a new ``commands/xxx.py`` module and
  a single ``register(router)`` call in ``console.py``.
- Handlers are plain callables ``(agent, args) -> str``.  The REPL prints
  whatever they return.  Raising :class:`ExitConsole` is the only special
  case (it signals a clean shutdown).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

Handler = Callable[["SmartAgent", list[str]], str]
FallbackHandler = Callable[["SmartAgent", str], str]


class ExitConsole(Exception):
    """Raised by the ``exit`` / ``quit`` handler to signal a clean shutdown."""


@dataclass
class CommandEntry:
    """Metadata about a single registered command."""

    name: str
    handler: Handler
    description: str
    group: str
    # Order within the group (lower = shown first).
    order: int = 0


class CommandRouter:
    """
    Registry and dispatcher for MARK console commands.

    Usage::

        router = CommandRouter()
        router.register("status", handle_status, "show system dashboard", "SYSTEM")
        response = router.dispatch(agent, "status")
    """

    _GROUP_ORDER: dict[str, int] = {
        "SYSTEM": 0,
        "MIND": 1,
        "MEMORY": 2,
        "KNOWLEDGE": 3,
        "SKILLS": 4,
        "TOOLS": 5,
        "MODELS": 6,
        "EVENTS": 7,
    }

    def __init__(self) -> None:
        self._entries: dict[str, CommandEntry] = {}
        self._fallback: FallbackHandler | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def set_fallback(self, handler: FallbackHandler) -> None:
        """
        Register a handler called when no command matches the input.

        The fallback receives the agent and the full raw input string
        (not just the args).  Used by the Console to route free-text
        messages to the active model when one is loaded.

        If no fallback is set, unknown commands return a friendly error.
        """
        self._fallback = handler

    def register(
        self,
        name: str,
        handler: Handler,
        description: str = "",
        group: str = "SYSTEM",
        order: int = 0,
    ) -> None:
        """Register *handler* under *name*.  Silently overwrites duplicates."""
        self._entries[name.lower()] = CommandEntry(
            name=name,
            handler=handler,
            description=description,
            group=group.upper(),
            order=order,
        )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, agent: "SmartAgent", raw: str) -> str:
        """
        Parse *raw* into a command name + argument list and call the handler.

        Returns the handler's string response.  Unknown commands return a
        friendly error rather than raising.
        """
        parts = raw.strip().split()
        if not parts:
            return ""

        name = parts[0].lower()
        args = parts[1:]

        entry = self._entries.get(name)
        if entry is None:
            if self._fallback is not None:
                return self._fallback(agent, raw.strip())
            return f'Unknown command: "{name}"\nType "help" for available commands.'

        try:
            return entry.handler(agent, args)
        except ExitConsole:
            raise
        except Exception as exc:  # pragma: no cover
            return f"[error] {name}: {exc}"

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def help_entries(self) -> list[tuple[str, str, str]]:
        """Return ``(group, name, description)`` tuples sorted for display."""
        entries = sorted(
            self._entries.values(),
            key=lambda e: (
                self._GROUP_ORDER.get(e.group, 99),
                e.order,
                e.name,
            ),
        )
        return [(e.group, e.name, e.description) for e in entries]

    def commands(self) -> list[CommandEntry]:
        """Return all registered :class:`CommandEntry` objects."""
        return list(self._entries.values())

    def has_command(self, name: str) -> bool:
        """Return True when *name* is a registered command."""
        return name.lower() in self._entries
