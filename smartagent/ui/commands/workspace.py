"""
Workspace console commands — Milestone 15: Project Workspace Manager.

Commands registered:
    workspace <sub>  — CRUD and lifecycle for named project workspaces
    goal <text>      — set a goal on the active workspace and pre-load a plan

Subcommands for ``workspace``:
    create <name>    — create and activate a new workspace
    open   <name>    — activate an existing workspace
    list             — list all workspaces
    status           — show active workspace dashboard
    close            — deactivate the current workspace
    delete <name>    — delete a workspace (requires it to be closed first)
    export [name]    — zip-archive a workspace
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter
from smartagent.workspace.workspace_manager import WorkspaceError

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# workspace — main dispatcher
# ---------------------------------------------------------------------------

def handle_workspace(agent: "SmartAgent", args: list[str]) -> str:
    """
    Project workspace management.

    Usage:  workspace <subcommand> [args]

    Subcommands:
        create <name>   — create and activate a workspace
        open   <name>   — switch to an existing workspace
        list            — show all workspaces
        status          — dashboard for the active workspace
        close           — deactivate the current workspace
        delete <name>   — permanently delete a workspace
        export [name]   — zip-export a workspace
    """
    if not args:
        return _help()

    sub = args[0].lower()
    dispatch = {
        "create": _handle_create,
        "open":   _handle_open,
        "list":   _handle_list,
        "status": _handle_status,
        "close":  _handle_close,
        "delete": _handle_delete,
        "export": _handle_export,
    }
    if sub in dispatch:
        return dispatch[sub](agent, args[1:])
    return (
        f"Unknown workspace subcommand: {sub!r}\n\n" + _help()
    )


def _help() -> str:
    return (
        "workspace — project workspace manager\n"
        "\n"
        "  workspace create <name>   create and activate a new workspace\n"
        "  workspace open   <name>   switch to an existing workspace\n"
        "  workspace list            list all workspaces\n"
        "  workspace status          dashboard for the active workspace\n"
        "  workspace close           deactivate the current workspace\n"
        "  workspace delete <name>   delete a workspace permanently\n"
        "  workspace export [name]   zip-archive a workspace\n"
        "\n"
        "Example workflow:\n"
        "  workspace create weather-api\n"
        "  goal Build a FastAPI weather service\n"
        "  run\n"
    )


def _handle_create(agent: "SmartAgent", args: list[str]) -> str:
    """Create and immediately activate a workspace."""
    if not args:
        return (
            "Usage: workspace create <name>\n"
            "Example: workspace create weather-api\n"
            "\n"
            "Name rules: lowercase letters, digits, hyphens; 3-63 chars.\n"
            "Examples: 'calculator', 'weather-api', 'my-project-v2'"
        )
    name = args[0].lower()
    try:
        ws = agent.workspace_manager.create(name)
        agent.workspace_manager.activate(name)
        return "\n".join([
            f"✓ Workspace {name!r} created and activated.",
            f"  Path: {ws.path}",
            "",
            "  Next steps:",
            f"    goal <text>   — set a goal and pre-load a plan",
            f"    plan <text>   — decompose a goal into tasks",
            f"    run           — execute the current plan",
        ])
    except (ValueError, WorkspaceError) as exc:
        return f"[error] {exc}"


def _handle_open(agent: "SmartAgent", args: list[str]) -> str:
    """Activate an existing workspace."""
    if not args:
        workspaces = agent.workspace_manager.list_workspaces()
        if not workspaces:
            return (
                "Usage: workspace open <name>\n"
                "No workspaces found — use 'workspace create <name>' first."
            )
        names = "  " + "\n  ".join(ws.name for ws in workspaces)
        return f"Usage: workspace open <name>\n\nAvailable workspaces:\n{names}"

    name = args[0].lower()
    try:
        ws = agent.workspace_manager.activate(name)
    except WorkspaceError as exc:
        return f"[error] {exc}"

    lines = [f"✓ Workspace {name!r} activated."]
    if ws.active_goal:
        lines.append(f"  Active goal : {ws.active_goal}")
    lines += [
        f"  Runs        : {ws.run_count}",
        f"  Lessons     : {ws.lesson_count}",
        f"  Files       : {ws.file_count()} in output/",
    ]
    if ws.last_run_at:
        lines.append(f"  Last run    : {ws.last_run_at}")
    lines += [
        "",
        "  Use 'goal <text>' or 'plan <text>' to continue work.",
    ]
    return "\n".join(lines)


def _handle_list(agent: "SmartAgent", args: list[str]) -> str:
    """List all workspaces."""
    workspaces = agent.workspace_manager.list_workspaces()
    if not workspaces:
        return (
            "No workspaces found.\n"
            "Use 'workspace create <name>' to create one.\n"
            "Example: workspace create weather-api"
        )

    active = agent.workspace_manager.active
    lines = [f"Workspaces  ({len(workspaces)} total)", ""]
    for ws in workspaces:
        marker = " ← active" if active and ws.name == active.name else ""
        lines.append(
            f"  {ws.name:32s}  [{ws.status:8s}]  "
            f"runs={ws.run_count}  lessons={ws.lesson_count}{marker}"
        )
        if ws.active_goal:
            preview = ws.active_goal[:64] + "…" if len(ws.active_goal) > 64 else ws.active_goal
            lines.append(f"    Goal: {preview}")
    lines += [
        "",
        "  workspace open <name>    — switch to a workspace",
        "  workspace create <name>  — create a new workspace",
    ]
    return "\n".join(lines)


def _handle_status(agent: "SmartAgent", args: list[str]) -> str:
    """Show the active workspace dashboard."""
    ws = agent.workspace_manager.active
    if ws is None:
        return (
            "No workspace is currently active.\n"
            "Use 'workspace open <name>' or 'workspace create <name>'."
        )

    file_count = ws.file_count()
    hist_count = ws.history_count()

    lines = [
        f"Workspace: {ws.name}",
        "─" * 50,
        f"  Status      : {ws.status}",
        f"  Path        : {ws.path}",
        f"  Created     : {ws.created_at}",
    ]
    if ws.active_goal:
        goal_preview = ws.active_goal[:70] + "…" if len(ws.active_goal) > 70 else ws.active_goal
        lines.append(f"  Active goal : {goal_preview}")
    if ws.goals:
        lines.append(f"  Goals set   : {len(ws.goals)}")
    lines += [
        f"  Runs        : {ws.run_count}",
        f"  History     : {hist_count} execution record(s)",
        f"  Output files: {file_count}",
        f"  Lessons     : {ws.lesson_count}",
    ]
    if ws.last_run_at:
        lines.append(f"  Last run    : {ws.last_run_at}")

    # Show recent output files if any
    from smartagent.workspace.file_output import list_output_files
    output_files = list_output_files(ws)
    if output_files:
        lines.append("")
        lines.append("  Output files:")
        for f in output_files[:10]:
            lines.append(f"    {f}")
        if len(output_files) > 10:
            lines.append(f"    … and {len(output_files) - 10} more")

    lines += [
        "",
        "  goal <text>   — set a new goal and pre-load a plan",
        "  run           — execute the current plan",
        "  workspace close — deactivate this workspace",
    ]
    return "\n".join(lines)


def _handle_close(agent: "SmartAgent", args: list[str]) -> str:
    """Deactivate the current workspace."""
    active = agent.workspace_manager.active
    if active is None:
        return "No workspace is currently active."
    name = active.name
    agent.workspace_manager.deactivate()
    return (
        f"✓ Workspace {name!r} closed.  Now in global context.\n"
        "  Memory, knowledge, and execution history are back to global defaults."
    )


def _handle_delete(agent: "SmartAgent", args: list[str]) -> str:
    """Delete a workspace permanently."""
    if not args:
        return (
            "Usage: workspace delete <name>\n"
            "Warning: this permanently deletes all workspace files.\n"
            "Close the workspace first with 'workspace close'."
        )
    name = args[0].lower()
    if not agent.workspace_manager.exists(name):
        return f"[error] Workspace {name!r} does not exist."

    active = agent.workspace_manager.active
    if active and active.name == name:
        return (
            f"Workspace {name!r} is currently active.\n"
            "Close it first:\n"
            "  workspace close\n"
            f"  workspace delete {name}"
        )

    try:
        agent.workspace_manager.delete(name)
        return f"✓ Workspace {name!r} deleted permanently."
    except WorkspaceError as exc:
        return f"[error] {exc}"


def _handle_export(agent: "SmartAgent", args: list[str]) -> str:
    """Zip-archive a workspace."""
    if args:
        name = args[0].lower()
    else:
        active = agent.workspace_manager.active
        if active is None:
            return (
                "Usage: workspace export <name>\n"
                "Or activate a workspace first and run 'workspace export' with no argument."
            )
        name = active.name

    if not agent.workspace_manager.exists(name):
        return f"[error] Workspace {name!r} does not exist."

    try:
        archive_path = agent.workspace_manager.export_zip(name)
        return f"✓ Workspace {name!r} exported.\n  Archive: {archive_path}"
    except Exception as exc:  # noqa: BLE001
        return f"[error] Export failed: {exc}"


# ---------------------------------------------------------------------------
# goal — set workspace goal and pre-load a plan
# ---------------------------------------------------------------------------

def handle_goal(agent: "SmartAgent", args: list[str]) -> str:
    """
    Set a goal on the active workspace and pre-load a task plan.

    Usage:  goal <goal text>
    Example: goal Build a FastAPI weather service with OpenWeatherMap

    If a workspace is active the goal is also persisted to goals.md.
    The plan is loaded automatically — use 'run' to execute it.
    """
    if not args:
        return (
            "Usage: goal <goal text>\n"
            "Example: goal Build a FastAPI weather service\n"
            "\n"
            "Sets the goal on the active workspace (if any) and pre-loads a plan.\n"
            "Use 'run' to execute the plan."
        )

    goal = " ".join(args)
    lines: list[str] = []

    # Persist to workspace if one is active
    ws = getattr(agent, "workspace_manager", None)
    if ws is not None and ws.active is not None:
        try:
            ws.set_goal(goal)
            lines.append(f"✓ Goal set on workspace {ws.active.name!r}.")
        except WorkspaceError as exc:
            lines.append(f"[warn] Could not persist goal: {exc}")

    # Pre-load the plan
    try:
        context = agent.executive.plan(goal)
    except ValueError as exc:
        lines.append(f"[error] {exc}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"[error] Could not plan goal: {exc}")
        return "\n".join(lines)

    lines += [
        f"✓ Plan ready — {context.task_count} task(s).",
        "",
    ]
    lines.extend(context.task_graph.as_display_lines())
    lines += [
        "",
        "  Use 'run' to execute.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(router: CommandRouter) -> None:
    """Register workspace and goal commands with *router*."""
    router.register(
        "workspace", handle_workspace,
        "workspace <sub> — manage project workspaces (create/open/list/status/close/delete/export)",
        "WORKSPACE", 0,
    )
    router.register(
        "goal", handle_goal,
        "goal <text> — set a goal on the active workspace and pre-load a plan",
        "WORKSPACE", 1,
    )
