"""
ProviderFactory — creates and wires the active LLM provider into ModelManager.

Provider selection order:
    1. ACTIVE_PROVIDER environment variable (``"github"`` or ``"ollama"``).
    2. Persisted state in ``.mark_provider_state.json`` (set by REST API).
    3. Default: ``"ollama"`` (backward-compatible for tests / offline use).

To switch providers at runtime call the REST API::

    POST /providers/switch  {"provider": "github", "model": "gpt-4.1-mini"}

Or set the env var before starting the server::

    ACTIVE_PROVIDER=github uvicorn smartagent.server.app:app

Architecture rule:
    Only ModelManager talks to providers.
    Only this factory and ModelManager.load_github_models() import GitHubProvider.
    Feature code (workers, RAG, etc.) calls ModelManager — never providers directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_DEFAULT_MODEL  = "gpt-4.1-mini"
GITHUB_FALLBACK_MODEL = "gpt-4o-mini"
GITHUB_CODING_MODEL   = "gpt-4.1"
GITHUB_EMBEDDING_MODEL = "text-embedding-3-small"

OLLAMA_DEFAULT_MODEL  = "llama3.1:8b"
OLLAMA_CODING_MODEL   = "qwen2.5-coder:7b"

_STATE_FILE = Path(".mark_provider_state.json")

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_state() -> dict[str, Any]:
    """Load persisted provider state (falls back to env-var / defaults)."""
    state: dict[str, Any] = {
        "provider": os.environ.get("ACTIVE_PROVIDER", "ollama"),
        "github_model": GITHUB_DEFAULT_MODEL,
        "github_coding_model": GITHUB_CODING_MODEL,
        "ollama_model": OLLAMA_DEFAULT_MODEL,
        "ollama_coding_model": OLLAMA_CODING_MODEL,
        "temperature": 0.7,
        "max_tokens": 4096,
        "streaming": True,
    }
    try:
        if _STATE_FILE.exists():
            saved = json.loads(_STATE_FILE.read_text())
            state.update(saved)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ProviderFactory: could not read state file: %s", exc)
    return state


def _save_state(state: dict[str, Any]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ProviderFactory: could not save state: %s", exc)


# ---------------------------------------------------------------------------
# Public helpers (used by OllamaWorkerMixin and api_providers.py)
# ---------------------------------------------------------------------------

def get_active_provider() -> str:
    """Return the name of the currently active provider (``"github"`` or ``"ollama"``)."""
    return _load_state()["provider"]


def get_model_for_role(role: str = "default") -> str | None:
    """
    Return the model ID that should be used for *role* (``"default"`` or ``"coding"``).

    Returns ``None`` when the active provider is Ollama — the OllamaWorkerMixin
    then falls back to ``settings.ollama_*_model`` for backward compatibility.
    Returns ``None`` if ACTIVE_PROVIDER is not set to ``"github"`` explicitly,
    preserving all pre-existing test behaviour.
    """
    state = _load_state()
    provider = state["provider"]
    if provider != "github":
        return None  # mixin uses Ollama settings as before
    if role == "coding":
        return state.get("github_coding_model", GITHUB_CODING_MODEL)
    return state.get("github_model", GITHUB_DEFAULT_MODEL)


def get_llm_settings() -> dict[str, Any]:
    """Return current LLM settings (provider, model, temperature, etc.)."""
    state = _load_state()
    return {
        "provider":       state["provider"],
        "model":          state.get("github_model" if state["provider"] == "github" else "ollama_model",
                                    GITHUB_DEFAULT_MODEL),
        "coding_model":   state.get("github_coding_model" if state["provider"] == "github"
                                    else "ollama_coding_model", GITHUB_CODING_MODEL),
        "temperature":    state.get("temperature", 0.7),
        "max_tokens":     state.get("max_tokens", 4096),
        "streaming":      state.get("streaming", True),
        "github_available": bool(os.environ.get("GITHUB_TOKEN")),
        "ollama_url":     os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    }


def update_llm_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Persist LLM setting changes and return the merged state."""
    state = _load_state()
    state.update(updates)
    _save_state(state)
    return get_llm_settings()


