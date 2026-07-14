"""
Entry point for running SmartAgent from the command line.

This module wires together configuration, the core agent, and (eventually)
voice/automation front-ends. For now it just boots the agent with default
settings and drops into a minimal placeholder loop so the project is
runnable end-to-end from day one, even though real behavior is not yet
implemented.
"""

from smartagent.brain.agent import SmartAgent
from smartagent.config.settings import Settings
from smartagent.logs.logger import configure_logging
from smartagent.ui.cli import run as run_ui


def main() -> None:
    """Boot SmartAgent using default configuration and start the CLI front-end."""
    configure_logging()
    settings = Settings.load()
    agent = SmartAgent(settings=settings)
    run_ui(agent)


if __name__ == "__main__":
    main()
