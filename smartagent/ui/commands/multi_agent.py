"""
Multi-agent console commands — Milestone 17: Multi-Agent Collaboration.

Commands registered:
    teams            — list all registered teams and their task types
    team <name>      — details for a specific team
    ceo-plan <goal>  — preview the CEO's decomposition without executing
    ceo <goal>       — run the full multi-agent pipeline

All commands delegate to ``agent.ceo`` (a ``CEOAgent`` instance wired in
``SmartAgent.__init__``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# teams — list all registered teams
# ---------------------------------------------------------------------------

def handle_teams(agent: "SmartAgent", args: list[str]) -> str:
    """
    List all registered teams and their task types.

    Usage:  teams
    """
    ceo = getattr(agent, "ceo", None)
    if ceo is None:
        return "[error] Multi-agent system is not available (agent.ceo is None)."

    teams = ceo.team_registry.list_teams()
    if not teams:
        return "No teams registered."

    lines = [f"Teams  ({len(teams)} registered)", ""]
    for t in teams:
        types_str = ", ".join(t.task_type_names)
        lines.append(f"  {t.emoji or '·'} {t.name:20s}  [{types_str}]")
        lines.append(f"    {t.description}")
        if t.lead:
            lines.append(f"    Lead: {t.lead}")
        lines.append("")
    lines += [
        "  Use 'team <name>'    to inspect a specific team.",
        "  Use 'ceo <goal>'     to run the full multi-agent pipeline.",
        "  Use 'ceo-plan <goal>' to preview the decomposition first.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# team — detail view for one team
# ---------------------------------------------------------------------------

def handle_team(agent: "SmartAgent", args: list[str]) -> str:
    """
    Show details for a specific team.

    Usage:  team <name>
    Example: team engineering
    """
    ceo = getattr(agent, "ceo", None)
    if ceo is None:
        return "[error] Multi-agent system is not available."

    if not args:
        teams = ceo.team_registry.names()
        names = "  " + "\n  ".join(teams)
        return f"Usage: team <name>\n\nAvailable teams:\n{names}"

    name = args[0].lower()
    team = ceo.team_registry.get(name)
    if team is None:
        available = ", ".join(ceo.team_registry.names())
        return (
            f"[error] Team {name!r} not found.\n"
            f"Available teams: {available}"
        )

    lines = [
        f"{team.emoji or '·'} Team: {team.name}",
        "─" * 50,
        f"  Description : {team.description}",
    ]
    if team.lead:
        lines.append(f"  Lead role   : {team.lead}")
    lines.append(f"  Task types  : {', '.join(team.task_type_names)}")
    lines.append(f"  Goal template:")
    lines.append(f"    {team.goal_template}")
    lines.append("")
    lines.append(
        f"  Example sub-goal for 'Build a weather API':\n"
        f"    {team.build_goal('Build a weather API')[:140]}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ceo-plan — preview decomposition
# ---------------------------------------------------------------------------

def handle_ceo_plan(agent: "SmartAgent", args: list[str]) -> str:
    """
    Preview how the CEO would decompose a goal, without executing.

    Usage:  ceo-plan <goal>
    Example: ceo-plan Build a FastAPI weather service with OpenWeatherMap
    """
    ceo = getattr(agent, "ceo", None)
    if ceo is None:
        return "[error] Multi-agent system is not available."

    if not args:
        return (
            "Usage: ceo-plan <goal>\n"
            "Example: ceo-plan Build a FastAPI weather service\n\n"
            "Shows the CEO's decomposition into team assignments without executing.\n"
            "Use 'ceo <goal>' to run the full pipeline."
        )

    goal = " ".join(args)
    try:
        plan = ceo.preview_plan(goal)
    except Exception as exc:  # noqa: BLE001
        return f"[error] Could not plan: {exc}"

    lines = plan.as_display_lines()
    lines += [
        "",
        "  Use 'ceo <goal>' to execute this plan.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ceo — full multi-agent execution
# ---------------------------------------------------------------------------

def handle_ceo(agent: "SmartAgent", args: list[str]) -> str:
    """
    Run a goal through the full multi-agent pipeline.

    Usage:  ceo <goal>
    Example: ceo Build a FastAPI weather service with OpenWeatherMap

    The CEO decomposes the goal into team assignments, then runs each team
    in sequence (research → engineering → qa → documentation) with context
    chaining so each team builds on the previous team's output.
    """
    ceo = getattr(agent, "ceo", None)
    if ceo is None:
        return "[error] Multi-agent system is not available."

    if not args:
        return (
            "Usage: ceo <goal>\n"
            "Example: ceo Build a FastAPI weather service\n\n"
            "Runs the full multi-agent pipeline:\n"
            "  1. CEO decomposes goal into team assignments\n"
            "  2. Research team gathers intelligence\n"
            "  3. Engineering team builds the solution\n"
            "  4. QA team tests and validates\n"
            "  5. Documentation team writes docs\n\n"
            "Use 'ceo-plan <goal>' to preview the plan without executing."
        )

    goal = " ".join(args)
    try:
        result = ceo.execute(goal)
    except Exception as exc:  # noqa: BLE001
        return f"[error] Multi-agent execution failed: {exc}"

    return "\n".join(result.as_display_lines())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(router: CommandRouter) -> None:
    """Register multi-agent commands with *router*."""
    router.register(
        "teams", handle_teams,
        "teams — list all registered teams and their task types",
        "MULTI-AGENT", 0,
    )
    router.register(
        "team", handle_team,
        "team <name> — inspect a specific team",
        "MULTI-AGENT", 1,
    )
    router.register(
        "ceo-plan", handle_ceo_plan,
        "ceo-plan <goal> — preview CEO decomposition without executing",
        "MULTI-AGENT", 2,
    )
    router.register(
        "ceo", handle_ceo,
        "ceo <goal> — run the full multi-agent pipeline (CEO → teams → workers)",
        "MULTI-AGENT", 3,
    )
