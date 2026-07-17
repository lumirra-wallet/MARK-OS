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
    """
    List available models for the active provider (GitHub Models or Ollama).

    Returns a unified shape regardless of provider so the frontend needs no
    special-casing:
        { models: [{name, id, size_gb, modified, family, params, provider}],
          active, provider, ollama_url?, error? }
    """
    import httpx

    # Determine active provider
    try:
        from smartagent.llm.factory import get_active_provider, get_llm_settings
        provider = get_active_provider()
        settings = get_llm_settings()
    except Exception:
        provider = "ollama"
        settings = {}

    if provider == "github":
        token = os.environ.get("GITHUB_TOKEN", "")
        active = settings.get("model", "gpt-4.1")
        if not token:
            return {
                "models": [], "active": active, "provider": "github",
                "error": "GITHUB_TOKEN not set",
            }
        try:
            from smartagent.llm.github_provider import GitHubProvider, _GITHUB_MODEL_CATALOGUE
            p = GitHubProvider(token=token)
            p.load()
            raw_models = p.list_models()
            # Build a lookup so catalogue metadata (modified, params, size_gb) are
            # available even when the live endpoint returns bare ids.
            _cat: dict[str, dict] = {m["id"]: m for m in _GITHUB_MODEL_CATALOGUE}
            models = [
                {
                    "name":     m["id"],
                    "id":       m["id"],
                    "size_gb":  _cat.get(m["id"], {}).get("size_gb", 0),
                    "modified": _cat.get(m["id"], {}).get("modified", ""),
                    "family":   m.get("family", _cat.get(m["id"], {}).get("family", "")),
                    "params":   _cat.get(m["id"], {}).get("params", ""),
                    "context":  m.get("context", _cat.get(m["id"], {}).get("context", 128_000)),
                    "provider": "github",
                }
                for m in raw_models
            ]
            return {"models": models, "active": active, "provider": "github"}
        except Exception as exc:
            return {"models": [], "active": active, "provider": "github", "error": str(exc)}

    if provider == "nvidia":
        api_key = os.environ.get("NVIDIA_API_KEY", "")
        active = settings.get("model", "nvidia/nemotron-3-ultra-550b-a55b")
        if not api_key:
            return {
                "models": [], "active": active, "provider": "nvidia",
                "error": "NVIDIA_API_KEY not set",
            }
        try:
            from smartagent.llm.nvidia_provider import NvidiaProvider, _NVIDIA_MODEL_CATALOGUE
            p = NvidiaProvider(api_key=api_key)
            p.load()
            raw_models = p.list_models()
            _cat: dict[str, dict] = {m["id"]: m for m in _NVIDIA_MODEL_CATALOGUE}
            models = [
                {
                    "name":     m["id"],
                    "id":       m["id"],
                    "size_gb":  _cat.get(m["id"], {}).get("size_gb", 0),
                    "modified": _cat.get(m["id"], {}).get("modified", ""),
                    "family":   m.get("family", _cat.get(m["id"], {}).get("family", "")),
                    "params":   _cat.get(m["id"], {}).get("params", ""),
                    "context":  m.get("context", _cat.get(m["id"], {}).get("context", 128_000)),
                    "provider": "nvidia",
                }
                for m in raw_models
            ]
            return {"models": models, "active": active, "provider": "nvidia"}
        except Exception as exc:
            return {"models": [], "active": active, "provider": "nvidia", "error": str(exc)}

    if provider == "openai":
        active = settings.get("model", "gpt-4o-mini")
        try:
            from smartagent.llm.openai_provider import OpenAIProvider
            p = OpenAIProvider()
            raw_models = p.list_models()
            models = [
                {
                    "name":     m["id"],
                    "id":       m["id"],
                    "size_gb":  m.get("size_gb", 0),
                    "modified": m.get("modified", ""),
                    "family":   m.get("family", ""),
                    "params":   m.get("params", ""),
                    "context":  m.get("context", 128_000),
                    "provider": "openai",
                }
                for m in raw_models
            ]
            return {"models": models, "active": active, "provider": "openai"}
        except Exception as exc:
            return {"models": [], "active": active, "provider": "openai", "error": str(exc)}

    if provider == "anthropic":
        active = settings.get("model", "claude-haiku-3-5")
        try:
            from smartagent.llm.anthropic_provider import AnthropicProvider
            p = AnthropicProvider()
            raw_models = p.list_models()
            models = [
                {
                    "name":     m["id"],
                    "id":       m["id"],
                    "size_gb":  m.get("size_gb", 0),
                    "modified": m.get("modified", ""),
                    "family":   m.get("family", "claude"),
                    "params":   m.get("params", ""),
                    "context":  m.get("context", 200_000),
                    "provider": "anthropic",
                }
                for m in raw_models
            ]
            return {"models": models, "active": active, "provider": "anthropic"}
        except Exception as exc:
            return {"models": [], "active": active, "provider": "anthropic", "error": str(exc)}

    # Ollama (default)
    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    active = _active_model
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [
                {
                    "name":     m.get("name", ""),
                    "id":       m.get("name", ""),
                    "size_gb":  round(m.get("size", 0) / 1e9, 1),
                    "modified": m.get("modified_at", ""),
                    "family":   m.get("details", {}).get("family", ""),
                    "params":   m.get("details", {}).get("parameter_size", ""),
                    "provider": "ollama",
                }
                for m in data.get("models", [])
            ]
    except Exception as exc:
        return {"models": [], "active": active, "provider": "ollama",
                "ollama_url": ollama_url, "error": str(exc)}

    if not active:
        try:
            from smartagent.config.settings import Settings  # type: ignore
            s = Settings()
            active = getattr(s, "ollama_default_model", "") or ""
        except Exception:
            pass

    return {"models": models, "active": active, "provider": "ollama", "ollama_url": ollama_url}


@router.post("/models/switch")
async def switch_model(req: SwitchModelRequest) -> dict:
    """Set the active model (provider-aware)."""
    global _active_model
    try:
        from smartagent.llm.factory import get_active_provider, switch_provider
        provider = get_active_provider()
        switch_provider(provider, req.model)
        _active_model = req.model
    except Exception:
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


@router.get("/models/router")
async def get_model_router() -> dict:
    """Get current per-worker model routing config (Feature 15)."""
    from smartagent.server.model_router import get_all_routes
    return {"routes": get_all_routes()}


class ModelRouterUpdateRequest(BaseModel):
    routes: dict[str, str]


@router.post("/models/router")
async def update_model_router(req: ModelRouterUpdateRequest) -> dict:
    from smartagent.server.model_router import update_routes
    return {"routes": update_routes(req.routes)}


@router.post("/models/router/reset")
async def reset_model_router() -> dict:
    from smartagent.server.model_router import reset_routes
    return {"routes": reset_routes()}


def record_workspace(path: str) -> None:
    """Called by the execute endpoint to track workspace history."""
    abs_path = os.path.abspath(path)
    if abs_path in _recent_workspaces:
        _recent_workspaces.remove(abs_path)
    _recent_workspaces.append(abs_path)
    # Keep at most 20
    if len(_recent_workspaces) > 20:
        _recent_workspaces.pop(0)
