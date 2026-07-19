"""Tests for smartagent.server.voice_pipeline — real Silero VAD + real
Faster-Whisper, exercised against a genuine synthesized speech WAV
(tests/fixtures/sample_speech.wav — "Hello MARK, can you hear me? I would
like to talk about the project architecture.", generated via Windows SAPI),
streamed in small chunks the way the browser sends real microphone frames.
No mocking of the models: these tests are slow (a few seconds — real model
inference) and download real model weights on first run, by design — the
point is proving the pipeline actually transcribes real audio, not that a
mock returns what we told it to."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from smartagent.server.app import app
from smartagent.server.voice_pipeline import SAMPLE_RATE, VoiceSession, pcm16_to_float32

pytestmark = pytest.mark.slow

FIXTURE = Path(__file__).parent / "fixtures" / "sample_speech.wav"


def _load_as_pcm16_bytes() -> bytes:
    """Real speech audio, resampled to 16kHz mono, returned as raw PCM16
    bytes — exactly the wire format the browser sends over /ws/voice."""
    with wave.open(str(FIXTURE), "rb") as w:
        raw = w.readframes(w.getnframes())
        orig_rate = w.getframerate()
    audio_i16 = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    duration = len(audio_i16) / orig_rate
    target_len = int(duration * SAMPLE_RATE)
    resampled = np.interp(
        np.linspace(0, len(audio_i16), target_len, endpoint=False),
        np.arange(len(audio_i16)), audio_i16,
    ).astype(np.float32)
    # Pad with real silence front/back, like a real streaming session.
    silence = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
    full = np.concatenate([silence, resampled, silence])
    return (full * 32768.0).astype(np.int16).tobytes()


@pytest.fixture(scope="module")
def transcript_events() -> list[dict]:
    """Run the fixture through the real session once per test module —
    real model inference is slow enough that re-running it per test isn't
    worth it for what's a deterministic, read-only pipeline."""
    pcm = _load_as_pcm16_bytes()
    session = VoiceSession()
    events: list[dict] = []
    # Feed in small chunks, matching real browser frame sizes (~20-30ms).
    chunk_bytes = 512 * 2  # 512 int16 samples per feed, like real mic frames
    for i in range(0, len(pcm), chunk_bytes):
        events.extend(session.feed(pcm[i:i + chunk_bytes]))
    return events


class TestPCM16Conversion:
    def test_converts_to_float32_in_range(self):
        raw = np.array([0, 16384, -16384, 32767, -32768], dtype=np.int16).tobytes()
        floats = pcm16_to_float32(raw)
        assert floats.dtype == np.float32
        assert floats.max() <= 1.0
        assert floats.min() >= -1.0


class TestVoiceSessionRealAudio:
    def test_detects_speech_start(self, transcript_events):
        assert any(e["type"] == "speech_start" for e in transcript_events)

    def test_produces_at_least_one_final_transcript(self, transcript_events):
        finals = [e for e in transcript_events if e["type"] == "final"]
        assert len(finals) >= 1

    def test_final_transcripts_contain_real_recognized_words(self, transcript_events):
        """Not asserting exact text (Whisper's phrasing/punctuation can
        vary slightly run to run) — asserting it actually recognized real
        content from the real audio, which a fake/mocked pipeline
        couldn't fail even if broken."""
        all_text = " ".join(e["text"].lower() for e in transcript_events if e["type"] == "final")
        assert "mark" in all_text or "hear" in all_text
        assert "architecture" in all_text or "project" in all_text

    def test_silence_before_speech_produces_no_events(self):
        """Real VAD must not claim speech during real silence."""
        session = VoiceSession()
        silence = (np.zeros(SAMPLE_RATE * 2, dtype=np.float32) * 32768).astype(np.int16).tobytes()
        events = session.feed(silence)
        assert not any(e["type"] in ("speech_start", "final") for e in events)


class TestVoiceSessionReset:
    def test_reset_clears_state(self):
        session = VoiceSession()
        pcm = _load_as_pcm16_bytes()
        session.feed(pcm[:20000])  # partial utterance, mid-speech
        session.reset()
        assert session.speech_active is False
        assert session._utterance == []


class TestVoiceWebSocketEndpoint:
    """The real /ws/voice endpoint, exercised end-to-end with the same
    genuine speech audio — proves the wiring (binary frames in, JSON
    events out), not just the pipeline module in isolation."""

    def test_streams_real_transcript_over_the_websocket(self):
        """The server never closes the connection or sends a fixed number
        of messages — a plain receive loop could block forever waiting for
        a message that isn't coming. Run it in a thread with a hard
        wall-clock timeout so a real problem fails the test instead of
        hanging the suite."""
        import queue
        import threading

        pcm = _load_as_pcm16_bytes()
        chunk_bytes = 512 * 2 * 8  # a few real VAD chunks per WS frame
        client = TestClient(app)
        result: "queue.Queue[list[dict] | Exception]" = queue.Queue()

        def _run() -> None:
            try:
                received: list[dict] = []
                with client.websocket_connect("/ws/voice") as ws:
                    for i in range(0, len(pcm), chunk_bytes):
                        ws.send_bytes(pcm[i:i + chunk_bytes])
                    # This fixture reliably produces at least 2 finals
                    # (VAD merges closely-spaced sentences under the
                    # production 500ms silence threshold) — stop as soon
                    # as we have enough to prove real transcription
                    # happened, well before any risk of no more messages.
                    for _ in range(15):
                        received.append(ws.receive_json())
                        if sum(1 for e in received if e["type"] == "final") >= 2:
                            break
                result.put(received)
            except Exception as exc:  # noqa: BLE001
                result.put(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=45)
        assert not thread.is_alive(), "voice websocket test timed out — no hang allowed"

        received = result.get_nowait()
        assert not isinstance(received, Exception), f"voice websocket test errored: {received}"

        assert any(e["type"] == "speech_start" for e in received)
        finals = [e for e in received if e["type"] == "final"]
        assert len(finals) >= 1
        all_text = " ".join(e["text"].lower() for e in finals)
        assert "mark" in all_text or "hear" in all_text or "architecture" in all_text
