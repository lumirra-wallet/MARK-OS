"""
Command-line interface front-end.

Thin wrapper that drives a :class:`~smartagent.brain.agent.SmartAgent`
instance from the command line via the :class:`~smartagent.ui.console.Console`.

Kept separate from ``smartagent.main`` (the process entry point) and from
``smartagent.brain.agent`` (the orchestrator) so alternative front-ends
(a web UI, a voice-only loop, an API server, etc.) can be added later
without changing either of those.
"""

from __future__ import annotations

from smartagent.brain.agent import SmartAgent
from smartagent.ui.console import Console


def run(agent: SmartAgent) -> None:
    """
    Start the MARK interactive console for *agent*.

    Blocks until the user exits (``exit`` / ``quit`` / Ctrl+C / EOF).
    """
    Console(agent).run()
