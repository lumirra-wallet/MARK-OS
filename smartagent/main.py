"""
Entry point for running SmartAgent from the command line.

This module wires together configuration, the core agent, and (eventually)
voice/automation front-ends. For now it just boots the agent with default
settings and drops into a minimal placeholder loop so the project is
runnable end-to-end from day one, even though real behavior is not yet
implemented.
"""

from smartagent.config.settings import Settings
from smartagent.core.agent import SmartAgent


def main() -> None:
    """Boot SmartAgent using default configuration and start the main loop."""
    settings = Settings.load()
    agent = SmartAgent(settings=settings)
    agent.run()


if __name__ == "__main__":
    main()
