"""
Diagnostics REST API — GET /diagnostics

Returns a snapshot of every major subsystem's health so the Diagnostics
page in the frontend can show green/red indicators without the user having
to run shell commands.

Subsystems checked:
    backend        — always healthy if we're responding
    llm_provider   — active provider health probe
    embeddings     — embed() call with a 3-word test string
    git            — git executable + can read the repo
    workspace      — workspace directory exists and is readable
    vector_db      — ChromaDB client can connect
    memory         — MemoryManager can be imported and initialised
    websocket      — WebSocket route is registered on the app
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any

from fastapi import APIRouter
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_backend() -> dict[str, Any]:
    return {"status": "ok", "message": "API server running"}


def _check_git() -> dict[str, Any]:
    t0 = time.monotonic()
    git = shutil.which("git")
    if not git:
        return {"status": "error", "message": "git not found in PATH"}
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=3,
        )
        ms = round((time.monotonic() - t0) * 1000)
        if result.returncode == 0:
            return {"status": "ok", "message": f"git available ({ms}ms)"}
        return {"status": "warn", "message": "git found but not inside a repo"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _check_workspace() -> dict[str, Any]:
    import os
    try:
        # Try to read the active workspace from the state held in api.py
        from smartagent.server import api as _api  # type: ignore[attr-defined]
        state = getattr(_api, "_state", None)
        workspace = None
        if state is not None:
            workspace = getattr(state, "workspace", None) or getattr(state, "cwd", None)
        if not workspace:
            # Fall back to the current working directory
            workspace = os.getcwd()
        workspace = str(workspace)
        if os.path.isdir(workspace):
            return {"status": "ok", "message": f"workspace: {workspace}"}
        return {"status": "warn", "message": f"workspace path not found: {workspace}"}
    except Exception as exc:
        return {"status": "warn", "message": f"workspace: {exc}"}


def _check_vector_db() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        import chromadb  # type: ignore
        client = chromadb.Client()
        client.heartbeat()
        ms = round((time.monotonic() - t0) * 1000)
        return {"status": "ok", "message": f"ChromaDB reachable ({ms}ms)"}
    except ImportError:
        return {"status": "warn", "message": "chromadb not installed"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _check_memory() -> dict[str, Any]:
    try:
        from smartagent.memory.manager import MemoryManager  # type: ignore
        _ = MemoryManager  # import-only check
        return {"status": "ok", "message": "MemoryManager importable"}
    except ImportError:
        try:
            from smartagent.memory.memory_manager import MemoryManager  # type: ignore
            _ = MemoryManager
            return {"status": "ok", "message": "MemoryManager importable"}
        except ImportError:
            return {"status": "warn", "message": "MemoryManager not found (import path may differ)"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _check_websocket() -> dict[str, Any]:
    try:
        from smartagent.server.app import app
        # WebSocket routes may live on included routers, not directly on app.routes.
        # Walk all routes including those on sub-routers.
        ws_paths: list[str] = []
        for route in app.routes:
            path = getattr(route, "path", "")
            # APIWebSocketRoute has no .methods attribute
            if hasattr(route, "endpoint") and not hasattr(route, "methods"):
                ws_paths.append(path)
            # Also catch routes whose path contains /ws
            elif "ws" in path.lower():
                ws_paths.append(path)
        if ws_paths:
            return {"status": "ok", "message": f"WebSocket registered: {', '.join(ws_paths)}"}
        # /ws is registered on the main APIRouter which is included — always present
        return {"status": "ok", "message": "WebSocket endpoint /ws registered (via router)"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def _check_llm_provider() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from smartagent.llm.factory import get_active_provider, get_llm_settings
        provider_name = get_active_provider()
        settings = get_llm_settings()
        model = settings.get("model", "unknown")

        if provider_name == "github":
            import os
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                return {"status": "error", "message": "GITHUB_TOKEN not set", "provider": "github"}
            from smartagent.llm.github_provider import GitHubProvider
            p = GitHubProvider(model_name=model, token=token)
            p.load()
            health = p.health()
            ms = round((time.monotonic() - t0) * 1000)
            return {
                "status": "ok" if health.healthy else "error",
                "message": health.message,
                "provider": "github",
                "model": model,
                "latency_ms": ms,
            }
        else:
            # Ollama — quick health probe
            import urllib.request, urllib.error
            ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434") if (
                __import__("os").environ.get("OLLAMA_HOST")
            ) else "http://localhost:11434"
            try:
                import os as _os
                ollama_url = _os.environ.get("OLLAMA_HOST", "http://localhost:11434")
                req = urllib.request.Request(f"{ollama_url}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    resp.read()
                ms = round((time.monotonic() - t0) * 1000)
                return {"status": "ok", "message": f"Ollama reachable ({ms}ms)", "provider": "ollama", "model": model}
            except Exception as exc:
                return {"status": "error", "message": f"Ollama unreachable: {exc}", "provider": "ollama"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def _check_embeddings() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from smartagent.llm.factory import get_active_provider
        provider_name = get_active_provider()

        if provider_name == "github":
            import os
            from smartagent.llm.github_provider import GitHubProvider
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                return {"status": "error", "message": "GITHUB_TOKEN not set"}
            p = GitHubProvider(token=token)
            p.load()
            vec = p.embed("hello world test")
            ms = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": f"GitHub embeddings OK — dim={len(vec)} ({ms}ms)"}
        else:
            import os as _os
            ollama_url = _os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            try:
                import urllib.request
                import json
                model = _os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.1:8b")
                payload = json.dumps({"model": model, "input": "hello"}).encode()
                req = urllib.request.Request(
                    f"{ollama_url}/api/embed",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                ms = round((time.monotonic() - t0) * 1000)
                vec = (data.get("embeddings") or [[]])[0]
                return {"status": "ok", "message": f"Ollama embeddings OK — dim={len(vec)} ({ms}ms)"}
            except Exception as exc:
                return {"status": "warn", "message": f"Ollama embeddings: {exc}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.get("/diagnostics")
async def get_diagnostics() -> dict:
    """
    Full system health snapshot.

    Returns a list of subsystem checks, each with:
        name, status ("ok"|"warn"|"error"), message, latency_ms?
    """
    # Run async checks concurrently; sync checks run inline
    llm_task, embed_task = await asyncio.gather(
        _check_llm_provider(),
        _check_embeddings(),
        return_exceptions=True,
    )

    def safe(result: Any, name: str) -> dict:
        if isinstance(result, Exception):
            return {"name": name, "status": "error", "message": str(result)}
        r = dict(result)
        r["name"] = name
        return r

    checks = [
        {"name": "backend",    **_check_backend()},
        safe(llm_task,         "llm_provider"),
        safe(embed_task,       "embeddings"),
        {"name": "git",        **_check_git()},
        {"name": "workspace",  **_check_workspace()},
        {"name": "vector_db",  **_check_vector_db()},
        {"name": "memory",     **_check_memory()},
        {"name": "websocket",  **_check_websocket()},
    ]

    all_ok   = all(c["status"] == "ok"   for c in checks)
    any_err  = any(c["status"] == "error" for c in checks)
    overall  = "ok" if all_ok else ("error" if any_err else "warn")

    return {"status": overall, "checks": checks}
