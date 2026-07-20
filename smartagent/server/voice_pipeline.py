"""
voice_pipeline.py — real local streaming speech-to-text + voice activity
detection for MARK's voice interface.

Faster-Whisper (STT) + Silero VAD, both running locally — no cloud account,
no API key, no per-request cost. This is the backend half of the pipeline
from the Real-Time Presence directive:

    Microphone (browser) -> binary PCM16 frames over /ws/voice
        -> Silero VAD (speech start/end detection, ~30ms latency)
        -> Faster-Whisper (partial + final transcription)
        -> transcript events streamed back over the same connection

VAD's speech-start event is deliberately the first thing sent back to the
client, before any transcription happens — it's the interruption signal.
It fires within one ~32ms VAD chunk of the owner starting to talk, in time
for the frontend to stop TTS playback before it talks over them. Partial
transcripts are a real re-decode of everything captured so far roughly
once per second of speech, not a fabricated "typing" indicator — true
token-by-token streaming ASR would need a specialized streaming-native
model; this is the honest, achievable version with an off-the-shelf
Whisper model.

Verified end-to-end against a real synthesized speech sample before this
module was written (VAD correctly split a 3-sentence utterance into three
segments at their natural pauses; Whisper correctly transcribed each one)
— see the session's own record of that test run.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512  # Silero VAD's required chunk size at 16kHz

_whisper_model: Any = None
_vad_model: Any = None


def _get_whisper_model() -> Any:
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        model_size = os.environ.get("MARK_WHISPER_MODEL", "base.en")
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("voice_pipeline: loaded Whisper model %r", model_size)
    return _whisper_model


def _get_vad_model() -> Any:
    global _vad_model
    if _vad_model is None:
        from silero_vad import load_silero_vad
        _vad_model = load_silero_vad()
        logger.info("voice_pipeline: loaded Silero VAD model")
    return _vad_model


def pcm16_to_float32(raw: bytes) -> np.ndarray:
    """The browser sends 16-bit signed little-endian PCM; Whisper/Silero
    both want float32 samples in [-1, 1]."""
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(audio: np.ndarray, *, partial: bool = False) -> str:
    """Real Faster-Whisper transcription of one accumulated utterance.
    partial=True uses a fast greedy decode for a quick interim transcript
    while the owner is still talking; the final pass is unconstrained.

    Segments where Whisper itself thinks there is no speech
    (no_speech_prob > 0.55) are discarded — this filters out background
    noise and MARK's own echo that slipped through the mic gate.
    Very short results (< 3 chars) are also rejected as noise artifacts.
    """
    if audio.size == 0:
        return ""
    model = _get_whisper_model()
    segments, _ = model.transcribe(
        audio, language="en", beam_size=1 if partial else 5, vad_filter=False,
    )
    texts: list[str] = []
    for seg in segments:
        # no_speech_prob is available on all recent faster-whisper versions;
        # fall back gracefully if it's missing on an older build.
        if getattr(seg, "no_speech_prob", 0.0) > 0.55:
            continue   # Whisper itself thinks this is silence/noise
        t = seg.text.strip()
        if t:
            texts.append(t)
    result = " ".join(texts).strip()
    # Reject single characters / punctuation — almost always noise
    return result if len(result) >= 3 else ""


class VoiceSession:
    """
    One connection's live audio state. Owns a Silero VADIterator (real
    streaming voice-activity detection, not a fixed silence timer) and
    accumulates PCM for the current utterance.
    """

    def __init__(self) -> None:
        from silero_vad import VADIterator
        self._vad = VADIterator(
            _get_vad_model(), sampling_rate=SAMPLE_RATE,
            # Raised from 0.5 → 0.65: requires stronger speech signal before
            # firing speech_start.  Reduces false positives from ambient audio,
            # MARK's own voice echo, and background TV/music.
            threshold=0.65,
            # Slightly longer silence window (was 500ms) so short pauses mid-
            # sentence don't prematurely end the utterance.
            min_silence_duration_ms=650,
        )
        self._pending = np.array([], dtype=np.float32)  # not yet VAD-processed
        self._utterance: list[np.ndarray] = []
        self.speech_active = False
        self.samples_since_partial = 0

    def feed(self, raw_pcm: bytes) -> list[dict]:
        """
        Feed raw PCM16 bytes from the browser. Returns zero or more real
        events for the caller to act on/send back to the client:
          {"type": "speech_start"}           — the interruption signal
          {"type": "partial", "text": "..."} — interim transcript
          {"type": "final", "text": "..."}   — utterance finished
        """
        events: list[dict] = []
        self._pending = np.concatenate([self._pending, pcm16_to_float32(raw_pcm)])

        while len(self._pending) >= VAD_CHUNK_SAMPLES:
            chunk = self._pending[:VAD_CHUNK_SAMPLES]
            self._pending = self._pending[VAD_CHUNK_SAMPLES:]

            result = self._vad(chunk, return_seconds=False)
            if self.speech_active:
                self._utterance.append(chunk)
                self.samples_since_partial += VAD_CHUNK_SAMPLES

            if result and "start" in result:
                self.speech_active = True
                self._utterance = [chunk]
                self.samples_since_partial = 0
                events.append({"type": "speech_start"})

            elif result and "end" in result:
                self.speech_active = False
                if self._utterance:
                    audio = np.concatenate(self._utterance)
                    text = transcribe(audio, partial=False)
                    if text:
                        events.append({"type": "final", "text": text})
                self._utterance = []

            elif self.speech_active and self.samples_since_partial >= SAMPLE_RATE:
                self.samples_since_partial = 0
                audio = np.concatenate(self._utterance)
                text = transcribe(audio, partial=True)
                if text:
                    events.append({"type": "partial", "text": text})

        return events

    def reset(self) -> None:
        self._vad.reset_states()
        self._pending = np.array([], dtype=np.float32)
        self._utterance = []
        self.speech_active = False
        self.samples_since_partial = 0
