"""
REPL — the read-eval-print loop for the MARK console.

v2.0 improvements (Phase 8 — Reliability):
  - Global exception handler wraps every ``router.dispatch()`` call so that
    unexpected exceptions are caught, logged, and reported to the user as a
    friendly error rather than terminating MARK.
  - Keyboard-interrupt and EOF handling remain unchanged.

Exit paths:
    - The user types ``exit`` or ``quit`` → handler raises ExitConsole.
    - The user presses Ctrl+C → caught, loop continues.
    - EOF (Ctrl+D or piped input ends) → clean shutdown.
"""

from __future__ import annotations

import traceback
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
            except KeyboardInterrupt:
                # User Ctrl+C during a long command — cancel, stay in REPL.
                print("\n[interrupted]")
                _logger.info("REPL: command interrupted by user")
                continue
            except Exception as exc:  # noqa: BLE001
                # Phase 8: graceful recovery — never let an uncaught exception
                # terminate MARK.
                _logger.error(
                    "REPL: unhandled exception for %r: %s",
                    raw,
                    exc,
                    exc_info=True,
                )
                tb_lines = traceback.format_exc().splitlines()
                # Show a concise error; include last 3 traceback lines for context.
                tail = "\n  ".join(tb_lines[-3:])
                print(
                    f"[error] An unexpected error occurred:\n  {exc}\n\n"
                    f"  {tail}\n\n"
                    "MARK continues — type 'help' to see available commands."
                )
                continue

            if response:
                print(response)

    # ------------------------------------------------------------------
    # Introspection (useful for tests)
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        """``True`` while the REPL loop is executing."""
        return self._running
