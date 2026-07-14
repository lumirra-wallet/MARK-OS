"""
Command modules for the MARK console.

Each sub-module exposes a ``register(router: CommandRouter) -> None``
function that installs its handlers.  ``console.py`` calls all of them
at startup so the main REPL stays free of per-command logic.
"""
