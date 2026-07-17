"""
TTSProvider — unified interface every text-to-speech provider must satisfy.

Mirrors ``smartagent/llm/base.py``'s ``LLMProvider`` Protocol: a structural
(not nominal) interface, so any class implementing these two methods is a
valid provider without explicit subclassing.

Architecture rule (same as the LLM factory): only ``smartagent/tts/factory.py``
imports concrete providers. Feature code (the ``/voice/speak-*`` endpoints,
``DevPipeline``) calls the factory, never a provider class directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSProvider(Protocol):
    """
    Structural protocol every TTS provider satisfies.

    Methods:
        synthesize(text, voice, speed) — returns audio bytes (WAV or MP3)
        list_voices()                  — catalogue of voice names this provider offers
    """

    @property
    def available(self) -> bool:
        """True if this provider's dependencies/credentials are present."""
        ...

    def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
        """Synthesize *text* to audio bytes. Raises on failure — callers
        (the factory) are responsible for catching and falling back."""
        ...

    def list_voices(self) -> list[str]:
        """Return the voice names this provider supports."""
        ...
