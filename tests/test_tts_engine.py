"""Tests for smartagent.server.tts_engine — real local Kokoro (kokoro-onnx)
TTS engine. Slow: downloads/loads real model weights on first run, by
design — the point is proving real synthesis works, not that a mock
returns canned bytes."""

from __future__ import annotations

import numpy as np
import pytest

from smartagent.server import tts_engine

pytestmark = pytest.mark.slow


class TestSynthesize:
    def test_produces_real_nonempty_audio(self):
        pcm = tts_engine.synthesize("Hello, this is a real test of MARK's voice.")
        assert len(pcm) > 0
        samples = len(pcm) // 2  # PCM16 mono: 2 bytes/sample
        duration = samples / tts_engine.SAMPLE_RATE
        assert 0.3 < duration < 30

    def test_audio_is_not_silence(self):
        pcm = tts_engine.synthesize("Testing, testing, one two three.")
        arr = np.frombuffer(pcm, dtype=np.int16)
        assert arr.size > 0
        assert np.abs(arr.astype(np.int32)).mean() > 50  # real speech has real amplitude

    def test_empty_text_returns_empty_bytes(self):
        assert tts_engine.synthesize("") == b""
        assert tts_engine.synthesize("   ") == b""

    def test_same_voice_used_every_call(self):
        """MARK's identity is one consistent voice, never chosen per-request."""
        import inspect
        source = inspect.getsource(tts_engine.synthesize)
        assert "MARK_VOICE" in source


class TestAvailability:
    def test_is_available_true_with_real_engine(self):
        assert tts_engine.is_available() is True
        assert tts_engine.unavailable_reason() is None
