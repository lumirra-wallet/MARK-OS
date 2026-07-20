"""
speech_to_text.py — MARK's local speech transcription via Faster-Whisper.

This is the standalone STT module (used by higher-level code that needs
a simple transcribe() call). The real-time streaming pipeline that also
handles VAD is in smartagent/server/voice_pipeline.py — use that for the
live /ws/voice endpoint. This module is the simpler interface for one-shot
transcription of a complete audio buffer.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_model: Any = None


def _get_model() -> Any:
    global _model
    if _model is not None:
        return _model
    from faster_whisper import WhisperModel
    size = os.environ.get("MARK_WHISPER_MODEL", "base.en")
    logger.info("SpeechToText: loading Whisper model %r (first use)", size)
    _model = WhisperModel(size, device="cpu", compute_type="int8")
    logger.info("SpeechToText: Whisper model ready")
    return _model


class SpeechToText:
    """
    MARK's local speech-to-text using Faster-Whisper (base.en by default).
    Runs fully on CPU — no cloud API, no API key, no per-request cost.

    For real-time streaming with VAD, use voice_pipeline.VoiceSession instead.
    This class is for one-shot transcription of a complete audio buffer.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            self._model = _get_model()
        return self._model

    def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """
        Transcribe raw PCM16 bytes into text.

        audio_data: raw signed 16-bit little-endian PCM bytes at sample_rate.
        Returns the transcribed string, or "" if nothing was heard.
        """
        if not self.enabled:
            return ""
        if not audio_data:
            return ""

        model = self._ensure_model()

        # Convert PCM16 → float32 [-1, 1] that Faster-Whisper expects
        samples = (
            np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        )

        # Resample to 16kHz if needed
        if sample_rate != 16000:
            ratio = sample_rate / 16000
            n_out = int(len(samples) / ratio)
            indices = np.linspace(0, len(samples) - 1, n_out)
            samples = np.interp(indices, np.arange(len(samples)), samples).astype(
                np.float32
            )

        if samples.size == 0:
            return ""

        segments, _ = model.transcribe(
            samples, language="en", beam_size=5, vad_filter=True
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def is_available(self) -> bool:
        """Returns True if Faster-Whisper loaded successfully."""
        try:
            self._ensure_model()
            return True
        except Exception as exc:
            logger.warning("SpeechToText unavailable: %s", exc)
            return False
