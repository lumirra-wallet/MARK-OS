"""
System commands: help, status, version, clear, exit.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from smartagent.ui import renderer
from smartagent.ui.command_router import CommandRouter, ExitConsole

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_help(router: CommandRouter):
    """Return a closure that formats the current help listing."""

    def _handler(agent: "SmartAgent", args: list[str]) -> str:
        from smartagent.ui import renderer as r  # local import avoids circular dep
        return r.help_text(router.help_entries())

    return _handler


def handle_status(agent: "SmartAgent", args: list[str]) -> str:
    """Show the full system status dashboard."""
    lines: list[str] = [renderer.hr(), "SYSTEM STATUS", renderer.hr()]

    def _safe(label: str, fn) -> None:
        try:
            lines.append(fn())
        except Exception as exc:
            lines.append(f"  {label}: [unavailable — {exc}]")

    # Brain
    lines.append("\nBRAIN")
    lines.append("  Status        : Online")
    lines.append("  Router        : BrainRouter active")

    # Mind
    lines.append("\nMIND")
    try:
        sm = agent.mind.self_model()
        lines.append(f"  Status        : Online")
        lines.append(f"  State         : {sm.state}")
        lines.append(f"  Goal          : {sm.current_goal or 'None'}")
        lines.append(f"  Confidence    : {sm.confidence:.2f}")
    except Exception as exc:
        lines.append(f"  Status        : Online [detail unavailable — {exc}]")

    # Memory
    lines.append("\nMEMORY")
    try:
        cats = agent.memory.list_categories()
        recent = agent.memory.search("", limit=5)
        lines.append(f"  Backend       : {agent.settings.memory_backend}")
        lines.append(f"  Categories    : {len(cats)}")
        lines.append(f"  Recent entries: {len(recent)}")
    except Exception as exc:
        lines.append(f"  Status        : [unavailable — {exc}]")

    # Knowledge
    lines.append("\nKNOWLEDGE")
    try:
        stats = agent.knowledge.stats()
        inbox_pending = stats.pending_inbox_items
        lines.append(f"  Concepts      : {stats.total_concepts}")
        lines.append(f"  Relationships : {stats.total_relationships}")
        lines.append(f"  Avg confidence: {stats.average_confidence:.2f}")
        lines.append(f"  Inbox pending : {inbox_pending}")
    except Exception as exc:
        lines.append(f"  Status        : [unavailable — {exc}]")

    # Skills
    lines.append("\nSKILLS")
    try:
        skills = agent.skill_engine.list_available()
        lines.append(f"  Loaded        : {len(skills)}")
        for s in skills[:5]:
            lines.append(f"    - {s.get('id', s.get('name', '?'))}")
        if len(skills) > 5:
            lines.append(f"    ... and {len(skills) - 5} more")
    except Exception as exc:
        lines.append(f"  Status        : [unavailable — {exc}]")

    # Tools
    lines.append("\nTOOLS")
    try:
        tools = agent.tool_engine.list_available()
        lines.append(f"  Loaded        : {len(tools)}")
    except Exception as exc:
        lines.append(f"  Status        : [unavailable — {exc}]")

    # Models
    lines.append("\nMODELS")
    try:
        lines.append(f"  {agent.model_manager.describe()}")
    except Exception as exc:
        lines.append(f"  Status        : [unavailable — {exc}]")

    # Health
    lines.append("\nHEALTH")
    try:
        tick = agent.mind.health_check()
        band = tick.band.value if hasattr(tick, "band") else "unknown"
        score = tick.score if hasattr(tick, "score") else "?"
        lines.append(f"  Band          : {band}")
        lines.append(f"  Score         : {score}")
    except Exception as exc:
        lines.append(f"  Status        : Healthy [detail unavailable — {exc}]")

    return "\n".join(lines)


def handle_version(agent: "SmartAgent", args: list[str]) -> str:
    """Display MARK's version information."""
    return (
        "MARK AI Operating System\n"
        "  Version       : 0.9\n"
        f"  Agent         : {agent.settings.agent_name}\n"
        "  Owner         : Mr. Smart\n"
        "  Architecture  : Brain v2 / Mind OS v1 / Knowledge Engine v1"
    )


def handle_clear(agent: "SmartAgent", args: list[str]) -> str:
    """Clear the terminal and redraw the banner."""
    os.system("clear")
    return renderer.banner(agent)


def handle_exit(agent: "SmartAgent", args: list[str]) -> str:
    """Signal the REPL to exit cleanly."""
    raise ExitConsole()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(router: CommandRouter) -> None:
    """Register all system commands with *router*."""
    # help is a closure so it can inspect the live router state.
    router.register("help", handle_help(router), "show available commands", "SYSTEM", 0)
    router.register("status", handle_status, "show system dashboard", "SYSTEM", 1)
    router.register("version", handle_version, "show version info", "SYSTEM", 2)
    router.register("clear", handle_clear, "clear screen and redraw banner", "SYSTEM", 3)
    router.register("exit", handle_exit, "exit MARK", "SYSTEM", 4)
    router.register("quit", handle_exit, "exit MARK", "SYSTEM", 5)
