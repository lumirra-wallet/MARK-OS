"""
Project Memory console commands — Milestone 22.

Commands registered:
    project show [name]   — show a project's profile
    project set <k> <v>   — set a field on the active/named project
    project get <k>       — read a field from the active/named project
    project scan [path]   — auto-detect tech stack from files
    project list          — list all remembered projects
    project note <text>   — add a note to the active project
    project delete <name> — remove a project profile
    project help          — show this listing
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


def _pm(agent: "SmartAgent"):
    pm = getattr(agent, "project_memory", None)
    if pm is None:
        raise RuntimeError("ProjectMemory is not available on this agent.")
    return pm


def _active_profile(agent: "SmartAgent"):
    """Return the active project profile, creating it from workspace if possible."""
    pm = _pm(agent)
    # Try to derive name/path from active workspace
    ws_mgr = getattr(agent, "workspace_manager", None)
    name = "default"
    path = "."
    if ws_mgr is not None and ws_mgr.active is not None:
        ws = ws_mgr.active
        name = getattr(ws, "name", "default")
        path = getattr(ws, "path", ".")
    return pm.load(name, path)


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------

def _sub_show(agent: "SmartAgent", args: list[str]) -> str:
    pm = _pm(agent)
    if args:
        profile = pm.load(args[0])
    else:
        try:
            profile = _active_profile(agent)
        except RuntimeError as exc:
            return f"[error] {exc}"
    lines = ["  Project Memory:"] + profile.as_display_lines()
    return "\n".join(lines)


def _sub_set(agent: "SmartAgent", args: list[str]) -> str:
    if len(args) < 2:
        return (
            "Usage: project set <key> <value>\n"
            "Example: project set framework FastAPI\n"
            "Known keys: language, framework, test_runner, package_manager, database, style_checker\n"
            "Special keys: tool (adds to tool list), note (adds a note)"
        )
    pm = _pm(agent)
    profile = _active_profile(agent)
    key   = args[0]
    value = " ".join(args[1:])
    pm.set(profile, key, value)
    return f"  ✓ {profile.name}: {key} = {value}"


def _sub_get(agent: "SmartAgent", args: list[str]) -> str:
    if not args:
        return "Usage: project get <key>"
    pm = _pm(agent)
    profile = _active_profile(agent)
    val = pm.get(profile, args[0])
    if val:
        return f"  {args[0]} = {val}"
    return f"  {args[0]} is not set (project: {profile.name})"


def _sub_scan(agent: "SmartAgent", args: list[str]) -> str:
    pm = _pm(agent)
    if args:
        import os
        path = os.path.abspath(args[0])
        profile = pm.load(args[0].split("/")[-1] or "scanned", path)
    else:
        try:
            profile = _active_profile(agent)
        except RuntimeError as exc:
            return f"[error] {exc}"
    detected = pm.scan(profile)
    lines = [f"  Scanning: {profile.path}", ""]
    lines += [f"  {d}" for d in detected]
    return "\n".join(lines)


def _sub_list(agent: "SmartAgent", args: list[str]) -> str:
    pm = _pm(agent)
    projects = pm.list_projects()
    if not projects:
        return "  No projects remembered yet.  Use 'project set' or 'project scan'."
    lines = [f"  Projects ({len(projects)}):"]
    for p in projects:
        lines.append(pm.summary(p))
    return "\n".join(lines)


def _sub_note(agent: "SmartAgent", args: list[str]) -> str:
    if not args:
        return "Usage: project note <text>"
    pm = _pm(agent)
    profile = _active_profile(agent)
    note = " ".join(args)
    pm.set(profile, "note", note)
    return f"  ✓ Note added to {profile.name}: {note}"


def _sub_delete(agent: "SmartAgent", args: list[str]) -> str:
    if not args:
        return "Usage: project delete <name>"
    pm = _pm(agent)
    if pm.delete(args[0]):
        return f"  ✓ Deleted project: {args[0]}"
    return f"  Project {args[0]!r} not found."


def _sub_help(*_) -> str:
    return """\
  Project Memory commands:

    project show [name]       — show a project's remembered tech stack
    project set <key> <value> — set a field on the active project
    project get <key>         — read a field from the active project
    project scan [path]       — auto-detect tech stack from project files
    project list              — list all remembered projects
    project note <text>       — add a note to the active project
    project delete <name>     — remove a project profile
    project help              — show this listing

  Known keys:  language, framework, test_runner, package_manager, database, style_checker
  Special keys: tool (appends to tool list), note (appends a note)

  Example:
    project set framework FastAPI
    project set test_runner pytest
    project set language Python
    project scan /path/to/my-api\
"""


_DISPATCH = {
    "show":   _sub_show,
    "set":    _sub_set,
    "get":    _sub_get,
    "scan":   _sub_scan,
    "list":   _sub_list,
    "note":   _sub_note,
    "delete": _sub_delete,
    "help":   _sub_help,
}


def handle_project(agent: "SmartAgent", args: list[str]) -> str:
    """
    Project Memory commands.

    Usage: project <sub-command> [args…]

    Run 'project help' for a full listing.
    """
    if not args:
        return _sub_show(agent, [])
    sub  = args[0].lower()
    rest = args[1:]
    handler = _DISPATCH.get(sub)
    if handler is None:
        return (
            f"Unknown project sub-command: {sub!r}\n"
            "Run 'project help' for available commands."
        )
    try:
        return handler(agent, rest)
    except RuntimeError as exc:
        return f"[error] {exc}"


def register(router: CommandRouter) -> None:
    """Register all project-memory commands with *router*."""
    router.register(
        "project", handle_project,
        "project <sub> — Project Memory (show, set, get, scan, list, note)",
        "PROJECT", 0,
    )
