"""
ProviderFactory — creates and wires the active LLM provider into ModelManager.

Provider selection order:
    1. ACTIVE_PROVIDER environment variable (``"ollama"``, ``"nvidia"``,
       ``"github"``, ``"openai"``, or ``"anthropic"``).
    2. Persisted state in ``.mark_provider_state.json`` (set by REST API).
    3. Auto-detect: ``"nvidia"`` when NVIDIA_API_KEY is present, else
       ``"github"`` when GITHUB_TOKEN is present, else ``"openai"``, else
       ``"anthropic"``, else ``"nvidia"`` (the unconditional default).

Ollama — MARK's local intelligence core (see docs/canonical/MASTER_BLUEPRINT.md):
    When the active provider is ``"ollama"``, NVIDIA is also registered as a
    silent fallback (never switched to unless Ollama fails) whenever
    NVIDIA_API_KEY is present — see ``_load_ollama()``. Model defaults to
    ``MARK_MODEL`` (falling back to ``OLLAMA_DEFAULT_MODEL``, then the
    hard-coded "llama3.2:3b") env var, matching the canonical spec's naming.

To switch providers at runtime call the REST API::

    POST /providers/switch  {"provider": "ollama", "model": "llama3.2:3b"}

Or set the env var before starting the server::

    ACTIVE_PROVIDER=ollama uvicorn smartagent.server.app:app

Architecture rule:
    Only ModelManager talks to providers.
    Only this factory imports GitHubProvider/NvidiaProvider/OllamaProvider directly.
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

GITHUB_DEFAULT_MODEL  = "gpt-4.1"
GITHUB_FALLBACK_MODEL = "gpt-4o-mini"
GITHUB_CODING_MODEL   = "gpt-4.1"
GITHUB_EMBEDDING_MODEL = "text-embedding-3-small"

NVIDIA_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

# MARK_MODEL is the canonical spec's name (docs/canonical/MASTER_BLUEPRINT.md
# section 4) for MARK's local-core model. OLLAMA_DEFAULT_MODEL is kept as a
# secondary alias since smartagent/server/config.py already reads it.
OLLAMA_DEFAULT_MODEL = (
    os.environ.get("MARK_MODEL")
    or os.environ.get("OLLAMA_DEFAULT_MODEL")
    or "llama3.2:3b"
)

_STATE_FILE = Path(".mark_provider_state.json")

# GitHubProvider/NvidiaProvider deliberately swallow API exceptions and
# return/yield an error-prefixed string as if it were real model content
# (see each provider's own tests — this is intentional so a raw exception
# never crashes a caller mid-stream). That means callers must check for one
# of these sentinels themselves before treating the text as genuine model
# output — otherwise a rate-limit or outage message streams straight to the
# user as if MARK had said it. Use ``is_llm_error_text()`` wherever
# chat_stream()/chat() output is about to be published or parsed as real
# content.
LLM_ERROR_PREFIXES = (
    "GitHub Models error: ",
    "NVIDIA API error: ",
    "Ollama server unavailable.",
)


def is_llm_error_text(text: str) -> bool:
    """True when *text* is a provider's swallowed-error sentinel, not real model output."""
    stripped = text.strip()
    return any(stripped.startswith(p) for p in LLM_ERROR_PREFIXES)

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

_VALID_PROVIDERS = {"ollama", "github", "nvidia", "openai", "anthropic"}


def _auto_default_provider() -> str:
    """Detect the best default provider without requiring explicit configuration.

    Selection order:
      1. ACTIVE_PROVIDER env var (explicit override)
      2. OLLAMA_HOST present → "ollama"  (local-first: fastest, free, no auth)
      3. NVIDIA_API_KEY present → "nvidia"
      4. GITHUB_TOKEN present  → "github"
      5. OPENAI_API_KEY present → "openai"
      6. ANTHROPIC_API_KEY present → "anthropic"
      7. Fallback               → "ollama" (works without any cloud keys)

    Ollama is prioritised over cloud providers when OLLAMA_HOST is configured
    because it has no auth to expire, no rate limits, and no per-token cost.
    Cloud providers are still used when Ollama is absent.
    """
    explicit = os.environ.get("ACTIVE_PROVIDER", "").strip().lower()
    if explicit in _VALID_PROVIDERS:
        return explicit
    # Prefer local Ollama when configured — no auth failures, no billing
    if os.environ.get("OLLAMA_HOST"):
        return "ollama"
    if os.environ.get("NVIDIA_API_KEY"):
        return "nvidia"
    if os.environ.get("GITHUB_TOKEN"):
        return "github"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "ollama"


