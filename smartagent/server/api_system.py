"""
System-level API endpoints for the MARK dashboard.

Covers:
  GET  /git/status          — git status for workspace
  GET  /git/log             — recent commits
  GET  /git/diff            — diff for a commit ref
  GET  /memory              — list MARK memory files
  GET  /memory/file         — read a memory file
  GET  /models              — list Ollama models
  POST /models/switch       — change active model
  GET  /metrics             — CPU / RAM / disk snapshot
  GET  /workspace/detect    — detect workspace from CWD
  GET  /workspace/recent    — recently used workspaces
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: str, timeout: int = 10) -> tuple[str, str, int]:
    """Run a git command; returns (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, cwd=cwd, timeout=timeout,
        )
        return r.stdout, r.stderr, r.returncode
    except FileNotFoundError:
        return "", "git not found", 127
    except subprocess.TimeoutExpired:
        return "", "timed out", 1
    except Exception as exc:
        return "", str(exc), 1


def _active_workspace() -> str:
    """Return the current run's workspace, falling back to CWD."""
    # Import here to avoid circular import; _state lives in api.py
    try:
        from smartagent.server.api import _state  # type: ignore[attr-defined]
        ws = _state.workspace
        if ws and ws != ".":
            return os.path.abspath(ws)
    except Exception:
        pass
    return os.path.abspath(os.getcwd())


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

@router.get("/git/status")
async def git_status(workspace: str | None = Query(None)) -> dict:
    """Return porcelain git status for the workspace."""
    ws = workspace or _active_workspace()
    if not os.path.isdir(ws):
        raise HTTPException(404, f"Workspace not found: {ws}")

    # Branch / tracking info
    branch_out, _, rc = _git(["rev-parse", "--abbrev-ref", "HEAD"], ws)
    if rc != 0:
        return {"error": "Not a git repository", "workspace": ws}
    branch = branch_out.strip()

    # Ahead / behind
    ahead = behind = 0
    track_out, _, _ = _git(["rev-list", "--left-right", "--count", "@{u}...HEAD"], ws)
    if track_out.strip():
        parts = track_out.strip().split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])

    # Changed files (porcelain v1)
    porcelain, _, _ = _git(["status", "--porcelain"], ws)
    changes = []
    for line in porcelain.splitlines():
        if len(line) < 3:
            continue
        xy   = line[:2]
        path = line[3:].strip().strip('"')
        if " -> " in path:           # rename
            path = path.split(" -> ", 1)[1]
        changes.append({"status": xy.strip(), "path": path})

    return {
        "workspace": ws,
        "branch":    branch,
        "ahead":     ahead,
        "behind":    behind,
        "clean":     len(changes) == 0,
        "changes":   changes,
    }


@router.get("/git/log")
async def git_log(
    workspace: str | None = Query(None),
    limit: int = Query(30, ge=1, le=200),
) -> dict:
    """Return recent git commits."""
    ws = workspace or _active_workspace()
    sep = "|||"
    fmt = f"%H{sep}%h{sep}%s{sep}%an{sep}%ae{sep}%ai{sep}%D"
    out, err, rc = _git(["log", f"--max-count={limit}", f"--pretty=format:{fmt}"], ws)
    if rc != 0:
        return {"commits": [], "error": err.strip()}

    commits = []
    for line in out.strip().splitlines():
        parts = line.split(sep)
        if len(parts) < 6:
            continue
        commits.append({
            "hash":     parts[0],
            "short":    parts[1],
            "message":  parts[2],
            "author":   parts[3],
            "email":    parts[4],
            "date":     parts[5],
            "refs":     parts[6] if len(parts) > 6 else "",
        })
    return {"commits": commits, "workspace": ws}


@router.get("/git/diff")
async def git_diff(
    ref: str,
    workspace: str | None = Query(None),
) -> dict:
    """Return unified diff for a commit."""
    ws = workspace or _active_workspace()
    out, err, rc = _git(["show", "--stat", "--patch", ref], ws, timeout=20)
    if rc != 0:
        raise HTTPException(400, err.strip() or "git show failed")
    return {"diff": out, "ref": ref}


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@router.get("/memory")
async def memory_files(workspace: str | None = Query(None)) -> dict:
    """List MARK memory files (.agents/memory/)."""
    ws = workspace or _active_workspace()
    mem_dir = Path(ws) / ".agents" / "memory"
    if not mem_dir.is_dir():
        return {"files": [], "workspace": ws, "memory_dir": str(mem_dir), "exists": False}

    files = []
    for p in sorted(mem_dir.rglob("*.md")):
        try:
            text  = p.read_text(errors="replace")
            lines = text.splitlines()
            preview = " ".join(lines[:3])[:200] if lines else ""
        except Exception:
            text = preview = ""
        files.append({
            "name":    p.name,
            "path":    str(p.relative_to(mem_dir)),
            "full":    str(p),
            "size":    p.stat().st_size,
            "preview": preview,
        })
    return {"files": files, "workspace": ws, "memory_dir": str(mem_dir), "exists": True}


