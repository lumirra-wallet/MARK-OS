"""
AgentTools — the core tool set that makes MARK autonomous.

Provides:
    TOOL_DEFINITIONS   OpenAI-compatible function-calling definitions.
    execute_tool()     Single dispatcher: name + args → string result.
    requires_approval()  True for destructive/irreversible operations.

All filesystem paths are validated against the workspace root to prevent
path-traversal.  Terminal commands run with a hard timeout.  Output is
truncated at MAX_OUTPUT_CHARS to avoid flooding the context window.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

# Maximum characters returned from any single tool call.
MAX_OUTPUT_CHARS = 8_000

# ────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible tool definitions
# ────────────────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file in the workspace. "
                "Use this before editing to understand what already exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root (e.g. 'src/main.py').",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write (or overwrite) a file in the workspace.  Creates parent "
                "directories automatically.  Use this to create new files or "
                "save changes to existing ones."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text content to write.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and subdirectories at a path (two levels deep by default). "
                "Use this to understand project structure before acting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to workspace root. Defaults to '.' (workspace root).",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "How many levels deep to list (1–3). Default 2.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_workspace",
            "description": (
                "Search for text inside files in the workspace (grep-style). "
                "Returns file paths and matching lines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for.",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Glob to restrict search (e.g. '*.py', '*.ts').  Defaults to all files.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_terminal",
            "description": (
                "Execute a shell command in the workspace and return stdout + stderr. "
                "Use for pytest, npm, pnpm, pip install, cargo, go test, etc. "
                "Commands time out after 60 s."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute (runs via /bin/sh -c).",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory relative to workspace root.  Defaults to workspace root.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show the current git status of the workspace (staged, unstaged, untracked).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show the current unstaged diff in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": (
                "Stage all changes (git add -A) and create a commit.  "
                "Use after completing a task to checkpoint progress."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message.",
                    },
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_file",
            "description": "Rename or move a file within the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {
                        "type": "string",
                        "description": "Current path (relative to workspace root).",
                    },
                    "dst": {
                        "type": "string",
                        "description": "New path (relative to workspace root).",
                    },
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Permanently delete a file from the workspace.  "
                "REQUIRES user approval — do not call unless the user explicitly said to delete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root.",
                    },
                },
                "required": ["path"],
            },
        },
    },
]

# ────────────────────────────────────────────────────────────────────────────
# Permission model
# ────────────────────────────────────────────────────────────────────────────

_APPROVAL_REQUIRED: frozenset[str] = frozenset({
    "delete_file",
    "git_push",
    "run_production_deploy",
    "database_migrate",
    "rm_rf",
})


def requires_approval(tool_name: str) -> bool:
    """True when *tool_name* is a destructive/irreversible operation."""
    return tool_name in _APPROVAL_REQUIRED


# ────────────────────────────────────────────────────────────────────────────
# Path safety
# ────────────────────────────────────────────────────────────────────────────

def _safe_path(workspace: str, rel: str) -> Path:
    """
    Resolve *rel* against *workspace* and raise ValueError on path traversal.

    Uses ``resolve()`` + ``is_relative_to()`` rather than a string
    ``startswith()`` check — the latter would wrongly accept a sibling
    directory whose name happens to share the workspace path as a string
    prefix (e.g. workspace ``/a/project`` vs. target ``/a/project-evil``).
    """
    base   = Path(workspace).resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Path traversal blocked: {rel!r} resolves outside workspace.")
    return target


#: Tool names that mutate the filesystem — the only ones subject to the
#: per-task ``allowed_paths`` scope (reads stay unrestricted so MARK can
#: still build context; least-privilege applies to what gets changed).
_WRITE_TOOLS = frozenset({"write_file", "rename_file", "delete_file"})


def _is_path_allowed(rel_path: str, workspace: str, allowed_paths: list[str] | None) -> bool:
    """True if *rel_path* is within *allowed_paths* (or scoping is off)."""
    if not allowed_paths:
        return True
    try:
        target = _safe_path(workspace, rel_path)
    except ValueError:
        return False
    for allowed in allowed_paths:
        try:
            if target == _safe_path(workspace, allowed):
                return True
        except ValueError:
            continue
    return False


def _truncate(text: str, label: str = "output") -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return (
        text[:half]
        + f"\n\n… [{label} truncated — {len(text) - MAX_OUTPUT_CHARS} chars omitted] …\n\n"
        + text[-half:]
    )


# ────────────────────────────────────────────────────────────────────────────
# Executor
# ────────────────────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict[str, Any], workspace_path: str) -> str:
    """
    Dispatch *name* with *args* against *workspace_path*.

    Returns a UTF-8 string (stdout / content / error message).
    Callers should pass the result back to the LLM as a tool message.
    """
    try:
        return _DISPATCH[name](args, workspace_path)
    except KeyError:
        return f"Unknown tool: {name!r}"
    except Exception as exc:
        logger.warning("AgentTools: tool %r failed: %s", name, exc)
        return f"Tool error ({name}): {exc}"


# ── Individual implementations ───────────────────────────────────────────────

def _read_file(args: dict, ws: str) -> str:
    path = _safe_path(ws, args["path"])
    if not path.exists():
        return f"File not found: {args['path']!r}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return _truncate(text, label="file content")
    except Exception as exc:
        return f"Could not read {args['path']!r}: {exc}"


def _write_file(args: dict, ws: str) -> str:
    path    = _safe_path(ws, args["path"])
    content = args["content"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Written {len(content)} characters to {args['path']!r}."
    except Exception as exc:
        return f"Could not write {args['path']!r}: {exc}"


def _list_directory(args: dict, ws: str) -> str:
    rel   = args.get("path", ".")
    depth = min(int(args.get("depth", 2)), 3)
    base  = _safe_path(ws, rel)
    if not base.exists():
        return f"Directory not found: {rel!r}"

    lines: list[str] = [f"Directory: {rel}/"]

    def _walk(d: Path, indent: int, remaining: int) -> None:
        if remaining <= 0:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith(".") and entry.name not in (".env",):
                continue
            prefix  = "  " * indent
            if entry.is_dir():
                lines.append(f"{prefix}{entry.name}/")
                _walk(entry, indent + 1, remaining - 1)
            else:
                size = entry.stat().st_size
                size_str = f"{size:,} B" if size < 1024 else f"{size // 1024} KB"
                lines.append(f"{prefix}{entry.name}  ({size_str})")

    _walk(base, 1, depth)
    return "\n".join(lines)


def _search_workspace(args: dict, ws: str) -> str:
    query   = args["query"]
    pattern = args.get("file_pattern", "")
    cmd     = ["grep", "-r", "-n", "--include=" + pattern if pattern else "--include=*", query, ws]
    if not pattern:
        cmd = ["grep", "-r", "-n", query, ws]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, cwd=ws,
        )
        out = (r.stdout + r.stderr).strip()
        # Strip absolute workspace prefix for readability
        out = out.replace(ws + os.sep, "").replace(ws + "/", "")
        return _truncate(out or "(no matches)", label="search results") if out else "(no matches)"
    except subprocess.TimeoutExpired:
        return "Search timed out."
    except FileNotFoundError:
        # grep not available — fallback via Python
        results: list[str] = []
        for root, _, files in os.walk(ws):
            for fname in files:
                if pattern and not fname.endswith(pattern.lstrip("*")):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    for lineno, line in enumerate(
                        open(fpath, encoding="utf-8", errors="replace"), 1
                    ):
                        if query.lower() in line.lower():
                            rel = os.path.relpath(fpath, ws)
                            results.append(f"{rel}:{lineno}: {line.rstrip()}")
                except Exception:
                    pass
        return _truncate("\n".join(results) or "(no matches)", label="search results")


def _run_terminal(args: dict, ws: str) -> str:
    command = args["command"]
    cwd_rel = args.get("cwd", ".")
    cwd     = str(_safe_path(ws, cwd_rel))
    try:
        r = subprocess.run(
            command,
            shell=True,
            executable="/bin/sh",
            capture_output=True,
            text=True,
            timeout=60,
            cwd=cwd,
        )
        out = (r.stdout + ("\n" + r.stderr if r.stderr else "")).strip()
        prefix = f"[exit {r.returncode}]\n" if r.returncode != 0 else ""
        return _truncate(prefix + (out or "(no output)"), label="terminal output")
    except subprocess.TimeoutExpired:
        return "[exit timeout] Command exceeded 60-second limit."
    except Exception as exc:
        return f"Terminal error: {exc}"


def _git_status(args: dict, ws: str) -> str:
    r = subprocess.run(
        ["git", "status"], capture_output=True, text=True, cwd=ws, timeout=10,
    )
    return (r.stdout + r.stderr).strip() or "(nothing to report)"


def _git_diff(args: dict, ws: str) -> str:
    r = subprocess.run(
        ["git", "diff"], capture_output=True, text=True, cwd=ws, timeout=10,
    )
    out = (r.stdout + r.stderr).strip()
    return _truncate(out or "(no changes)", label="diff")


def _git_commit(args: dict, ws: str) -> str:
    message = args["message"]
    add = subprocess.run(
        ["git", "add", "-A"], capture_output=True, text=True, cwd=ws, timeout=10,
    )
    if add.returncode != 0:
        return f"git add failed: {add.stderr.strip()}"
    commit = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True, text=True, cwd=ws, timeout=15,
    )
    out = (commit.stdout + commit.stderr).strip()
    return out or f"Committed: {message}"


def _rename_file(args: dict, ws: str) -> str:
    src = _safe_path(ws, args["src"])
    dst = _safe_path(ws, args["dst"])
    if not src.exists():
        return f"Source not found: {args['src']!r}"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return f"Renamed {args['src']!r} → {args['dst']!r}"
    except Exception as exc:
        return f"Rename failed: {exc}"


def _delete_file(args: dict, ws: str) -> str:
    """Only reachable after approval gating in the loop."""
    path = _safe_path(ws, args["path"])
    if not path.exists():
        return f"File not found: {args['path']!r}"
    try:
        path.unlink()
        return f"Deleted {args['path']!r}"
    except Exception as exc:
        return f"Delete failed: {exc}"


_DISPATCH: dict[str, Any] = {
    "read_file":       _read_file,
    "write_file":      _write_file,
    "list_directory":  _list_directory,
    "search_workspace": _search_workspace,
    "run_terminal":    _run_terminal,
    "git_status":      _git_status,
    "git_diff":        _git_diff,
    "git_commit":      _git_commit,
    "rename_file":     _rename_file,
    "delete_file":     _delete_file,
}
