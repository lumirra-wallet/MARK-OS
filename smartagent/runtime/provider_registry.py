"""
provider_registry.py — Elena's provider registry.

The Runtime owns the ProviderRegistry.  Providers are *services* — they
supply reasoning, speech-to-text, text-to-speech, embedding, or any other
capability the Runtime needs.  Swapping a provider never touches Elena's
identity, memory, session, or configuration.

Provider kinds
──────────────
  REASONING   — LLM inference (Ollama, GitHub, NVIDIA, OpenAI, Anthropic)
  STT         — speech-to-text (Whisper, Google Speech, Deepgram)
  TTS         — text-to-speech (Kokoro, Google TTS, ElevenLabs)
  VOICE       — full-duplex realtime voice (Gemini Live, LiveKit + ElevenLabs)
  EMBEDDING   — vector embedding for memory retrieval
  STORAGE     — persistent storage backend (MongoDB, Postgres, SQLite)

Usage
─────
    registry = ProviderRegistry()

    # Register
    registry.register(ProviderKind.REASONING, "ollama", ollama_provider_instance)
    registry.register(ProviderKind.VOICE,     "gemini", gemini_bridge_instance)

    # Activate
    registry.set_active(ProviderKind.REASONING, "ollama")

    # Get active
    provider = registry.get_active(ProviderKind.REASONING)

    # List
    registry.list_providers(ProviderKind.VOICE)  # [("gemini", obj), ("local", obj)]
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ProviderKind(Enum):
    """Category of capability a provider supplies."""
    REASONING  = auto()   # LLM inference
    STT        = auto()   # speech-to-text
    TTS        = auto()   # text-to-speech
    VOICE      = auto()   # full-duplex realtime voice
    EMBEDDING  = auto()   # vector embedding
    STORAGE    = auto()   # persistent storage


class ProviderRegistry:
    """
    Registry of named providers for each ProviderKind.

    Thread safety: single-threaded asyncio use; wrap with a lock if accessed
    from multiple threads.
    """

    def __init__(self) -> None:
        # kind → {name: provider_instance}
        self._providers: Dict[ProviderKind, Dict[str, Any]] = {
            k: {} for k in ProviderKind
        }
        # kind → active provider name
        self._active: Dict[ProviderKind, Optional[str]] = {
            k: None for k in ProviderKind
        }

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        kind: ProviderKind,
        name: str,
        provider: Any,
        *,
        set_active: bool = False,
    ) -> None:
        """
        Register ``provider`` under ``name`` for ``kind``.

        If ``set_active=True``, also make it the active provider for this kind.
        If no active provider is set yet, automatically activates the first one.
        """
        if not name:
            raise ValueError("provider name must be a non-empty string")
        self._providers[kind][name] = provider
        if set_active or self._active[kind] is None:
            self._active[kind] = name
        logger.debug(
            "provider_registry: registered %s/%s (active=%s)",
            kind.name, name, self._active[kind],
        )

    def unregister(self, kind: ProviderKind, name: str) -> None:
        """
        Remove a provider.  If it was active, the active slot is cleared
        (the caller should activate another provider).
        """
        self._providers[kind].pop(name, None)
        if self._active[kind] == name:
            self._active[kind] = None
            # Auto-activate another if one exists
            remaining = list(self._providers[kind].keys())
            if remaining:
                self._active[kind] = remaining[0]
                logger.info(
                    "provider_registry: %s/%s removed; activated %s instead",
                    kind.name, name, remaining[0],
                )
            else:
                logger.warning(
                    "provider_registry: %s/%s removed; no providers left for %s",
                    kind.name, name, kind.name,
                )

    # ── Activation ────────────────────────────────────────────────────────────

    def set_active(self, kind: ProviderKind, name: str) -> None:
        """
        Make ``name`` the active provider for ``kind``.

        Raises ``KeyError`` if ``name`` is not registered.
        """
        if name not in self._providers[kind]:
            raise KeyError(
                f"provider '{name}' is not registered for {kind.name}. "
                f"Available: {list(self._providers[kind].keys())}"
            )
        old = self._active[kind]
        self._active[kind] = name
        if old != name:
            logger.info(
                "provider_registry: %s active changed: %s → %s",
                kind.name, old, name,
            )

    # ── Access ────────────────────────────────────────────────────────────────

    def get_active(self, kind: ProviderKind) -> Optional[Any]:
        """
        Return the active provider instance for ``kind``, or None if no
        provider is registered or none is active.
        """
        name = self._active[kind]
        if name is None:
            return None
        return self._providers[kind].get(name)

    def get_active_name(self, kind: ProviderKind) -> Optional[str]:
        """Return the name of the active provider, or None."""
        return self._active[kind]

    def get(self, kind: ProviderKind, name: str) -> Optional[Any]:
        """Return a specific named provider, or None if not found."""
        return self._providers[kind].get(name)

    def has(self, kind: ProviderKind, name: str) -> bool:
        """Return True if ``name`` is registered for ``kind``."""
        return name in self._providers[kind]

    def list_providers(self, kind: ProviderKind) -> List[Tuple[str, Any]]:
        """Return all registered (name, instance) pairs for ``kind``."""
        return list(self._providers[kind].items())

    def active_names(self) -> Dict[str, Optional[str]]:
        """Return a dict mapping each ProviderKind name to its active provider name."""
        return {k.name: v for k, v in self._active.items()}

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self, kind: ProviderKind, name: str) -> bool:
        """
        Return True if the named provider is registered AND supports an
        ``is_available()`` check that passes (or has no such method).
        """
        provider = self.get(kind, name)
        if provider is None:
            return False
        check = getattr(provider, "is_available", None)
        if callable(check):
            try:
                return bool(check())
            except Exception:
                return False
        return True

    # ── Representation ────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        lines = ["ProviderRegistry:"]
        for kind in ProviderKind:
            names = list(self._providers[kind].keys())
            active = self._active[kind]
            lines.append(f"  {kind.name:12s}: {names}  (active={active!r})")
        return "\n".join(lines)
