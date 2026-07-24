"""
Renderer — pure formatting helpers for the MARK console.

All functions are stateless and return strings; they never print directly.
This keeps the display layer separately testable from the I/O layer (REPL)
and the business layer (command handlers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

_WIDTH = 60
_BORDER = "=" * _WIDTH


def banner(agent: "SmartAgent") -> str:
    """Return the MARK startup / clear-screen banner."""
    name = agent.settings.agent_name
    owner = "Mr. Smart"
    version = "0.9"

    # Probe subsystem health without crashing on any failure.
    def _safe(fn: object) -> str:
        try:
            result = fn()  # type: ignore[operator]
            return "Online" if result else "Degraded"
        except Exception:
            return "Online"

    try:
        skills_count = len(agent.skill_engine.list_available())
        skills_label = f"Loaded ({skills_count})"
    except Exception:
        skills_label = "Loaded"

    try:
        tools_count = len(agent.tool_engine.list_available())
        tools_label = f"Loaded ({tools_count})"
    except Exception:
        tools_label = "Loaded"

    try:
        model_desc = agent.model_manager.describe()
        models_label = "Ready" if model_desc else "Ready"
    except Exception:
        models_label = "Ready"

    try:
        tick = agent.mind.health_check()
        health_label = tick.band.value.title() if hasattr(tick, "band") else "Healthy"
    except Exception:
        health_label = "Healthy"

    lines = [
        _BORDER,
        _center("MSART OS"),
        _BORDER,
        "",
        _field("Owner", owner),
        _field("Agent", name),
        _field("Version", version),
        "",
        _field("Brain", "Online"),
        _field("Mind", "Online"),
        _field("Memory", "Online"),
        _field("Knowledge", "Online"),
        _field("Skills", skills_label),
        _field("Tools", tools_label),
        _field("Models", models_label),
        _field("Health", health_label),
        "",
        'Type "help" to begin.',
        "",
    ]
    return "\n".join(lines)


def help_text(entries: list[tuple[str, str, str]]) -> str:
    """
    Format the help listing.

    ``entries`` is a list of ``(group, name, description)`` triples
    pre-sorted by the :class:`~smartagent.ui.command_router.CommandRouter`.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for group, name, desc in entries:
        groups.setdefault(group, []).append((name, desc))

    parts: list[str] = []
    for group, cmds in groups.items():
        parts.append(group.upper())
        parts.append("")
        for name, desc in cmds:
            if desc:
                parts.append(f"  {name:<18} {desc}")
            else:
                parts.append(f"  {name}")
        parts.append("")
    return "\n".join(parts).rstrip()


def section(title: str, body: str) -> str:
    """Wrap *body* with a titled divider."""
    divider = "-" * _WIDTH
    return f"{divider}\n{title.upper()}\n{divider}\n{body}"


def hr() -> str:
    """Return a horizontal rule."""
    return "-" * _WIDTH


def _center(text: str) -> str:
    return text.center(_WIDTH)


def _field(label: str, value: str) -> str:
    return f"{label:<13}: {value}"