# Derive the allowed sets directly from each catalogue so adding a model
# there automatically allows it here — no duplicate maintenance required.
from smartagent.llm.github_provider import _GITHUB_MODEL_CATALOGUE as _CAT  # noqa: E402
from smartagent.llm.nvidia_provider import _NVIDIA_MODEL_CATALOGUE as _NCAT  # noqa: E402
_KNOWN_GITHUB_MODELS: set[str] = {m["id"] for m in _CAT}
_KNOWN_NVIDIA_MODELS: set[str] = {m["id"] for m in _NCAT}


def _load_state() -> dict[str, Any]:
    """Load persisted provider state (falls back to env-var / defaults)."""
    state: dict[str, Any] = {
        "provider": _auto_default_provider(),
        "github_model": GITHUB_DEFAULT_MODEL,
        "github_coding_model": GITHUB_CODING_MODEL,
        "nvidia_model": NVIDIA_DEFAULT_MODEL,
        "ollama_model": OLLAMA_DEFAULT_MODEL,
        "temperature": 0.7,
        "max_tokens": 4096,
        "streaming": True,
    }
    try:
        if _STATE_FILE.exists():
            saved = json.loads(_STATE_FILE.read_text())
            # Guard: reject unknown model names so a stale or hand-edited
            # state file can't silently route every call to a 404 endpoint.
            # Persist the correction immediately — otherwise a bad on-disk
            # value gets silently "fixed" in memory on every load without
            # ever actually being healed, and keeps re-triggering this branch.
            gm = saved.get("github_model", "")
            if gm and gm not in _KNOWN_GITHUB_MODELS:
                logger.warning(
                    "ProviderFactory: ignoring unknown github_model %r in state file "
                    "— resetting to default %r", gm, GITHUB_DEFAULT_MODEL,
                )
                saved["github_model"] = GITHUB_DEFAULT_MODEL
                _save_state({**state, **saved})
            nm = saved.get("nvidia_model", "")
            if nm and nm not in _KNOWN_NVIDIA_MODELS:
                logger.warning(
                    "ProviderFactory: ignoring unknown nvidia_model %r in state file "
                    "— resetting to default %r", nm, NVIDIA_DEFAULT_MODEL,
                )
                saved["nvidia_model"] = NVIDIA_DEFAULT_MODEL
                _save_state({**state, **saved})
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
# Public helpers (used by api_providers.py and the legacy executive/ workers)
# ---------------------------------------------------------------------------

def get_active_provider() -> str:
    """Return the name of the currently active provider (``"nvidia"``, ``"github"``, etc.)."""
    return _load_state()["provider"]


def get_model_for_role(role: str = "default") -> str | None:
    """
    Return the model ID that should be used for *role* (``"default"`` or ``"coding"``).

    Returns ``None`` for providers this function doesn't have a specific
    branch for (legacy callers, e.g. ``smartagent.executive.workers.ollama_mixin``,
    then fall back to their own local settings) — preserved for backward
    compatibility with that disconnected subsystem, which this function
    predates.
    """
    state = _load_state()
    provider = state["provider"]
    if provider == "nvidia":
        # Nvidia doesn't have a separate coding model yet — same model for both roles.
        return state.get("nvidia_model", NVIDIA_DEFAULT_MODEL)
    if provider != "github":
        return None
    if role == "coding":
        return state.get("github_coding_model", GITHUB_CODING_MODEL)
    return state.get("github_model", GITHUB_DEFAULT_MODEL)


