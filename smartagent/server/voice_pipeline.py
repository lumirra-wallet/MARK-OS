"""
voice_pipeline.py — real local streaming speech-to-text + voice activity
detection for MARK's voice interface.

Faster-Whisper (STT) + Silero VAD, both running locally — no cloud account,
no API key, no per-request cost.

Audio pipeline:
    Microphone (browser) → binary PCM16 frames over /ws/voice
        → Silero VAD (speech start/end detection, ~30ms latency)
        → Utterance stitching buffer (up to 2 s inter-sentence gap)
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

Phone-call feel — utterance stitching
--------------------------------------
After VAD fires "end", we do NOT immediately emit "final".  Instead we open a
_STITCH_WINDOW_SAMPLES window.  If the user starts speaking again before the
window expires (natural mid-thought pause), the new speech is appended at the
text level to the previous fragment.  The combined "final" is only emitted once
the stitch window expires with no new speech — giving MARK the full thought
rather than multiple fragments.

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
# MARK is speaking.  Room echo through a typical laptop/desk speaker measures
# ~0.02–0.05 RMS at the mic; genuine voice at conversational distance is
# typically ≥0.08.  Setting the threshold at 0.065 sits comfortably above
# steady echo.
_BARGE_IN_THRESHOLD = 0.065

# A single hot 32 ms chunk is NOT a barge-in: echo transients and clunks
# spike briefly and were cutting MARK off mid-sentence ("Mark never says
# everything").  Require this many CONSECUTIVE hot chunks (~100 ms of
# sustained voice) before interrupting — a real interruption easily
# sustains this; a spike never does.
_BARGE_IN_CONSECUTIVE_CHUNKS = 3

# POST_SPEECH cool-down: number of 16kHz samples to discard transcripts for.
# 900ms × 16000 samples/s = 14400 samples.  Slightly longer than the TTS
# audio system's own 800ms holdoff so there is always overlap — no gap.
_POST_SPEECH_HOLDOFF_SAMPLES = int(0.90 * SAMPLE_RATE)  # 900 ms

# Barge-in echo holdoff: after a barge-in, apply a short POST_SPEECH holdoff
# (200ms) before opening the VAD for transcription.  The chunk that tripped the
# barge-in threshold was already discarded; this absorbs the tail of the echo
# burst so Whisper never sees MARK's own voice as "user speech".
_BARGE_IN_ECHO_HOLDOFF_SAMPLES = int(0.20 * SAMPLE_RATE)  # 200 ms

# Utterance stitch window: after VAD fires "end" we wait this many samples
# before emitting "final".  If the user starts speaking again within the window,
# the new fragment is merged (at the text level) with the previous one so MARK
# receives the complete thought, not a series of fragments.
#
# ADAPTIVE: the window depends on whether the transcript so far LOOKS like a
# finished thought.  The owner speaks with natural mid-thought pauses and
# restarts; a fixed short window kept cutting them off and MARK answered
# fragments he never fully heard.  A finished-sounding sentence gets the
# short window (snappy reply); a trailing-off one gets the long window
# (patience).  See _looks_complete().
_STITCH_WINDOW_SAMPLES      = int(1.2 * SAMPLE_RATE)   # finished thought
_STITCH_WINDOW_LONG_SAMPLES = int(4.0 * SAMPLE_RATE)   # sounds unfinished — 4 s for slower/thoughtful speakers

# Trailing words that strongly signal "I'm not done talking".
_TRAILING_CONTINUATIONS = {
    "and", "but", "so", "or", "because", "like", "um", "uh", "the", "a",
    "to", "of", "with", "that", "is", "was", "if", "when", "then", "also",
    # Extended filler / continuation signals
    "i", "it", "you", "we", "they", "he", "she", "just", "even", "really",
    "yeah", "okay", "right", "well", "actually", "basically", "literally",
    "mean", "think", "kind", "sort", "gonna", "gotta", "wanna", "cause",
    "about", "around", "through", "for", "at", "in", "on", "by", "this",
}


def _looks_complete(text: str) -> bool:
    """Heuristic: does this transcript sound like a finished thought?

    Whisper punctuates its output, so terminal punctuation is a strong
    completion signal; a trailing conjunction/filler or a very short
    fragment is a strong continuation signal.
    """
    t = text.strip()
    if not t:
        return False
    if t[-1] in ".!?":
        last_word = t.rstrip(".!?,").rsplit(" ", 1)[-1].lower()
        return last_word not in _TRAILING_CONTINUATIONS
    # No terminal punctuation (trailing comma, dash, or nothing) → unfinished.
    return False

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
    # beam_size=5 (faster-whisper's default) roughly 3-5x's the CPU time of
    # beam_size=2 for a marginal accuracy gain — on CPU-only hardware that
    # was a real, measurable slice of the "few seconds before MARK responds"
    # latency users felt on every single turn. 2 keeps most of the accuracy
    # while cutting that cost substantially; partials stay at 1 (display-only).
    model = _get_whisper_model()
    segments, _ = model.transcribe(
        audio, language="en", beam_size=1 if partial else 2, vad_filter=False,
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

    Phone-call stitching
    --------------------
    VAD fires "end" after 2 000 ms of silence within a single utterance.
    On "end" we start _stitch_remaining counting down.  If the user speaks
    again before it reaches zero, the new speech is appended to
    _pending_final (text level) and _stitch_remaining resets.  Only when
    _stitch_remaining hits zero (2 s of genuine silence after the last
    fragment) do we emit {"type": "final", "text": <full_thought>}.
    """

    def __init__(self) -> None:
        # VAD model is loaded LAZILY on the first audio frame (_ensure_vad):
        # mic-denied tabs connect + retry every 10 s without ever sending a
        # frame — eager loading burned a model load per retry for nothing.
        self._vad_model: Any = None
        self._vad: Any = None
        self._pending  = np.array([], dtype=np.float32)
        self._utterance: list[np.ndarray] = []
        self.speech_active = False
        self.samples_since_partial = 0

        # Utterance stitching state
        # After VAD fires "end" we buffer the transcript here and count down
        # _stitch_remaining.  If speech starts again before the window expires
        # the new fragment is appended; when the window expires the whole
        # thing is emitted as one "final".
        self._pending_final: str | None = None
        self._stitch_remaining: int = 0   # samples; counts down when not speaking

        # Turn-taking state machine
        self._state = _STATE_LISTENING
        # Consecutive hot chunks while MARK speaks (sustained barge-in gate)
        self._barge_in_streak = 0
        # Counts down samples during POST_SPEECH holdoff
        self._post_holdoff_remaining = 0
        # Event used so speech_runtime can wake the holdoff early if needed
        self._holdoff_done = threading.Event()
        self._holdoff_done.set()   # initially "done"

    def _ensure_vad(self) -> None:
        """Load this session's PRIVATE VAD model on first audio.

        Private instance per session — never a shared singleton:
        VADIterator.__init__ resets its model's internal state, and with a
        shared model a second connection resets state MID-UTTERANCE for the
        active session — its VAD then never fires "end" for speech it no
        longer remembers and the conversation silently dies (observed live).
        Lazy so connections that never send audio never pay the load.
        """
        if self._vad is not None:
            return
        from silero_vad import VADIterator, load_silero_vad
        self._vad_model = load_silero_vad()
        self._vad = VADIterator(
            self._vad_model, sampling_rate=SAMPLE_RATE,
            threshold=0.5,
            # 800 ms silence → VAD "end".  Short enough for phone-call
            # responsiveness; anything the owner resumes within the 1.2 s
            # stitch window still merges into the same utterance, so slow
            # thinkers aren't cut off — their fragments are joined.
            min_silence_duration_ms=800,
        )

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
        self._pending_final = None
        self._stitch_remaining = 0
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
        self._pending_final = None
        self._stitch_remaining = 0
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
        """User clearly interrupted MARK — stop TTS and prepare to transcribe.

        We apply a short POST_SPEECH holdoff (200ms) rather than jumping
        directly to LISTENING.  The chunk that exceeded _BARGE_IN_THRESHOLD
        was already discarded by feed(); the holdoff absorbs the trailing edge
        of the echo burst so Whisper never sees MARK's own speaker audio as a
        user utterance.  After 200ms of received PCM the session transitions
        to LISTENING automatically and the user's real voice is captured.
        """
        self._state = _STATE_POST_SPEECH
        self._post_holdoff_remaining = _BARGE_IN_ECHO_HOLDOFF_SAMPLES
        # Reset VAD state so the trailing echo doesn't prime a false speech-start
        self._pending   = np.array([], dtype=np.float32)
        self._utterance = []
        self.speech_active = False
        self._pending_final = None
        self._stitch_remaining = 0
        try:
            self._vad.reset_states()
        except Exception:
            pass
        self._holdoff_done.clear()
        logger.debug("voice_pipeline: barge-in → 200ms echo holdoff → LISTENING")

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
        self._pending_final = None
        self._stitch_remaining = 0
        self._post_holdoff_remaining = 0
        self._holdoff_done.set()

    # ── Audio feed ────────────────────────────────────────────────────────────

    def feed(self, raw_pcm: bytes) -> list[dict]:
        """
        Feed raw PCM16 bytes from the browser.  Returns zero or more events:
          {"type": "speech_start"}           — barge-in / user started talking
          {"type": "partial", "text": "..."} — interim transcript (including any
                                               stitched prefix from earlier frags)
          {"type": "final",   "text": "..."} — full thought (stitched), ready for LLM

        State-machine behaviour:
          TTS_ACTIVE   → audio consumed, NO events (except high-energy barge-in)
          POST_SPEECH  → audio consumed, holdoff counter decremented, NO transcripts
          LISTENING    → full VAD + transcription + stitching pipeline
        """
        events: list[dict] = []
        samples = pcm16_to_float32(raw_pcm)

        # ── TTS_ACTIVE: full mute ─────────────────────────────────────────────
        if self._state == _STATE_TTS_ACTIVE:
            # Sustained-energy barge-in: require _BARGE_IN_CONSECUTIVE_CHUNKS
            # hot chunks in a row (~100 ms of real voice).  A single spike —
            # echo transient, cough, clunk — resets nothing MARK is saying.
            rms = float(np.sqrt(np.mean(samples ** 2)))
            if rms >= _BARGE_IN_THRESHOLD:
                self._barge_in_streak += 1
            else:
                self._barge_in_streak = 0
            if self._barge_in_streak >= _BARGE_IN_CONSECUTIVE_CHUNKS:
                logger.warning(
                    "voice_pipeline: sustained barge-in (rms=%.4f x%d) — interrupting",
                    rms, self._barge_in_streak,
                )
                self._barge_in_streak = 0
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

        # ── LISTENING: full VAD + transcription + stitching pipeline ──────────
        self._ensure_vad()
        self._pending = np.concatenate([self._pending, samples])

        while len(self._pending) >= VAD_CHUNK_SAMPLES:
            chunk = self._pending[:VAD_CHUNK_SAMPLES]
            self._pending = self._pending[VAD_CHUNK_SAMPLES:]

            result = self._vad(chunk, return_seconds=False)
            if self.speech_active:
                self._utterance.append(chunk)
                self.samples_since_partial += VAD_CHUNK_SAMPLES

            if result and "start" in result:
                # ── Speech started (or resumed within stitch window) ──────────
                self.speech_active = True
                self._utterance = [chunk]
                self.samples_since_partial = 0
                events.append({"type": "speech_start"})
                # _pending_final is intentionally kept — it will be prepended
                # to the next transcription fragment at "end" time.
                # _stitch_remaining resets when "end" fires (below).

            elif result and "end" in result:
                # ── Speech ended — immediate thinking cue, then transcribe ────
                # Fire "thinking" the INSTANT VAD says you stopped talking —
                # before Whisper even starts (~300-800 ms before "final").
                # The frontend shows a pulse immediately so there's zero
                # perceived silence between user finishing and MARK responding.
                events.append({"type": "thinking"})
                self.speech_active = False
                if self._utterance:
                    audio = np.concatenate(self._utterance)
                    text  = transcribe(audio, partial=False)
                    if text:
                        # Append to any existing pending fragment
                        if self._pending_final:
                            self._pending_final = self._pending_final + " " + text
                        else:
                            self._pending_final = text
                        # (Re)start the stitch window countdown — patient when
                        # the thought sounds unfinished, snappy when it doesn't.
                        complete = _looks_complete(self._pending_final)
                        self._stitch_remaining = (
                            _STITCH_WINDOW_SAMPLES if complete
                            else _STITCH_WINDOW_LONG_SAMPLES
                        )
                        logger.warning(
                            "voice_pipeline: fragment captured %r — stitch %.1fs (%s)",
                            self._pending_final[:60],
                            self._stitch_remaining / SAMPLE_RATE,
                            "complete" if complete else "unfinished",
                        )
                        # ── Speculative early dispatch ────────────────────────
                        # For complete-sounding thoughts, dispatch the LLM NOW
                        # (no stitch wait) instead of waiting 1.2 s.  We emit
                        # "speculative_final" so the voice_websocket can start
                        # the brain immediately.  The stitch window still runs;
                        # if the user continues talking, speech_start cancels
                        # the in-flight inference.  If they don't, the 1.2 s
                        # "final" fires but the dedup guard drops it (same text,
                        # < 5 s window).  Net saving: 1.2 s per complete turn.
                        if complete:
                            events.append({
                                "type": "speculative_final",
                                "text": self._pending_final,
                            })
                self._utterance = []

            elif self.speech_active and self.samples_since_partial >= 2 * SAMPLE_RATE:
                # ── Partial transcript (display only, every ~2 s of speech) ───
                # Every partial re-transcribes the accumulated utterance, so a
                # 1 s cadence over an unbounded buffer was O(n²) CPU during
                # long speech — a real contributor to the 100%-CPU stalls.
                # 2 s cadence + a 10 s tail bound keeps the display live at a
                # fraction of the cost; the FINAL still uses the full audio.
                self.samples_since_partial = 0
                audio = np.concatenate(self._utterance)[-10 * SAMPLE_RATE:]
                text  = transcribe(audio, partial=True)
                if text:
                    # Show full context: already-stitched prefix + current fragment
                    if self._pending_final:
                        display = (self._pending_final + " " + text).strip()
                    else:
                        display = text
                    events.append({"type": "partial", "text": display})

            # ── Stitch-window countdown ───────────────────────────────────────
            # Tick down every chunk while not currently speaking.
            # When it reaches zero we have 2 s of genuine silence — emit final.
            if self._pending_final and not self.speech_active:
                self._stitch_remaining -= VAD_CHUNK_SAMPLES
                if self._stitch_remaining <= 0:
                    text_out = self._pending_final.strip()
                    self._pending_final   = None
                    self._stitch_remaining = 0
                    if text_out:
                        logger.warning(
                            "voice_pipeline: FINAL emitted %r", text_out[:80]
                        )
                        events.append({"type": "final", "text": text_out})

        return events


