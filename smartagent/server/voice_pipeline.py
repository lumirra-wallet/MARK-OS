"""
voice_pipeline.py — real local streaming speech-to-text + voice activity
detection for MARK's voice interface.

Faster-Whisper (STT) + Silero VAD, both running locally — no cloud account,
no API key, no per-request cost.

Audio pipeline:
    Microphone (browser) → binary PCM16 frames over /ws/voice
        → Silero VAD (speech start/end detection, ~30ms latency)
        → Faster-Whisper (partial + final transcription)
        → transcript events streamed back over the same connection

Turn-taking state machine (mirrors how modern voice agents work)
---------------------------------------------------------------
LISTENING   default — VAD processes audio, transcripts emitted normally.
TTS_ACTIVE  MARK is speaking — VAD is fully muted (no transcripts at all);
            only a genuine high-energy barge-in clears back to LISTENING.
POST_SPEECH 800ms cool-down after TTS ends — VAD processes audio but
            suppresses transcripts; absorbs room reverb + AEC settling.

Transitions:
  LISTENING   → TTS_ACTIVE  : mute() called by speech_runtime before first audio byte
  TTS_ACTIVE  → POST_SPEECH : unmute() called by speech_runtime after last audio byte
  POST_SPEECH → LISTENING   : _post_tts_remaining hits zero
  TTS_ACTIVE  → LISTENING   : high-energy barge-in detected (interrupt)

speech_start is the interrupt signal:
  In TTS_ACTIVE  : only emitted when RMS ≥ _BARGE_IN_THRESHOLD (real voice)
  In POST_SPEECH : emitted normally (holdoff suppresses transcripts, not interrupts)
  In LISTENING   : always emitted

Module-level session registry lets speech_runtime call mute/unmute directly
— no round-trip through the browser is needed.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512          # Silero VAD's required chunk at 16 kHz

# Barge-in: energy a chunk must exceed for a speech_start to be emitted while
# MARK is speaking.  Set above typical speaker-echo levels (~0.01–0.02 RMS on
# a closed-back mic) while well below normal voice (~0.08+).
_BARGE_IN_THRESHOLD = 0.045

# POST_SPEECH cool-down: number of 16kHz samples to discard transcripts for.
# 900ms × 16000 samples/s = 14400 samples.  Slightly longer than the TTS
# audio system's own 800ms holdoff so there is always overlap — no gap.
_POST_SPEECH_HOLDOFF_SAMPLES = int(0.90 * SAMPLE_RATE)  # 900 ms

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
    """Browser sends 16-bit signed little-endian PCM; Whisper/Silero want
    float32 in [-1, 1]."""
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(audio: np.ndarray, *, partial: bool = False) -> str:
    """Real Faster-Whisper transcription.  Segments where Whisper itself
    thinks there is no speech (no_speech_prob > 0.55) are discarded.
    Very short results (< 3 chars) are also rejected as noise."""
    if audio.size == 0:
        return ""
    model = _get_whisper_model()
    segments, _ = model.transcribe(
        audio, language="en", beam_size=1 if partial else 5, vad_filter=False,
    )
    texts: list[str] = []
    for seg in segments:
        if getattr(seg, "no_speech_prob", 0.0) > 0.55:
            continue
        t = seg.text.strip()
        if t:
            texts.append(t)
    result = " ".join(texts).strip()
    return result if len(result) >= 3 else ""


# ── Turn-taking states ────────────────────────────────────────────────────────
_STATE_LISTENING   = "listening"
_STATE_TTS_ACTIVE  = "tts_active"
_STATE_POST_SPEECH = "post_speech"


class VoiceSession:
    """
    One connection's live audio state.  Owns a Silero VADIterator and the
    turn-taking state machine that prevents MARK from hearing himself.

    Public API for the WebSocket handler:
        feed(raw_pcm)  — process an audio frame; returns events to forward
        mute()         — MARK started speaking (called by speech_runtime)
        unmute()       — MARK finished speaking (called by speech_runtime)
        reset()        — clean slate (called on disconnect / reconnect)
    """

    def __init__(self) -> None:
        from silero_vad import VADIterator
        self._vad = VADIterator(
            _get_vad_model(), sampling_rate=SAMPLE_RATE,
            threshold=0.5,
            min_silence_duration_ms=650,
        )
        self._pending  = np.array([], dtype=np.float32)
        self._utterance: list[np.ndarray] = []
        self.speech_active = False
        self.samples_since_partial = 0

        # Turn-taking state machine
        self._state = _STATE_LISTENING
        # Counts down samples during POST_SPEECH holdoff
        self._post_holdoff_remaining = 0
        # Event used so speech_runtime can wake the holdoff early if needed
        self._holdoff_done = threading.Event()
        self._holdoff_done.set()   # initially "done"

    # ── Turn-taking API (called by speech_runtime / voice_websocket) ──────────

    def mute(self) -> None:
        """MARK started speaking — hard-mute VAD and clear all buffers.

        Called by speech_runtime *before* the first audio byte is sent to the
        browser.  This eliminates the round-trip that previously let the mic
        pick up MARK's voice before the mute arrived.
        """
        if self._state == _STATE_TTS_ACTIVE:
            return   # already muted, idempotent
        self._state = _STATE_TTS_ACTIVE
        # Hard-reset VAD so stale pre-mute audio doesn't get processed later
        self._pending   = np.array([], dtype=np.float32)
        self._utterance = []
        self.speech_active = False
        self.samples_since_partial = 0
        try:
            self._vad.reset_states()
        except Exception:
            pass
        # Cancel any ongoing post-speech holdoff
        self._holdoff_done.set()
        logger.debug("voice_pipeline: → TTS_ACTIVE (VAD hard-reset)")

    def unmute(self) -> None:
        """MARK finished speaking — start POST_SPEECH cool-down.

        After the holdoff expires, VAD returns to full LISTENING state.
        The holdoff absorbs room reverb + browser AEC settling time so
        residual echo doesn't become a spurious transcript.
        """
        if self._state != _STATE_TTS_ACTIVE:
            return
        self._state = _STATE_POST_SPEECH
        self._post_holdoff_remaining = _POST_SPEECH_HOLDOFF_SAMPLES
        # Also reset VAD here — any audio picked up right as TTS ended should
        # not carry over into the clean listening window.
        self._pending   = np.array([], dtype=np.float32)
        self._utterance = []
        self.speech_active = False
        try:
            self._vad.reset_states()
        except Exception:
            pass
        self._holdoff_done.clear()
        logger.debug(
            "voice_pipeline: → POST_SPEECH (%dms holdoff)",
            _POST_SPEECH_HOLDOFF_SAMPLES * 1000 // SAMPLE_RATE,
        )

    def barge_in(self) -> None:
        """User clearly interrupted MARK — transition immediately to LISTENING
        so the next words are captured cleanly, without waiting for the holdoff.
        Called from feed() when a high-energy speech_start fires during TTS_ACTIVE.
        """
        self._state = _STATE_LISTENING
        self._post_holdoff_remaining = 0
        self._holdoff_done.set()
        logger.debug("voice_pipeline: barge-in → LISTENING")

    def reset(self) -> None:
        """Full reset — called on disconnect / reconnect."""
        self._state = _STATE_LISTENING
        try:
            self._vad.reset_states()
        except Exception:
            pass
        self._pending   = np.array([], dtype=np.float32)
        self._utterance = []
        self.speech_active = False
        self.samples_since_partial = 0
        self._post_holdoff_remaining = 0
        self._holdoff_done.set()

    # ── Audio feed ────────────────────────────────────────────────────────────

    def feed(self, raw_pcm: bytes) -> list[dict]:
        """
        Feed raw PCM16 bytes from the browser.  Returns zero or more events:
          {"type": "speech_start"}           — barge-in / user started talking
          {"type": "partial", "text": "..."} — interim transcript
          {"type": "final",   "text": "..."} — utterance finished

        State-machine behaviour:
          TTS_ACTIVE   → audio consumed, NO events (except high-energy barge-in)
          POST_SPEECH  → audio consumed, holdoff counter decremented, NO transcripts
          LISTENING    → full VAD + transcription pipeline
        """
        events: list[dict] = []
        samples = pcm16_to_float32(raw_pcm)

        # ── TTS_ACTIVE: full mute ─────────────────────────────────────────────
        if self._state == _STATE_TTS_ACTIVE:
            # Check chunk energy for barge-in detection
            rms = float(np.sqrt(np.mean(samples ** 2)))
            if rms >= _BARGE_IN_THRESHOLD:
                logger.info(
                    "voice_pipeline: barge-in detected (rms=%.4f ≥ %.4f) — interrupting",
                    rms, _BARGE_IN_THRESHOLD,
                )
                self.barge_in()
                events.append({"type": "speech_start"})
            # Discard all audio while muted (do NOT feed VAD)
            return events

        # ── POST_SPEECH: holdoff cool-down ────────────────────────────────────
        if self._state == _STATE_POST_SPEECH:
            consumed = min(len(samples), self._post_holdoff_remaining)
            self._post_holdoff_remaining -= consumed
            if self._post_holdoff_remaining <= 0:
                self._state = _STATE_LISTENING
                self._holdoff_done.set()
                logger.debug("voice_pipeline: holdoff expired → LISTENING")
            # Discard audio during holdoff — don't feed VAD
            return events

        # ── LISTENING: full VAD + transcription pipeline ───────────────────────
        self._pending = np.concatenate([self._pending, samples])

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


# ── Module-level session registry ─────────────────────────────────────────────
# speech_runtime calls mute_active_session() / unmute_active_session() directly
# so the mute arrives BEFORE the first audio byte — no browser round-trip needed.

_registry_lock = threading.Lock()
_active_session: "VoiceSession | None" = None


def register_session(session: VoiceSession) -> None:
    global _active_session
    with _registry_lock:
        _active_session = session
    logger.debug("voice_pipeline: session registered")


def unregister_session(session: VoiceSession) -> None:
    global _active_session
    with _registry_lock:
        if _active_session is session:
            _active_session = None
    logger.debug("voice_pipeline: session unregistered")


def mute_active_session() -> None:
    """Called by speech_runtime before the first TTS audio byte is sent."""
    with _registry_lock:
        s = _active_session
    if s is not None:
        s.mute()


def unmute_active_session() -> None:
    """Called by speech_runtime after the last TTS audio byte is sent."""
    with _registry_lock:
        s = _active_session
    if s is not None:
        s.unmute()
