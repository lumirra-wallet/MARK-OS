"""
KokoroProvider — the default TTS provider (see ARCHITECTURE.md / MARK v2 spec).

Uses ``kokoro-onnx`` (CPU, ONNX runtime) rather than the reference PyTorch
implementation — matches this project's local-first, CPU-friendly design
(Ollama, faster-whisper int8, Piper all follow the same shape). Model weights
(``.mark_tts_models/kokoro-v1.0.int8.onnx`` + ``voices-v1.0.bin``, ~115MB
total, the quantized int8 variant) are downloaded once and gitignored —
see ``.gitignore`` — not shipped in the repo.

Best-effort subsystem: if the ``kokoro_onnx`` package or the model files
aren't present, ``available`` is False and the factory falls back to the
next provider (or ultimately the browser). The ONNX session is loaded lazily
on first ``synthesize()`` call, not at import time — it takes a moment to
load ~90MB and most processes never actually speak.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

MODEL_DIR    = Path(".mark_tts_models")
MODEL_PATH   = MODEL_DIR / "kokoro-v1.0.int8.onnx"
VOICES_PATH  = MODEL_DIR / "voices-v1.0.bin"
DEFAULT_VOICE = "af_sarah"
SAMPLE_RATE   = 24000


class KokoroProvider:
    """Lazy-loaded wrapper around ``kokoro_onnx.Kokoro``."""

    def __init__(self) -> None:
        self._kokoro: Any = None

    @property
    def available(self) -> bool:
        if not (MODEL_PATH.exists() and VOICES_PATH.exists()):
            return False
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self) -> Any:
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            logger.info("Loading Kokoro ONNX model from %s", MODEL_PATH)
            self._kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        return self._kokoro

    def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
        if not self.available:
            raise RuntimeError(
                f"Kokoro model files not found in {MODEL_DIR} — "
                "download kokoro-v1.0.int8.onnx and voices-v1.0.bin from "
                "https://github.com/thewh1teagle/kokoro-onnx/releases"
            )
        kokoro = self._load()
        samples, sample_rate = kokoro.create(
            text, voice=voice or DEFAULT_VOICE, speed=max(0.5, min(2.0, speed)), lang="en-us",
        )
        return _to_wav_bytes(samples, sample_rate)

    def list_voices(self) -> list[str]:
        if not self.available:
            return []
        kokoro = self._load()
        return sorted(kokoro.get_voices())


def _to_wav_bytes(samples: Any, sample_rate: int) -> bytes:
    """Convert float32 PCM samples (as returned by kokoro_onnx) to WAV bytes."""
    import numpy as np
    pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()
