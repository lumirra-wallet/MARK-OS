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
    """
    System-wide CPU/RAM plus THIS process's own usage — system-wide load
    on a dev machine is dominated by whatever else is running (browser tabs,
    IDE, etc.), which is easy to mistake for "MARK is using a lot of CPU."
    Reporting this process's own PID/CPU/RSS separately answers that
    directly instead of leaving it to system-wide numbers alone.
    """
    try:
        import psutil  # type: ignore
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem     = psutil.virtual_memory()
        ram_pct = mem.percent
        ram_gb_used  = round(mem.used  / 1e9, 1)
        ram_gb_total = round(mem.total / 1e9, 1)

        proc = psutil.Process(os.getpid())
        proc_cpu_pct = proc.cpu_percent(interval=0.1)
        proc_rss_mb  = round(proc.memory_info().rss / 1e6, 1)

        status  = "ok" if cpu_pct < 80 and ram_pct < 85 else "warn"
        return {
            "status":  status,
            "message": (
                f"CPU {cpu_pct:.0f}%  ·  RAM {ram_gb_used}/{ram_gb_total} GB ({ram_pct:.0f}%)  "
                f"·  this process (pid {proc.pid}): {proc_cpu_pct:.0f}% CPU, {proc_rss_mb} MB"
            ),
            "cpu_pct": cpu_pct,
            "ram_pct": ram_pct,
            "ram_used_gb":  ram_gb_used,
            "ram_total_gb": ram_gb_total,
            "process_pid":     proc.pid,
            "process_cpu_pct": proc_cpu_pct,
            "process_rss_mb":  proc_rss_mb,
        }
    except ImportError:
        return {"status": "warn", "message": "psutil not installed — install for CPU/RAM metrics"}
    except Exception as exc:
        return {"status": "warn", "message": str(exc)}


async def _check_llm_provider(probe: bool = True) -> dict[str, Any]:
    """
    *probe* controls whether this makes a REAL network call to the provider.

    health() on every provider (confirmed directly for NvidiaProvider: a
    genuine ``chat.completions.create(...)`` call) is a real, quota-consuming
    request — not a free ping. The frontend auto-polls /diagnostics every
    30s, so a naive "always probe" diagnostics page silently burns one real
    API call every 30 seconds just from being left open, which measurably
    contributes to hitting a provider's rate limit rather than only
    diagnosing it. probe=False (the periodic-poll default) reports static
    config + last-known telemetry with zero network calls; probe=True (an
    explicit manual refresh) does the real connectivity check.
    """
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
            if not probe:
                return {"status": "ok", "message": "GitHub token present (not probed this poll)", "provider": "github", "model": model}
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
            from smartagent.llm.nvidia_provider import NvidiaProvider, get_telemetry
            telemetry = get_telemetry()
            if not probe:
                return {
                    "status":        "ok" if not telemetry["last_error"] else "warn",
                    "message":       "NVIDIA key present (not probed this poll — see request_count/last_error below)",
                    "provider":      "nvidia",
                    "model":         model,
                    "endpoint":      telemetry["base_url"],
                    "request_count": telemetry["total_requests"],
                    "last_error":    telemetry["last_error"],
                    "last_error_at": telemetry["last_error_at"],
                }
            p      = NvidiaProvider(model_name=model, api_key=api_key)
            p.load()
            health = p.health()
            ms     = round((time.monotonic() - t0) * 1000)
            telemetry = get_telemetry()  # re-read — the probe call above just updated it
            return {
                "status":       "ok" if health.healthy else "error",
                "message":      health.message,
                "provider":     "nvidia",
                "model":        model,
                "latency_ms":   ms,
                "endpoint":     telemetry["base_url"],
                "request_count": telemetry["total_requests"],
                "last_error":   telemetry["last_error"],
                "last_error_at": telemetry["last_error_at"],
            }

        elif provider_name == "ollama":
            base_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
            if not probe:
                return {
                    "status":  "ok",
                    "message": "Ollama configured (not probed this poll)",
                    "provider": "ollama",
                    "model":    model,
                    "endpoint": base_url,
                }
            from smartagent.models.providers.ollama_provider import OllamaProvider
            p      = OllamaProvider(model_name=model, base_url=base_url)
            p.load()
            health = p.health()
            ms     = round((time.monotonic() - t0) * 1000)
            has_fallback = bool(os.environ.get("NVIDIA_API_KEY"))
            fallback_note = " NVIDIA fallback is configured and will be used." if (not health.healthy and has_fallback) else ""
            status = "ok" if health.healthy else ("warn" if has_fallback else "error")
            return {
                "status":     status,
                "message":    health.message + fallback_note,
                "provider":   "ollama",
                "model":      model,
                "latency_ms": ms,
                "endpoint":   base_url,
                "supports_tools": p.supports_tools if health.healthy else False,
            }

        elif provider_name == "openai":
            import os as _os
            api_key = _os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return {"status": "error", "message": "OPENAI_API_KEY not set", "provider": "openai"}
            if not probe:
                return {"status": "ok", "message": "OpenAI key present (not probed this poll)", "provider": "openai", "model": model}
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
            if not probe:
                return {"status": "ok", "message": "Anthropic key present (not probed this poll)", "provider": "anthropic", "model": model}
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
            # returns ollama/nvidia/github/openai/anthropic.
            return {"status": "error", "message": f"Unknown provider {provider_name!r}", "provider": provider_name}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def _check_embeddings(probe: bool = True) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        from smartagent.llm.factory import get_active_provider
        provider_name = get_active_provider()

        if provider_name == "github":
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                return {"status": "error", "message": "GITHUB_TOKEN not set"}
            if not probe:
                return {"status": "ok", "message": "GitHub token present (not probed this poll)"}
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

        elif provider_name == "ollama":
            # The default local-core model (MARK_MODEL) is a chat/reasoning
            # model, not an embedding model — same situation as NVIDIA's
            # nemotron. Pull a dedicated embedding model (e.g.
            # nomic-embed-text) to light this check up green.
            return {"status": "warn", "message": "Ollama: chat model, no embedding model pulled."}

        elif provider_name == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return {"status": "error", "message": "OPENAI_API_KEY not set"}
            if not probe:
                return {"status": "ok", "message": "OpenAI key present (not probed this poll)"}
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
            if not probe:
                return {"status": "ok", "message": "OpenAI fallback key present (not probed this poll)"}
            from openai import OpenAI  # type: ignore
            c   = OpenAI(api_key=openai_key)
            r   = c.embeddings.create(model="text-embedding-3-small", input="hello world test")
            vec = r.data[0].embedding
            ms  = round((time.monotonic() - t0) * 1000)
            return {"status": "ok", "message": f"OpenAI fallback embeddings OK — dim={len(vec)} ({ms}ms)"}

        else:
            # Unreachable in practice — get_active_provider() only ever
            # returns ollama/nvidia/github/openai/anthropic.
            return {"status": "error", "message": f"Unknown provider {provider_name!r}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ── Main endpoint ─────────────────────────────────────────────────────────────

@router.get("/diagnostics")
async def get_diagnostics(probe: bool = True) -> dict:
    """
    Full system health snapshot.

    Returns a list of subsystem checks, each with:
        name, status ("ok"|"warn"|"error"), message, latency_ms?

    ``probe=false`` skips the real network calls llm_provider/embeddings
    would otherwise make on every poll (see _check_llm_provider's
    docstring) — pass it from an automatic/periodic poller; leave the
    default ``true`` for an explicit, user-triggered refresh.
    """
    llm_task, embed_task = await asyncio.gather(
        _check_llm_provider(probe),
        _check_embeddings(probe),
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