def get_llm_settings() -> dict[str, Any]:
    """Return current LLM settings (provider, model, temperature, etc.)."""
    state    = _load_state()
    provider = state["provider"]

    if provider == "github":
        model        = state.get("github_model",        GITHUB_DEFAULT_MODEL)
        coding_model = state.get("github_coding_model", GITHUB_CODING_MODEL)
    elif provider == "nvidia":
        model        = state.get("nvidia_model", NVIDIA_DEFAULT_MODEL)
        coding_model = model
    elif provider == "ollama":
        model        = state.get("ollama_model", OLLAMA_DEFAULT_MODEL)
        coding_model = model
    elif provider == "openai":
        model        = state.get("openai_model",        os.environ.get("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"))
        coding_model = state.get("openai_coding_model", "gpt-4o")
    elif provider == "anthropic":
        model        = state.get("anthropic_model",        os.environ.get("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-3-5"))
        coding_model = state.get("anthropic_coding_model", "claude-sonnet-4-5")
    else:
        # Unrecognized/legacy provider value on disk — fall back to the
        # product default rather than crashing.
        model        = state.get("nvidia_model", NVIDIA_DEFAULT_MODEL)
        coding_model = model

    return {
        "provider":           provider,
        "model":              model,
        "coding_model":       coding_model,
        "temperature":        state.get("temperature", 0.7),
        "max_tokens":         state.get("max_tokens", 4096),
        "streaming":          state.get("streaming", True),
        "github_available":   bool(os.environ.get("GITHUB_TOKEN")),
        "nvidia_available":   bool(os.environ.get("NVIDIA_API_KEY")),
        "ollama_available":   True,  # local — no key required; see /diagnostics for live reachability
        "openai_available":   bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic_available": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


def update_llm_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Persist LLM setting changes and return the merged state."""
    state = _load_state()
    # Sanitize before saving — reject unknown model names so a bad dashboard
    # payload can't permanently break the provider.
    gm = updates.get("github_model", "")
    if gm and gm not in _KNOWN_GITHUB_MODELS:
        logger.warning(
            "update_llm_settings: ignoring unknown github_model %r — keeping %r",
            gm, state.get("github_model", GITHUB_DEFAULT_MODEL),
        )
        updates = {k: v for k, v in updates.items() if k != "github_model"}
    nm = updates.get("nvidia_model", "")
    if nm and nm not in _KNOWN_NVIDIA_MODELS:
        logger.warning(
            "update_llm_settings: ignoring unknown nvidia_model %r — keeping %r",
            nm, state.get("nvidia_model", NVIDIA_DEFAULT_MODEL),
        )
        updates = {k: v for k, v in updates.items() if k != "nvidia_model"}
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
    if provider not in _VALID_PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}.")

    state = _load_state()
    state["provider"] = provider
    if model:
        key = {"github": "github_model", "nvidia": "nvidia_model",
               "ollama": "ollama_model",
               "openai": "openai_model",
               "anthropic": "anthropic_model"}[provider]
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
    if provider == "nvidia":
        return state.get("nvidia_model", NVIDIA_DEFAULT_MODEL)
    if provider == "ollama":
        return state.get("ollama_model", OLLAMA_DEFAULT_MODEL)
    if provider == "openai":
        return state.get("openai_model", os.environ.get("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"))
    return state.get("anthropic_model", os.environ.get("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-3-5"))


def _wire_provider(provider: str, model: str, model_manager: Any) -> None:
    """Register provider models in model_manager and switch to *model*."""
    # Clear any fallback left over from a previous provider (e.g. switching
    # away from "ollama") — _load_ollama() re-establishes it if applicable.
    if hasattr(model_manager, "set_fallback"):
        model_manager.set_fallback(None)
    if provider == "github":
        _load_github(model, model_manager)
    elif provider == "nvidia":
        _load_nvidia(model, model_manager)
    elif provider == "ollama":
        _load_ollama(model, model_manager)
    else:
        # OpenAI / Anthropic don't register models with ModelManager yet —
        # they operate through the REST API layer directly. No-op here.
        logger.info("ProviderFactory: %s provider selected (REST API layer only)", provider)


def _load_github(model: str, model_manager: Any) -> None:
    """Register GitHubProvider instances in model_manager.

    Also registers an Ollama fallback (when OLLAMA_HOST is configured) so
    that a GitHub auth failure (Unauthorized / expired token) silently
    retries on the local model instead of leaving MARK unable to respond.
    This mirrors how _load_ollama() uses NVIDIA as its silent fallback.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.warning("ProviderFactory: GITHUB_TOKEN not set — GitHub provider unavailable")
        # Still try to wire Ollama so the system works without GitHub
        _load_ollama(OLLAMA_DEFAULT_MODEL, model_manager)
        return
    try:
        from smartagent.llm.github_provider import GitHubProvider
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

    # ── Ollama fallback for GitHub auth failures ──────────────────────────
    # Register a local Ollama model as a silent fallback.  When ModelManager
    # detects is_llm_error_text() in a GitHub response (e.g. Unauthorized),
    # it automatically retries on Ollama without any user intervention.
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    if not ollama_host:
        logger.info("ProviderFactory: OLLAMA_HOST not set — no Ollama fallback for GitHub")
        return
    try:
        from smartagent.models.providers.ollama_provider import OllamaProvider
        ollama_model = OLLAMA_DEFAULT_MODEL
        if model_manager.registry.find(ollama_model) is None:
            p = OllamaProvider(model_name=ollama_model, base_url=ollama_host)
            model_manager.registry.register(p)
            logger.info("ProviderFactory: registered Ollama model %s as GitHub fallback", ollama_model)
        if hasattr(model_manager, "set_fallback"):
            model_manager.set_fallback(ollama_model, is_failure=is_llm_error_text)
            logger.info("ProviderFactory: Ollama fallback active for GitHub (model=%s)", ollama_model)
    except Exception as exc:
        logger.warning("ProviderFactory: failed to register Ollama fallback for GitHub: %s", exc)


def _load_nvidia(model: str, model_manager: Any) -> None:
    """Register NvidiaProvider instances in model_manager."""
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        logger.warning("ProviderFactory: NVIDIA_API_KEY not set — NVIDIA provider unavailable")
        return
    try:
        from smartagent.llm.nvidia_provider import NvidiaProvider
        for mid in dict.fromkeys([model, NVIDIA_DEFAULT_MODEL]):
            if model_manager.registry.find(mid) is None:
                p = NvidiaProvider(model_name=mid, api_key=api_key)
                model_manager.registry.register(p)
                logger.info("ProviderFactory: registered NVIDIA model %s", mid)
        # Switch to the requested model
        model_manager.switch(model)
        logger.info("ProviderFactory: active NVIDIA model → %s", model)
    except Exception as exc:
        logger.warning("ProviderFactory: failed to load NVIDIA provider: %s", exc)


def _load_ollama(model: str, model_manager: Any) -> None:
    """
    Register OllamaProvider in model_manager and switch to *model*.

    Ollama needs no API key — connectivity is verified by health(), not
    registration. When NVIDIA_API_KEY is present, NVIDIA is also silently
    registered and set as ModelManager's fallback (see
    ModelManager.set_fallback()) — it's never switched to as the active
    model, only used automatically when Ollama's own calls fail.
    """
    try:
        from smartagent.models.providers.ollama_provider import OllamaProvider
        base_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        if model_manager.registry.find(model) is None:
            p = OllamaProvider(model_name=model, base_url=base_url)
            model_manager.registry.register(p)
            logger.info("ProviderFactory: registered Ollama model %s", model)
        model_manager.switch(model)
        logger.info("ProviderFactory: active Ollama model → %s", model)
    except Exception as exc:
        logger.warning("ProviderFactory: failed to load Ollama provider: %s", exc)
        return

    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        logger.info("ProviderFactory: NVIDIA_API_KEY not set — no fallback registered for Ollama")
        return
    try:
        from smartagent.llm.nvidia_provider import NvidiaProvider
        nvidia_model = NVIDIA_DEFAULT_MODEL
        if model_manager.registry.find(nvidia_model) is None:
            p = NvidiaProvider(model_name=nvidia_model, api_key=api_key)
            model_manager.registry.register(p)
            logger.info("ProviderFactory: registered NVIDIA model %s as Ollama fallback", nvidia_model)
        if hasattr(model_manager, "set_fallback"):
            model_manager.set_fallback(nvidia_model, is_failure=is_llm_error_text)
            logger.info("ProviderFactory: NVIDIA fallback active for Ollama (model=%s)", nvidia_model)
    except Exception as exc:
        logger.warning("ProviderFactory: failed to register NVIDIA fallback for Ollama: %s", exc)


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
