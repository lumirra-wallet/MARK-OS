"""
Models command: models.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


def handle_models(agent: "SmartAgent", args: list[str]) -> str:
    """
    Display registered model providers, loaded/active provider, and health.

    No Ollama integration — reports only what the Model Framework v1 knows.
    """
    try:
        lines = ["Models", ""]

        # Registered providers.
        try:
            available = agent.model_manager.list_available()
            if available:
                lines.append("  Registered providers:")
                for m in available:
                    mid = m.get("id", "?")
                    status = m.get("status", "?")
                    lines.append(f"    - {mid}  [{status}]")
            else:
                lines.append("  Registered providers: none")
        except Exception as exc:
            lines.append(f"  Registered providers: [unavailable — {exc}]")

        # Active / loaded provider.
        lines.append("")
        try:
            desc = agent.model_manager.describe()
            lines.append(f"  Active model: {desc}")
        except Exception as exc:
            lines.append(f"  Active model: [unavailable — {exc}]")

        # Health.
        lines.append("")
        try:
            health = agent.model_manager.health_check()
            lines.append(f"  Health: {health}")
        except Exception as exc:
            lines.append(f"  Health: [unavailable — {exc}]")

        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Could not retrieve model info: {exc}"


def register(router: CommandRouter) -> None:
    """Register the models command with *router*."""
    router.register("models", handle_models, "show model providers and status", "MODELS", 0)
