"""
Console — the top-level coordinator for the MARK interactive console.

Wires together:
    - :mod:`smartagent.ui.renderer` — banner and formatting helpers.
    - :class:`~smartagent.ui.command_router.CommandRouter` — command
      registry and dispatcher.
    - :mod:`smartagent.ui.commands.*` — individual command modules.
    - :class:`~smartagent.ui.repl.Repl` — the I/O loop.

Adding new commands for a future milestone means:
    1. Create ``smartagent/ui/commands/<module>.py`` with a
       ``register(router)`` function.
    2. Import and call it in :meth:`Console._register_commands`.
    3. No other file needs to change.
"""

from __future__ import annotations

from smartagent.brain.agent import SmartAgent
from smartagent.logs.logger import get_logger
from smartagent.ui import renderer
from smartagent.ui.command_router import CommandRouter
from smartagent.ui.commands import (
    events,
    executive,
    intelligence,
    knowledge,
    learning,
    memory,
    mind,
    models,
    multi_agent,
    skills,
    system,
    tools,
    workspace,
)
from smartagent.ui.commands import debug_cmd
from smartagent.ui.commands import git_cmd        # Milestone 21 — Git Engine
from smartagent.ui.commands import project_cmd    # Milestone 22 — Project Memory
from smartagent.ui.commands import long_run_cmd   # Milestone 23 — Long Running Execution
from smartagent.ui.commands import dev_loop_cmd   # Milestone 24 — Autonomous Dev Loop
from smartagent.ui.commands import engineer_cmd   # Milestone 25 — Full Software Engineer
from smartagent.ui.repl import Repl

_logger = get_logger(__name__)


class Console:
    """
    The MARK interactive console.

    Usage::

        agent = SmartAgent(settings)
        console = Console(agent)
        console.run()          # blocks until the user exits
    """

    def __init__(self, agent: SmartAgent) -> None:
        self._agent = agent
        self._router = CommandRouter()
        self._repl = Repl()
        self._register_commands()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Print the banner and start the interactive REPL."""
        _logger.info("Console: starting interactive session")
        banner = renderer.banner(self._agent)
        self._repl.run(self._agent, self._router, banner=banner)
        _logger.info("Console: session ended")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register_commands(self) -> None:
        """Install all command modules into the router."""
        # Order here controls nothing — each module declares its own group
        # and order so the help listing is always deterministic.
        system.register(self._router)
        mind.register(self._router)
        memory.register(self._router)
        knowledge.register(self._router)
        skills.register(self._router)
        tools.register(self._router)
        models.register(self._router)
        events.register(self._router)
        executive.register(self._router)    # Milestone 11 — plan, tasks
        learning.register(self._router)     # Milestone 14 — learning analytics
        workspace.register(self._router)    # Milestone 15 — workspace manager
        multi_agent.register(self._router)  # Milestone 17 — multi-agent collaboration
        intelligence.register(self._router) # Milestone 18 — workspace intelligence
        debug_cmd.register(self._router)    # Milestone 20 — self debugging
        git_cmd.register(self._router)      # Milestone 21 — Git Engine
        project_cmd.register(self._router)  # Milestone 22 — Project Memory
        long_run_cmd.register(self._router) # Milestone 23 — Long Running Execution
        dev_loop_cmd.register(self._router) # Milestone 24 — Autonomous Dev Loop
        engineer_cmd.register(self._router) # Milestone 25 — Full Software Engineer

        # Milestone 9: free-text fallback — when the user types something that
        # isn't a recognised command AND a model is active, route the raw input
        # to the model.  When no model is active the fallback returns the
        # standard "Unknown command" message so all pre-M9 behaviour is preserved.
        from smartagent.ui.commands.models import fallback_chat
        self._router.set_fallback(fallback_chat)

    # ------------------------------------------------------------------
    # Expose internals for testing
    # ------------------------------------------------------------------

    @property
    def router(self) -> CommandRouter:
        """The live :class:`~smartagent.ui.command_router.CommandRouter`."""
        return self._router

    @property
    def agent(self) -> SmartAgent:
        """The :class:`~smartagent.brain.agent.SmartAgent` instance."""
        return self._agent
