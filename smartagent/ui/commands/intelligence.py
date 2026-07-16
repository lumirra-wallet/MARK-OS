"""
Intelligence console commands — Milestone 18: Workspace Intelligence.

Commands registered:
    scan [path]   — scan a project directory and display MARK's mental model
    snapshot      — re-display the most recent scan result

The ``scan`` command builds a :class:`~smartagent.workspace.scanner.ProjectSnapshot`
covering:

  • file graph    (language breakdown, total file and test counts)
  • dependency graph  (packages from requirements.txt / pyproject.toml)
  • import graph  (Python AST import relationships)
  • module map    (dotted module name → file path)
  • git status    (branch, last commit, working-tree changes)
  • architecture  (pattern detected: MVC, DDD, Layered, …)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Shared state — most recent snapshot per session
# ---------------------------------------------------------------------------

_last_snapshot = None   # type: ignore[assignment]


# ---------------------------------------------------------------------------
# scan — full project scan
# ---------------------------------------------------------------------------

def handle_scan(agent: "SmartAgent", args: list[str]) -> str:
    """
    Scan a project directory and build MARK's mental model.

    Usage:  scan [path]
    Examples:
        scan                  — scan the current working directory
        scan /path/to/project — scan a specific directory
        scan .                — scan the cwd explicitly

    Output includes:
        • Architecture pattern (MVC, DDD, Layered, …)
        • File and test counts
        • Language breakdown
        • Declared dependencies
        • Git branch, last commit, and working-tree changes
        • Import graph edge count
        • Module map size
    """
    global _last_snapshot

    from smartagent.workspace.scanner import ProjectScanner

    # Resolve the target directory
    if args:
        raw = " ".join(args)
        target = os.path.abspath(raw)
    else:
        # Default: active workspace project_path, then cwd
        ws = getattr(agent, "workspace_manager", None)
        if ws is not None and ws.active is not None:
            target = ws.active.path
        else:
            target = os.getcwd()

    if not os.path.isdir(target):
        return (
            f"[error] Not a directory: {target!r}\n"
            "Usage: scan [path]"
        )

    print(f"  Scanning {target} …", flush=True)

    try:
        scanner  = ProjectScanner(root=target)
        snapshot = scanner.scan()
    except Exception as exc:  # noqa: BLE001
        return f"[error] Scan failed: {exc}"

    _last_snapshot = snapshot

    # Persist the snapshot text into the active workspace if one is open
    ws = getattr(agent, "workspace_manager", None)
    if ws is not None and ws.active is not None:
        try:
            from smartagent.workspace.file_output import write_output_file
            summary_text = snapshot.as_summary_text()
            write_output_file(ws.active, ".mark/project-snapshot.md", summary_text)
        except Exception:  # noqa: BLE001
            pass  # Non-critical — don't surface to user

    # Also store the snapshot on the agent for workers to access
    if hasattr(agent, "__dict__"):
        agent.__dict__["_project_snapshot"] = snapshot

    return "\n".join(snapshot.as_display_lines())


# ---------------------------------------------------------------------------
# snapshot — re-display most recent scan
# ---------------------------------------------------------------------------

def handle_snapshot(agent: "SmartAgent", args: list[str]) -> str:
    """
    Re-display the most recent project scan result.

    Usage:  snapshot

    If no scan has been run in this session, prompts to run 'scan' first.
    """
    global _last_snapshot

    # Also check if stored on agent
    if _last_snapshot is None:
        snap = getattr(agent, "_project_snapshot", None)
        if snap is not None:
            _last_snapshot = snap

    if _last_snapshot is None:
        return (
            "No scan result available for this session.\n"
            "Run 'scan' or 'scan <path>' first."
        )

    return "\n".join(_last_snapshot.as_display_lines())


# ---------------------------------------------------------------------------
# imports — show the import graph for the scanned project
# ---------------------------------------------------------------------------

def handle_imports(agent: "SmartAgent", args: list[str]) -> str:
    """
    Show the import relationships for the most recent scan.

    Usage:  imports [module]

    With no argument: show a summary of all import edges.
    With a module name: show what that module imports and what imports it.

    Example:
        imports
        imports smartagent.brain.agent
    """
    global _last_snapshot

    snap = _last_snapshot or getattr(agent, "_project_snapshot", None)
    if snap is None:
        return "No scan result.  Run 'scan' first."

    if not snap.import_edges:
        return "No Python import edges found in the most recent scan."

    if args:
        query = args[0]
        outbound = [
            e for e in snap.import_edges
            if query in e.from_file or e.from_file.endswith(query)
        ]
        inbound = [
            e for e in snap.import_edges
            if query in e.to_module
        ]
        lines = [
            f"Import graph for: {query!r}",
            f"  Outbound ({len(outbound)} import statements):",
        ]
        for e in outbound[:20]:
            lines.append(f"    {e.from_file}  →  {e.to_module}")
        if len(outbound) > 20:
            lines.append(f"    … and {len(outbound) - 20} more")
        lines += [
            "",
            f"  Inbound ({len(inbound)} files import this):",
        ]
        for e in inbound[:20]:
            lines.append(f"    {e.from_file}")
        if len(inbound) > 20:
            lines.append(f"    … and {len(inbound) - 20} more")
        return "\n".join(lines)

    # Summary mode
    total = len(snap.import_edges)
    unique_sources = len({e.from_file for e in snap.import_edges})
    unique_targets = len({e.to_module for e in snap.import_edges})
    lines = [
        f"Import graph summary",
        f"  Total edges     : {total}",
        f"  Source files    : {unique_sources}",
        f"  Imported modules: {unique_targets}",
        "",
        "  Top imported modules:",
    ]
    from collections import Counter
    counts = Counter(e.to_module for e in snap.import_edges)
    for mod, cnt in counts.most_common(10):
        lines.append(f"    {mod:<50s}  ×{cnt}")
    lines += [
        "",
        "  Use 'imports <module>' to drill into a specific module.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(router: CommandRouter) -> None:
    """Register intelligence commands with *router*."""
    router.register(
        "scan", handle_scan,
        "scan [path] — scan a project directory and build MARK's mental model",
        "INTELLIGENCE", 0,
    )
    router.register(
        "snapshot", handle_snapshot,
        "snapshot — re-display the most recent project scan",
        "INTELLIGENCE", 1,
    )
    router.register(
        "imports", handle_imports,
        "imports [module] — show import graph from the most recent scan",
        "INTELLIGENCE", 2,
    )
