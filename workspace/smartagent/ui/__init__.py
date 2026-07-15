"""
User-interface layer for MARK.

Currently implements a terminal-based interactive console
(:mod:`smartagent.ui.console`), but the package is structured so that
alternative front-ends (web UI, voice loop, API server) can be added
alongside the console without any changes to the agent core.

Sub-modules:
    console        — top-level Console coordinator
    repl           — the read-eval-print I/O loop
    renderer       — pure formatting helpers (no I/O)
    command_router — command registry and dispatcher
    commands/      — one module per command group
"""
