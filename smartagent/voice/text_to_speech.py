"""
text_to_speech.py — MARK's local voice synthesis via Kokoro-ONNX.

Thin wrapper around smartagent/server/tts_engine.py that exposes the
same speak() interface the rest of the codebase expects, while routing
actual synthesis through the shared tts_engine singleton (so model weights
are only loaded once per process, regardless of which module calls first).

The real streaming voice pipeline is in speech_runtime.py (sentence
buffering → tts_engine.synthesize → broadcast_bytes over /ws). Use this
class for one-shot synthesis outside the streaming path, e.g. system
announcements or test code.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TextToSpeech:
    """
    MARK's local text-to-speech using Kokoro-82M (ONNX runtime).
    Runs fully locally — no browser speechSynthesis, no cloud TTS.

    Voice: af_bella (MARK's permanent, consistent voice — never varies).
    Output: raw PCM16 mono bytes at 24kHz (returned from speak_to_bytes)
            or synthesized and ready for broadcast_bytes.

    For the live streaming path (LLM reply → sentence chunks → audio frames
    → WebSocket), see speech_runtime.SpeechRuntime — that's what the
    dashboard actually hears. This class is for standalone synthesis calls.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def speak(self, text: str) -> None:
        """
        Synthesize *text* and log it. In the server context, audio goes
        through speech_runtime's broadcast path, not playback here.
        Use speak_to_bytes() when you need the raw PCM.
        """
        pcm = self.speak_to_bytes(text)
        if pcm:
            logger.debug("TextToSpeech.speak: synthesized %d bytes for %r", len(pcm), text[:60])

    def speak_to_bytes(self, text: str) -> bytes:
        """
        Synthesize *text* and return raw PCM16 mono bytes at 24kHz.
        Returns b"" if synthesis fails or is disabled.
        """
        if not self.enabled or not text.strip():
            return b""
        try:
            from smartagent.server import tts_engine
            return tts_engine.synthesize(text)
        except Exception as exc:
            logger.warning("TextToSpeech synthesis failed: %s", exc)
            return b""

    def is_available(self) -> bool:
        """Returns True if the Kokoro TTS engine loaded successfully."""
        try:
            from smartagent.server import tts_engine
            return tts_engine.is_available()
        except Exception as exc:
            logger.warning("TextToSpeech unavailable: %s", exc)
            return False
