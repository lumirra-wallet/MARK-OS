"""
Command-line interface front-end.

Thin wrapper that drives a `SmartAgent` instance from the command line.
Kept separate from `smartagent.main` (the process entry point) and from
`smartagent.brain.agent` (the orchestrator) so alternative front-ends
(a web ui, a voice-only loop, etc.) can be added later without changing
either of those.
"""

from __future__ import annotations

from smartagent.brain.agent import SmartAgent


def run(agent: SmartAgent) -> None:
    """
    Start the CLI front-end for `agent`.

    Placeholder implementation: delegates straight to `agent.run()`. Will
    later own the actual read-input/print-output loop (and call
    `agent.handle_message` per line) once that behavior is implemented.
    """
    # TODO: replace with a real input/output loop, e.g.:
    #   while True:
    #       message = input("> ")
    #       print(agent.handle_message(message))
    agent.run()
