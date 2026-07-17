"""
Provider Management REST API.

Endpoints
---------
GET  /providers              — list available providers + capabilities
GET  /providers/current      — currently active provider & model
POST /providers/switch       — switch provider (and optionally model)
POST /models/select          — select a specific model within current provider
GET  /health/llm             — LLM-specific health check (latency + token validity)
GET  /llm/settings           — get all LLM settings
POST /llm/settings           — update LLM settings (temperature, max_tokens, etc.)
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel as PydanticModel

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class SwitchProviderRequest(PydanticModel):
    provider: str           # "github" | "ollama"
    model: str | None = None


class SelectModelRequest(PydanticModel):
    model: str


class LlmSettingsUpdate(PydanticModel):
    temperature: float | None = None
    max_tokens: int | None = None
    streaming: bool | None = None
    github_model: str | None = None
    github_coding_model: str | None = None
    ollama_model: str | None = None
    ollama_coding_model: str | None = None


# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

_PROVIDER_CATALOGUE = [
    {
        "id":          "github",
        "name":        "GitHub Models",
        "description": "Cloud-hosted models via GitHub Models inference API",
        "base_url":    "https://models.github.ai/inference",
        "requires_token": True,
        "token_env":   "GITHUB_TOKEN",
        "capabilities": ["chat", "streaming", "embeddings", "tool_calling"],
        "default_model": "gpt-4.1",
    },
    {
        "id":          "ollama",
        "name":        "Ollama",
        "description": "Locally-running open-source models via Ollama",
        "base_url":    os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        "requires_token": False,
        "token_env":   None,
        "capabilities": ["chat", "streaming"],
        "default_model": "llama3.1:8b",
    },
    {
        "id":          "openai",
        "name":        "OpenAI",
        "description": "OpenAI GPT-4o and GPT-4o-mini models",
        "base_url":    os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "requires_token": True,
        "token_env":   "OPENAI_API_KEY",
        "capabilities": ["chat", "streaming", "embeddings", "tool_calling"],
        "default_model": "gpt-4o-mini",
    },
    {
        "id":          "anthropic",
        "name":        "Anthropic",
        "description": "Anthropic Claude — Opus 4.5, Sonnet 4.5, and Haiku 3.5",
        "base_url":    "https://api.anthropic.com",
        "requires_token": True,
        "token_env":   "ANTHROPIC_API_KEY",
        "capabilities": ["chat", "streaming", "tool_calling"],
        "default_model": "claude-haiku-3-5",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_model_manager():
    """Get the global agent's ModelManager, or None if server isn't initialised."""
    try:
        from smartagent.server.api import _get_agent  # type: ignore[attr-defined]
        agent = _get_agent()
        return getattr(agent, "model_manager", None)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/providers")
async def list_providers() -> dict:
    """List all available providers with their capabilities and availability."""
    from smartagent.llm.factory import get_active_provider

    current = get_active_provider()
    result = []
    for p in _PROVIDER_CATALOGUE:
        entry = dict(p)
        if p["id"] == "github":
            entry["token_present"] = bool(os.environ.get("GITHUB_TOKEN"))
            entry["available"] = entry["token_present"]
        else:  # ollama
            # Quick Ollama health check
            try:
                import httpx
                async with httpx.AsyncClient(timeout=2) as client:
                    resp = await client.get(f"{p['base_url']}/api/tags")
                    entry["available"] = resp.status_code == 200
            except Exception:
                entry["available"] = False
        entry["active"] = (p["id"] == current)
        result.append(entry)
    return {"providers": result}


@router.get("/providers/current")
async def get_current_provider() -> dict:
    """Return the currently active provider and model."""
    from smartagent.llm.factory import get_llm_settings
    settings = get_llm_settings()
    return {
        "provider":     settings["provider"],
        "model":        settings["model"],
        "coding_model": settings["coding_model"],
        "temperature":  settings["temperature"],
        "max_tokens":   settings["max_tokens"],
        "streaming":    settings["streaming"],
        "github_available": settings["github_available"],
    }


@router.post("/providers/switch")
async def switch_provider_endpoint(req: SwitchProviderRequest) -> dict:
    """
    Switch the active LLM provider.

    Immediately re-wires the global ModelManager so all subsequent
    worker calls use the new provider without a server restart.
    """
    from smartagent.llm.factory import switch_provider
    mm = _get_model_manager()
    try:
        settings = switch_provider(req.provider, req.model, model_manager=mm)
        return {"success": True, **settings}
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning("switch_provider: unexpected error: %s", exc)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/models/select")
async def select_model(req: SelectModelRequest) -> dict:
    """Select a specific model within the current provider."""
    from smartagent.llm.factory import get_active_provider, switch_provider
    provider = get_active_provider()
    mm = _get_model_manager()
    try:
        settings = switch_provider(provider, req.model, model_manager=mm)
        return {"success": True, **settings}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.get("/health/llm")
async def llm_health() -> dict:
    """
    Probe the active LLM provider and return health metrics.

    Returns provider, model, latency_ms, available, token_valid, streaming.
    """
    from smartagent.llm.factory import get_llm_settings
    settings = get_llm_settings()
    provider = settings["provider"]
    model_id = settings["model"]

    result: dict[str, Any] = {
        "provider":    provider,
        "model":       model_id,
        "latency_ms":  None,
        "available":   False,
        "token_valid": False,
        "streaming":   settings["streaming"],
        "error":       None,
    }

    t0 = time.monotonic()
    if provider == "github":
        token = os.environ.get("GITHUB_TOKEN", "")
        result["token_valid"] = bool(token)
        if not token:
            result["error"] = "GITHUB_TOKEN not set"
            return result
        try:
            from smartagent.llm.github_provider import GitHubProvider
            p = GitHubProvider(model_name=model_id, token=token)
            p.load()
            health = p.health()
            result["available"] = health.healthy
            result["latency_ms"] = round((time.monotonic() - t0) * 1000)
            if not health.healthy:
                result["error"] = health.message
        except Exception as exc:
            result["error"] = str(exc)
    else:
        ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{ollama_url}/api/tags")
                result["available"] = resp.status_code == 200
                result["token_valid"] = True  # no token needed
        except Exception as exc:
            result["error"] = str(exc)
        result["latency_ms"] = round((time.monotonic() - t0) * 1000)

    return result


@router.get("/llm/settings")
async def get_llm_settings_endpoint() -> dict:
    """Return all LLM settings."""
    from smartagent.llm.factory import get_llm_settings
    return get_llm_settings()


@router.post("/llm/settings")
async def update_llm_settings_endpoint(req: LlmSettingsUpdate) -> dict:
    """Update LLM settings and persist them."""
    from smartagent.llm.factory import update_llm_settings
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    return update_llm_settings(updates)


@router.get("/models/github")
async def list_github_models() -> dict:
    """List models available through GitHub Models."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return {"models": [], "error": "GITHUB_TOKEN not set"}
    try:
        from smartagent.llm.github_provider import GitHubProvider
        p = GitHubProvider(token=token)
        p.load()
        models = p.list_models()
        return {"models": models}
    except Exception as exc:
        return {"models": [], "error": str(exc)}
