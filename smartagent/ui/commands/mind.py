"""
Mind commands: mind, identity, health, state, attention, context.

All operations go through ``agent.mind`` (ExecutiveController).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_mind(agent: "SmartAgent", args: list[str]) -> str:
    """Show a full description of MARK's current mental state."""
    try:
        return agent.mind.describe()
    except Exception as exc:
        return f"[error] Mind describe failed: {exc}"


def handle_identity(agent: "SmartAgent", args: list[str]) -> str:
    """Display MARK's identity from the SelfModel."""
    try:
        sm = agent.mind.self_model()
        lines = [
            "MARK Identity",
            "",
            f"  Agent name    : {sm.agent_name}",
            f"  Mission       : {sm.mission}",
            f"  Current goal  : {sm.current_goal or 'None'}",
            f"  Current task  : {sm.current_task or 'None'}",
            f"  State         : {sm.state}",
            f"  Confidence    : {sm.confidence:.2f}",
            f"  Health score  : {sm.health_score:.2f}",
        ]
        if sm.capabilities:
            lines.append(f"  Capabilities  : {', '.join(sm.capabilities[:8])}")
        if sm.recent_changes:
            lines.append("")
            lines.append("  Recent changes:")
            for change in sm.recent_changes[-3:]:
                lines.append(f"    - {change}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Identity unavailable: {exc}"


def handle_health(agent: "SmartAgent", args: list[str]) -> str:
    """Run a health check and display the result."""
    try:
        tick = agent.mind.health_check()
        lines = ["MARK Health Check", ""]
        if hasattr(tick, "band"):
            lines.append(f"  Band          : {tick.band.value}")
        if hasattr(tick, "score"):
            lines.append(f"  Score         : {tick.score:.2f}" if isinstance(tick.score, float) else f"  Score : {tick.score}")
        if hasattr(tick, "metrics") and tick.metrics:
            m = tick.metrics
            lines.append("")
            lines.append("  Metrics:")
            for attr in ("memory_usage", "task_load", "error_rate", "queue_length", "average_latency"):
                val = getattr(m, attr, None)
                if val is not None:
                    lines.append(f"    {attr:<22}: {val}")
        if hasattr(tick, "notes") and tick.notes:
            lines.append("")
            lines.append("  Notes:")
            for note in tick.notes:
                lines.append(f"    - {note}")
        if hasattr(tick, "notify_owner") and tick.notify_owner:
            lines.append("")
            lines.append("  ⚠  Owner notification recommended.")
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Health check failed: {exc}"


def handle_state(agent: "SmartAgent", args: list[str]) -> str:
    """Show MARK's current internal state."""
    try:
        sm = agent.mind.self_model()
        lines = [
            "MARK Internal State",
            "",
            f"  State         : {sm.state}",
            f"  Confidence    : {sm.confidence:.2f}",
            f"  Health score  : {sm.health_score:.2f}",
            f"  Current task  : {sm.current_task or 'None'}",
            f"  Current goal  : {sm.current_goal or 'None'}",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] State unavailable: {exc}"


def handle_attention(agent: "SmartAgent", args: list[str]) -> str:
    """Show what MARK is currently focused on."""
    try:
        sm = agent.mind.self_model()
        processes = agent.mind.running_processes()
        lines = ["MARK Attention", ""]
        if processes:
            lines.append("  Active focus:")
            for p in processes[:5]:
                lines.append(f"    - {p}")
        else:
            lines.append("  Focus         : idle — no active tasks")
        lines.append(f"  State         : {sm.state}")
        # Priority queue
        try:
            pq = agent.mind.priority_queue()
            if pq:
                lines.append("")
                lines.append(f"  Priority queue ({len(pq)} items):")
                for item in pq[:3]:
                    lines.append(f"    - {item}")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Attention unavailable: {exc}"


def handle_context(agent: "SmartAgent", args: list[str]) -> str:
    """Show the current context bundle assembled by the ContextManager."""
    try:
        bundle = agent.mind.build_context(max_tokens=800)
        rendered = bundle.render(max_length=1200) if hasattr(bundle, "render") else str(bundle)
        if not rendered:
            return "Context bundle is empty."
        return f"MARK Context Bundle\n\n{rendered}"
    except Exception as exc:
        return f"[error] Context unavailable: {exc}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(router: CommandRouter) -> None:
    """Register all mind commands with *router*."""
    router.register("mind", handle_mind, "show full mental state", "MIND", 0)
    router.register("identity", handle_identity, "show MARK's identity", "MIND", 1)
    router.register("health", handle_health, "run a health check", "MIND", 2)
    router.register("state", handle_state, "show current internal state", "MIND", 3)
    router.register("attention", handle_attention, "show current focus", "MIND", 4)
    router.register("context", handle_context, "show context bundle", "MIND", 5)