@router.get("/memory/file")
async def memory_file(path: str, workspace: str | None = Query(None)) -> dict:
    """Read a memory file by relative path."""
    ws = workspace or _active_workspace()
    mem_dir = Path(ws) / ".agents" / "memory"
    try:
        resolved = (mem_dir / path).resolve()
    except Exception as exc:
        raise HTTPException(400, str(exc))
    if not resolved.is_relative_to(mem_dir.resolve()):
        raise HTTPException(400, "Path escapes memory directory")
    if not resolved.is_file():
        raise HTTPException(404, f"File not found: {path}")
    content = resolved.read_text(errors="replace")
    return {"path": path, "content": content, "size": len(content)}


# ---------------------------------------------------------------------------
# Models (Ollama)
# ---------------------------------------------------------------------------

class SwitchModelRequest(BaseModel):
    model: str


_active_model: str = ""


@router.get("/models")
async def list_models() -> dict:
    """List available Ollama models."""
    import httpx
    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [
                {
                    "name":     m.get("name", ""),
                    "size_gb":  round(m.get("size", 0) / 1e9, 1),
                    "modified": m.get("modified_at", ""),
                    "family":   m.get("details", {}).get("family", ""),
                    "params":   m.get("details", {}).get("parameter_size", ""),
                }
                for m in data.get("models", [])
            ]
    except Exception as exc:
        return {"models": [], "active": _active_model, "error": str(exc)}

    # Try to detect active model from settings
    active = _active_model
    if not active:
        try:
            from smartagent.config.settings import Settings  # type: ignore
            settings = Settings()
            active = getattr(settings, "model", "") or ""
        except Exception:
            pass

    return {"models": models, "active": active, "ollama_url": ollama_url}


@router.post("/models/switch")
async def switch_model(req: SwitchModelRequest) -> dict:
    """Set the active Ollama model."""
    global _active_model
    _active_model = req.model
    return {"success": True, "model": _active_model}


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def system_metrics() -> dict:
    """Return a snapshot of CPU / RAM usage."""
    try:
        import psutil
        cpu_pct  = psutil.cpu_percent(interval=0.2)
        vm       = psutil.virtual_memory()
        disk     = psutil.disk_usage(os.getcwd())
        return {
            "cpu_pct":      round(cpu_pct, 1),
            "mem_pct":      round(vm.percent, 1),
            "mem_used_mb":  round(vm.used / 1e6, 0),
            "mem_total_mb": round(vm.total / 1e6, 0),
            "disk_pct":     round(disk.percent, 1),
            "disk_free_gb": round(disk.free / 1e9, 1),
        }
    except ImportError:
        return {"error": "psutil not installed", "cpu_pct": 0, "mem_pct": 0}
    except Exception as exc:
        return {"error": str(exc), "cpu_pct": 0, "mem_pct": 0}


# ---------------------------------------------------------------------------
# Workspace detection
# ---------------------------------------------------------------------------

_recent_workspaces: list[str] = []


@router.get("/workspace/detect")
async def workspace_detect() -> dict:
    """
    Detect the best workspace path to use.
    Returns the current active workspace, CWD, and git root if available.
    """
    cwd = os.path.abspath(os.getcwd())
    active = _active_workspace()

    # Try to find git root
    git_root_out, _, rc = _git(["rev-parse", "--show-toplevel"], cwd)
    git_root = git_root_out.strip() if rc == 0 else None

    candidates = []
    seen: set[str] = set()
    for p in [active, git_root, cwd]:
        if p and p not in seen:
            candidates.append(p)
            seen.add(p)

    return {
        "workspace":    active,
        "cwd":          cwd,
        "git_root":     git_root,
        "candidates":   candidates,
        "recent":       _recent_workspaces[-10:],
    }


@router.get("/workspace/recent")
async def workspace_recent() -> dict:
    """Return recently used workspace paths."""
    return {"recent": list(reversed(_recent_workspaces[-10:]))}


def record_workspace(path: str) -> None:
    """Called by the execute endpoint to track workspace history."""
    abs_path = os.path.abspath(path)
    if abs_path in _recent_workspaces:
        _recent_workspaces.remove(abs_path)
    _recent_workspaces.append(abs_path)
    # Keep at most 20
    if len(_recent_workspaces) > 20:
        _recent_workspaces.pop(0)