def switch_provider(
    provider: str,
    model: str | None = None,
    model_manager: Any = None,
) -> dict[str, Any]:
    """
    Switch the active provider and optionally select a specific model.

    If *model_manager* is provided, the new provider's models are registered
    and the active model is switched immediately.

    Returns the new settings dict.
    """
    if provider not in ("github", "ollama"):
        raise ValueError(f"Unknown provider {provider!r}. Must be 'github' or 'ollama'.")

    state = _load_state()
    state["provider"] = provider
    if model:
        key = "github_model" if provider == "github" else "ollama_model"
        state[key] = model
    _save_state(state)

    if model_manager is not None:
        _wire_provider(provider, model or _default_model(provider, state), model_manager)

    return get_llm_settings()


def wire_agent(model_manager: Any) -> None:
    """
    Register the active provider's models in *model_manager* and set the active model.

    Called by SmartAgent.__init__ and by the /providers/switch endpoint.
    No-ops gracefully if the provider is unavailable.
    """
    state = _load_state()
    provider = state["provider"]
    model = _default_model(provider, state)
    _wire_provider(provider, model, model_manager)


def _default_model(provider: str, state: dict[str, Any]) -> str:
    if provider == "github":
        return state.get("github_model", GITHUB_DEFAULT_MODEL)
    return state.get("ollama_model", OLLAMA_DEFAULT_MODEL)


def _wire_provider(provider: str, model: str, model_manager: Any) -> None:
    """Register provider models in model_manager and switch to *model*."""
    if provider == "github":
        _load_github(model, model_manager)
    else:
        _load_ollama(model, model_manager)


def _load_github(model: str, model_manager: Any) -> None:
    """Register GitHubProvider instances in model_manager."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.warning("ProviderFactory: GITHUB_TOKEN not set — GitHub provider unavailable")
        return
    try:
        from smartagent.llm.github_provider import GitHubProvider, GITHUB_CODING_MODEL as _CM
        state = _load_state()
        coding = state.get("github_coding_model", GITHUB_CODING_MODEL)
        for mid in dict.fromkeys([model, coding, GITHUB_DEFAULT_MODEL, GITHUB_FALLBACK_MODEL]):
            if model_manager.registry.find(mid) is None:
                p = GitHubProvider(model_name=mid, token=token)
                model_manager.registry.register(p)
                logger.info("ProviderFactory: registered GitHub model %s", mid)
        # Switch to the requested model
        model_manager.switch(model)
        logger.info("ProviderFactory: active GitHub model → %s", model)
    except Exception as exc:
        logger.warning("ProviderFactory: failed to load GitHub provider: %s", exc)


def _load_ollama(model: str, model_manager: Any) -> None:
    """Ensure Ollama models are registered and switch to *model*."""
    try:
        if model_manager.registry.find(model) is not None:
            model_manager.switch(model)
        else:
            logger.info("ProviderFactory: Ollama model %s not registered yet", model)
    except Exception as exc:
        logger.warning("ProviderFactory: failed to switch Ollama model: %s", exc)


class ProviderFactory:
    """
    High-level facade for provider management.

    Keeps a reference to the global ModelManager so REST endpoints can call
    switch_provider() and have the change immediately reflected in the running agent.
    """

    def __init__(self, model_manager: Any = None) -> None:
        self._mm = model_manager

    def get_provider(self) -> str:
        return get_active_provider()

    def get_settings(self) -> dict[str, Any]:
        return get_llm_settings()

    def switch(self, provider: str, model: str | None = None) -> dict[str, Any]:
        return switch_provider(provider, model, model_manager=self._mm)

    def wire(self) -> None:
        if self._mm is not None:
            wire_agent(self._mm)


_factory: ProviderFactory | None = None


def get_provider_factory(model_manager: Any = None) -> ProviderFactory:
    """
    Return the global ProviderFactory singleton.

    If *model_manager* is supplied the first time, it is stored for future
    provider-switching calls.
    """
    global _factory
    if _factory is None:
        _factory = ProviderFactory(model_manager)
    elif model_manager is not None and _factory._mm is None:
        _factory._mm = model_manager
    return _factory
