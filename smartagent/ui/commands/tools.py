"""
Tools command: tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


def handle_tools(agent: "SmartAgent", args: list[str]) -> str:
    """List all loaded tools with name, description, and availability."""
    try:
        tools = agent.tool_engine.list_available()
        if not tools:
            return "No tools loaded."
        lines = [f"Tools ({len(tools)} loaded)", ""]
        for t in tools:
            name = str(t.get("name", t.get("id", "?")))
            desc = str(t.get("description", ""))
            avail = t.get("available", t.get("enabled", True))
            avail_label = "✓ available" if avail else "✗ unavailable"
            desc_short = (desc[:56] + "…") if len(desc) > 56 else desc
            lines.append(f"  {avail_label}  {name}")
            if desc_short:
                lines.append(f"             {desc_short}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Could not list tools: {exc}"


def register(router: CommandRouter) -> None:
    """Register the tools command with *router*."""
    router.register("tools", handle_tools, "list loaded tools", "TOOLS", 0)
