"""
Entry point for running SmartAgent from the command line.

This module wires together configuration, logging, the core agent, and the
interactive console.  Running::

    python -m smartagent.main

boots MARK and drops into a persistent interactive console where every
command is available immediately.

Logging is directed to ``logs/mark.log`` only — the console is kept clean
from log noise so the REPL prompt is always readable.
"""

from smartagent.brain.agent import SmartAgent
from smartagent.config.settings import Settings
from smartagent.logs.logger import configure_logging
from smartagent.ui.cli import run as run_ui


def main() -> None:
    """Boot SmartAgent and start the interactive console."""
    # Configure logging before any module-level loggers fire.
    # File-only (no console): keeps the REPL display clean.
    configure_logging(log_file="logs/mark.log", log_to_console=False)
    settings = Settings.load()
    agent = SmartAgent(settings=settings)
    run_ui(agent)


if __name__ == "__main__":
    main()
