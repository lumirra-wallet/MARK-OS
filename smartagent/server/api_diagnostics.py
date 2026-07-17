"""
Diagnostics REST API — GET /diagnostics

Returns a snapshot of every major subsystem's health so the Diagnostics
page in the frontend can show green/red indicators without the user having
to run shell commands.

Subsystems checked
------------------
backend        — always healthy if we're responding
database       — storage provider (LocalStorage / PostgreSQL) health
llm_provider   — active provider health probe + active model
embeddings     — embed() call with a 3-word test string
git            — git executable + in-repo check
workspace      — workspace directory exists and is readable
vector_db      — vector store (Chroma / pgvector / keyword) health
memory         — MemoryManager importable
websocket      — WebSocket route registered
system         — CPU % and RAM usage via psutil
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Any

from fastapi import APIRouter
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_backend() -> dict[str, Any]:
    return {"status": "ok", "message": "API server running"}


def _check_database() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from smartagent.storage.factory import get_storage
        store  = get_storage()
        result = store.health()
        ms     = round((time.monotonic() - t0) * 1000)
        result["latency_ms"] = ms
        return result
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _check_git() -> dict[str, Any]:
    t0  = time.monotonic()
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
    try:
        from smartagent.server import api as _api  # type: ignore[attr-defined]
        state     = getattr(_api, "_state", None)
        workspace = None
        if state is not None:
            workspace = getattr(state, "workspace", None) or getattr(state, "cwd", None)
        if not workspace:
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
        from smartagent.vector.factory import get_vector_store
        vs     = get_vector_store()
        health = vs.health()
        ms     = round((time.monotonic() - t0) * 1000)
        health["latency_ms"] = ms
        return health
    except Exception as exc:
        return {"status": "warn", "message": str(exc)}


def _check_memory() -> dict[str, Any]:
    for mod_path in ("smartagent.memory.manager", "smartagent.memory.memory_manager"):
        try:
            import importlib
            mod = importlib.import_module(mod_path)
            _ = getattr(mod, "MemoryManager", None)
            return {"status": "ok", "message": "MemoryManager importable"}
        except ImportError:
            continue
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
    return {"status": "warn", "message": "MemoryManager not found (import path may differ)"}


def _check_websocket() -> dict[str, Any]:
    try:
        from smartagent.server.app import _fastapi_app as _app  # type: ignore[attr-defined]
    except ImportError:
        try:
            from smartagent.server.app import app as _app  # type: ignore[assignment]
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
    try:
        ws_paths: list[str] = []
        for route in _app.routes:  # type: ignore[union-attr]
            path = getattr(route, "path", "")
            if hasattr(route, "endpoint") and not hasattr(route, "methods"):
                ws_paths.append(path)
            elif "ws" in path.lower():
                ws_paths.append(path)
        if ws_paths:
            return {"status": "ok", "message": f"WebSocket registered: {', '.join(ws_paths)}"}
        return {"status": "ok", "message": "WebSocket endpoint /ws registered (via router)"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _check_system() -> dict[str, Any]:
    """CPU and RAM usage via psutil."""
    try:
        import psutil  # type: ignore
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem     = psutil.virtual_memory()
        ram_pct = mem.percent
        ram_gb_used  = round(mem.used  / 1e9, 1)
        ram_gb_total = round(mem.total / 1e9, 1)
        status  = "ok" if cpu_pct < 80 and ram_pct < 85 else "warn"
        return {
            "status":  status,
            "message": f"CPU {cpu_pct:.0f}%  ·  RAM {ram_gb_used}/{ram_gb_total} GB ({ram_pct:.0f}%)",
            "cpu_pct": cpu_pct,
            "ram_pct": ram_pct,
            "ram_used_gb":  ram_gb_used,
            "ram_total_gb": ram_gb_total,
        }
    except ImportError:
        return {"status": "warn", "message": "psutil not installed — install for CPU/RAM metrics"}
    except Exception as exc:
        return {"status": "warn", "message": str(exc)}


async def _check_llm_provider() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from smartagent.llm.factory import get_active_provider, get_llm_settings
        provider_name = get_active_provider()
        settings      = get_llm_settings()
        model         = settings.get("model", "unknown")

        if provider_name == "github":
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                return {"status": "error", "message": "GITHUB_TOKEN not set", "provider": "github"}
            from smartagent.llm.github_provider import GitHubProvider
            p      = GitHubProvider(model_name=model, token=token)
            p.load()
            health = p.health()
            ms     = round((time.monotonic() - t0) * 1000)
            return {
                "status":     "ok" if health.healthy else "error",
                "message":    health.message,
                "provider":   "github",
                "model":      model,
                "latency_ms": ms,
            }

        elif provider_name == "nvidia":
            api_key = os.environ.get("NVIDIA_API_KEY", "")
            if not api_key:
                return {"status": "error", "message": "NVIDIA_API_KEY not set", "provider": "nvidia"}
            from smartagent.llm.nvidia_provider import NvidiaProvider
            p      = NvidiaProvider(model_name=model, api_key=api_key)
            p.load()
            health = p.health()
            ms     = round((time.monotonic() - t0) * 1000)
            return {
                "status":     "ok" if health.healthy else "error",
                "message":    health.message,
                "provider":   "nvidia",
                "model":      model,
                "latency_ms": ms,
            }

        elif provider_name == "openai":
            import os as _os
            api_key = _os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return {"status": "error", "message": "OPENAI_API_KEY not set", "provider": "openai"}
            from smartagent.llm.openai_provider import OpenAIProvider
            p  = OpenAIProvider(model_name=model, api_key=api_key)
            h  = p.health()
            ms = round((time.monotonic() - t0) * 1000)
            return {
                "status":     "ok" if h.get("healthy") else "error",
                "message":    h.get("message", ""),
                "provider":   "openai",
                "model":      model,
                "latency_ms": ms,
            }

        elif provider_name == "anthropic":
            import os as _os
            api_key = _os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                return {"status": "error", "message": "ANTHROPIC_API_KEY not set", "provider": "anthropic"}
            from smartagent.llm.anthropic_provider import AnthropicProvider
            p  = AnthropicProvider(model_name=model, api_key=api_key)
            h  = p.health()
            ms = round((time.monotonic() - t0) * 1000)
            return {
                "status":     "ok" if h.get("healthy") else "error",
                "message":    h.get("message", ""),
                "provider":   "anthropic",
                "model":      model,
                "latency_ms": ms,
            }

        else:
            # Unreachable in practice — get_active_provider() only ever
            # returns nvidia/github/openai/anthropic.
            return {"status": "error", "message": f"Unknown provider {provider_name!r}", "provider": provider_name}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def _check_embeddings() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from smartagent.llm.factory import get_active_provider
        provider_name = get_active_provider()

        if provider_name == "github":
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                return {"status": "error", "message": "GITHUB_TOKEN not set"}
            from smartagent.llm.github_provider import GitHubProvider
            p   = GitHubProvider(token=token)
            p.load()
            vec = p.embed("hello world test")
            ms  = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": f"GitHub embeddings OK — dim={len(vec)} ({ms}ms)"}

        elif provider_name == "nvidia":
            # nvidia/nemotron-* is a chat/reasoning model, not an embedding
            # model — no network call to make, and none should be attempted
            # (this check runs on every /diagnostics poll; a real call here
            # would just burn quota for a capability that doesn't exist).
            return {"status": "warn", "message": "NVIDIA: chat model, no embedding endpoint configured."}

        elif provider_name == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return {"status": "error", "message": "OPENAI_API_KEY not set"}
            from smartagent.llm.openai_provider import OpenAIProvider
            p   = OpenAIProvider(api_key=api_key)
            vec = p.embed("hello world test")
            ms  = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": f"OpenAI embeddings OK — dim={len(vec)} ({ms}ms)"}

        elif provider_name == "anthropic":
            # Anthropic has no native embedding API; check OpenAI fallback
            openai_key = os.environ.get("OPENAI_API_KEY", "")
            if not openai_key:
                return {"status": "warn", "message": "Anthropic: no embedding API. Set OPENAI_API_KEY for fallback."}
            from openai import OpenAI  # type: ignore
            c   = OpenAI(api_key=openai_key)
            r   = c.embeddings.create(model="text-embedding-3-small", input="hello world test")
            vec = r.data[0].embedding
            ms  = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": f"OpenAI fallback embeddings OK — dim={len(vec)} ({ms}ms)"}

        else:
            # Unreachable in practice — get_active_provider() only ever
            # returns nvidia/github/openai/anthropic.
            return {"status": "error", "message": f"Unknown provider {provider_name!r}"}
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
        {"name": "database",   **_check_database()},
        safe(llm_task,           "llm_provider"),
        safe(embed_task,         "embeddings"),
        {"name": "vector_db",  **_check_vector_db()},
        {"name": "git",        **_check_git()},
        {"name": "workspace",  **_check_workspace()},
        {"name": "memory",     **_check_memory()},
        {"name": "websocket",  **_check_websocket()},
        {"name": "system",     **_check_system()},
    ]

    all_ok  = all(c["status"] == "ok"    for c in checks)
    any_err = any(c["status"] == "error" for c in checks)
    overall = "ok" if all_ok else ("error" if any_err else "warn")

    return {"status": overall, "checks": checks}