# ── Module-level session registry ─────────────────────────────────────────────
# speech_runtime calls mute_active_session() / unmute_active_session() directly
# so the mute arrives BEFORE the first audio byte — no browser round-trip needed.
#
# _tts_active mirrors whether speech_runtime is currently sending TTS audio.
# It is set by speech_runtime via set_tts_active() on every mute/unmute call.
# When a new voice session registers mid-playback (model-load race or reconnect),
# we can immediately mute it rather than letting it hear MARK's current sentence.

_registry_lock = threading.Lock()
_active_session: "VoiceSession | None" = None
_tts_active = False   # True while speech_runtime is sending audio frames


def set_tts_active(active: bool) -> None:
    """Called by speech_runtime to keep the registry informed of TTS state."""
    global _tts_active
    _tts_active = active


# How long (in samples at 16 kHz) to suppress transcription after a fresh
# session registers when TTS is NOT currently active.  Absorbs any residual
# echo from MARK's startup greeting that played before the VAD model loaded.
_STARTUP_HOLDOFF_SAMPLES = int(1.5 * SAMPLE_RATE)   # 1.5 s


def register_session(session: VoiceSession) -> None:
    """Register a new VoiceSession.

    If TTS is currently active (MARK is mid-sentence when the voice WS
    reconnected or connected for the first time during playback), immediately
    hard-mute the new session — it would otherwise start in LISTENING and
    hear the tail of MARK's current sentence.

    If TTS is not active, apply a 1.5-second startup holdoff so any room
    echo from MARK's opening greeting (which may have played while the VAD
    model was still loading) clears before transcription opens.
    """
    global _active_session
    with _registry_lock:
        _active_session = session
    if _tts_active:
        session.mute()
        logger.debug("voice_pipeline: session registered mid-TTS — immediately hard-muted")
    else:
        # Startup holdoff — don't open the VAD until the echo from the
        # greeting that played during model-load has had time to decay.
        with _registry_lock:
            pass   # just to serialise the state write below
        session._state = _STATE_POST_SPEECH
        session._post_holdoff_remaining = _STARTUP_HOLDOFF_SAMPLES
        session._holdoff_done.clear()
        logger.debug(
            "voice_pipeline: session registered with %.1fs startup holdoff",
            _STARTUP_HOLDOFF_SAMPLES / SAMPLE_RATE,
        )


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
