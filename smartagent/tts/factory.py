"""
TTSFactory — selects and wires the active TTS provider.

Mirrors ``smartagent/llm/factory.py``'s pattern:

Provider selection order:
    1. Persisted state in ``.mark_tts_state.json`` (set by REST API / dashboard).
    2. Default: ``"kokoro"`` — browser TTS is a fallback, not the default,
       per the MARK v2 architecture spec.

Switch at runtime via the REST API::

    POST /tts/provider  {"provider": "piper"}

Architecture rule (same as the LLM factory):
    Only this factory imports concrete providers.
    Feature code (the ``/voice/*``/``/tts/*`` endpoints, ``DevPipeline``)
    calls ``synthesize()``/``get_active_provider()`` here — never a provider
    class directly.
"""

from __future__ import annotations

import json
from pathlib import Path

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_STATE_FILE = Path(".mark_tts_state.json")

_VALID_PROVIDERS = {"kokoro", "piper", "openai", "browser"}
DEFAULT_PROVIDER = "kokoro"


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        logger.warning("TTSFactory: failed to persist state: %s", exc)


def get_active_provider_name() -> str:
    state = _load_state()
    provider = state.get("provider", DEFAULT_PROVIDER)
    return provider if provider in _VALID_PROVIDERS else DEFAULT_PROVIDER


def switch_provider(provider: str) -> str:
    if provider not in _VALID_PROVIDERS:
        raise ValueError(f"Unknown TTS provider {provider!r} — valid: {sorted(_VALID_PROVIDERS)}")
    state = _load_state()
    state["provider"] = provider
    _save_state(state)
    return provider


def _make_provider(name: str):
    """Instantiate a fresh provider by name. Only this function (and the
    module-level cache below) may import concrete provider classes."""
    if name == "kokoro":
        from smartagent.tts.kokoro_provider import KokoroProvider
        return KokoroProvider()
    if name == "piper":
        from smartagent.tts.piper_provider import PiperProvider
        return PiperProvider()
    if name == "openai":
        from smartagent.tts.openai_provider import OpenAIProvider
        return OpenAIProvider()
    return None  # "browser" has no server-side provider — handled by the frontend


_provider_cache: dict[str, object] = {}


def _get_provider(name: str):
    if name not in _provider_cache:
        _provider_cache[name] = _make_provider(name)
    return _provider_cache[name]


def synthesize(text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
    """
    Synthesize *text* via the active provider.

    Raises if the active provider is unavailable or fails — callers (the
    ``/tts/speak`` endpoint) translate that into an HTTP error so the
    frontend can fall back to browser ``speechSynthesis``, per "Kokoro is
    the default provider, with browser TTS available only as a fallback."
    """
    name = get_active_provider_name()
    if name == "browser":
        raise RuntimeError("Active provider is 'browser' — synthesize client-side.")
    provider = _get_provider(name)
    if provider is None or not provider.available:
        raise RuntimeError(f"TTS provider {name!r} is not available on this server.")
    return provider.synthesize(text, voice=voice, speed=speed)


def list_voices(provider_name: str | None = None) -> list[str]:
    name = provider_name or get_active_provider_name()
    if name == "browser":
        return []
    provider = _get_provider(name)
    if provider is None or not provider.available:
        return []
    return provider.list_voices()


def provider_status() -> dict[str, bool]:
    """Availability of every provider — used by the Narration panel's
    Voice Provider dropdown to grey out options that won't work."""
    status = {"browser": True}
    for name in ("kokoro", "piper", "openai"):
        provider = _get_provider(name)
        status[name] = bool(provider and provider.available)
    return status
