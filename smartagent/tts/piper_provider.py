"""
PiperProvider — wraps the same Piper synthesis path as
``smartagent/server/voice_manager.py``, but returns WAV bytes for the browser
to play instead of writing to the server's local speakers via ``sounddevice``.

Kept as a separate, factory-selectable provider (not removed) since the
architecture must support multiple TTS providers side by side — Kokoro is
just the new default.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

DEFAULT_VOICE = "en_US-lessac-medium"
SAMPLE_RATE   = 22050


class PiperProvider:
    def __init__(self) -> None:
        self._binary = shutil.which("piper") or shutil.which("piper-tts")

    @property
    def available(self) -> bool:
        if self._binary is not None:
            return True
        try:
            import piper.voice  # noqa: F401
        except ImportError:
            return False
        return True

    def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
        voice = voice or DEFAULT_VOICE
        if self._binary is not None:
            return self._synthesize_via_binary(text, voice, speed)
        return self._synthesize_via_package(text, voice)

    def _synthesize_via_binary(self, text: str, voice: str, speed: float) -> bytes:
        proc = subprocess.run(
            [
                self._binary, "--model", voice,
                "--length_scale", str(1.0 / max(speed, 0.1)),
                "--output_raw",
            ],
            input=text.encode(), capture_output=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"piper returned {proc.returncode}: {proc.stderr[:200]!r}")
        return _raw_pcm_to_wav(proc.stdout, SAMPLE_RATE)

    def _synthesize_via_package(self, text: str, voice: str) -> Any:
        from piper.voice import PiperVoice
        pv = PiperVoice.load(voice)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            pv.synthesize(text, wf)
        return buf.getvalue()

    def list_voices(self) -> list[str]:
        # Piper voices are model files the user installs locally — no fixed
        # catalogue to enumerate without scanning a models directory.
        return [DEFAULT_VOICE]


def _raw_pcm_to_wav(raw_pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_pcm)
    return buf.getvalue()
