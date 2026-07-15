"""
REPL — the read-eval-print loop for the MARK console.

This module owns only the I/O loop itself: reading a line from the user,
calling the :class:`~smartagent.ui.command_router.CommandRouter` to
dispatch it, and printing the response.  All business logic lives in the
command modules under ``smartagent/ui/commands/``.

Exit paths:
    - The user types ``exit`` or ``quit`` → handler raises
      :class:`~smartagent.ui.command_router.ExitConsole`.
    - The user presses Ctrl+C → :exc:`KeyboardInterrupt` is caught and
      triggers a clean shutdown.
    - EOF (Ctrl+D or piped input ends) → :exc:`EOFError` triggers
      a clean shutdown.  This also allows the REPL to be driven by
      piped input in tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter, ExitConsole
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

_logger = get_logger(__name__)

PROMPT = "mark> "


class Repl:
    """
    Persistent interactive read-eval-print loop.

    Instantiate once, then call :meth:`run` with the live agent and a
    configured :class:`~smartagent.ui.command_router.CommandRouter`.
    """

    def __init__(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        agent: "SmartAgent",
        router: CommandRouter,
        *,
        banner: str = "",
    ) -> None:
        """
        Start the REPL.

        Prints *banner* first (if supplied), then enters the loop.
        Returns only when the user exits or the input stream ends.
        """
        self._running = True
        if banner:
            print(banner)

        while self._running:
            try:
                raw = input(PROMPT)
            except KeyboardInterrupt:
                print("\nInterrupted.  Type 'exit' to quit.")
                _logger.info("REPL: KeyboardInterrupt received")
                continue
            except EOFError:
                # Piped input has ended — exit cleanly (important for tests).
                print()
                break

            raw = raw.strip()
            if not raw:
                continue

            _logger.debug("REPL input: %r", raw)

            try:
                response = router.dispatch(agent, raw)
            except ExitConsole:
                print("Goodbye.")
                _logger.info("REPL: exit requested")
                self._running = False
                break

            if response:
                print(response)

    # ------------------------------------------------------------------
    # Introspection (useful for tests)
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        """``True`` while the REPL loop is executing."""
        return self._running
