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
import re
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512          # Silero VAD's required chunk at 16 kHz

# ── Target RMS for audio normalization ───────────────────────────────────────
# Whisper accuracy drops sharply for quiet audio (RMS < 0.03).  We normalise
# every utterance to this level before transcription.  Gain is capped at 12×
# so broadband noise bursts don't get amplified into false transcriptions.
_NORM_TARGET_RMS  = 0.12
_NORM_MAX_GAIN    = 12.0

# Barge-in: energy a chunk must exceed for a speech_start to be emitted while
# MARK is speaking.  Room echo through a typical laptop/desk speaker measures
# ~0.02–0.05 RMS at the mic; genuine voice at conversational distance is
# typically ≥0.08.  Setting the threshold at 0.065 sits comfortably above
# steady echo.
_BARGE_IN_THRESHOLD = 0.065

# 1 hot chunk (~32 ms) is now enough to trigger barge-in.
# Echo transients are caught by the threshold (0.065) being well above
# speaker echo (0.02–0.05). A single chunk at conversational voice level
# is unambiguous — no need to wait for consecutive ones.
_BARGE_IN_CONSECUTIVE_CHUNKS = 1

# POST_SPEECH cool-down: number of 16kHz samples to discard transcripts for.
# 550ms absorbs room reverb + AEC settling without making Elena feel deaf.
# Reduced from 900ms → 550ms so she returns to listening ~350ms sooner.
_POST_SPEECH_HOLDOFF_SAMPLES = int(0.55 * SAMPLE_RATE)  # 550 ms

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
#
# Complete thoughts use speculative_final (fires immediately with 0 ms wait),
# so _STITCH_WINDOW_SAMPLES is only the fallback path.  0.8 s is plenty —
# if speculative_final already dispatched, dedup drops the "final" copy.
# Unfinished fragments still get a patient 2.5 s to continue their thought.
_STITCH_WINDOW_SAMPLES      = int(0.8 * SAMPLE_RATE)   # finished thought — fast fallback (speculative_final handles it)
_STITCH_WINDOW_LONG_SAMPLES = int(2.5 * SAMPLE_RATE)   # sounds unfinished — 2.5 s patience window

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


# ── Voice command detection ───────────────────────────────────────────────────
# Natural voice commands that should interrupt playback immediately, no LLM call.
# Checked case-insensitively against the full transcript.
_STOP_COMMANDS: frozenset[str] = frozenset({
    "stop", "pause", "wait", "hold on", "hold it",
    "never mind", "nevermind", "cancel", "cancel that",
    "forget it", "forget that", "that's okay", "never mind that",
    "enough", "quiet", "silence", "shh",
})

# Patterns that catch partial matches like "stop talking" or "pause for a second"
_STOP_PATTERNS = re.compile(
    r"\b(stop|pause|wait|hold on|cancel|quiet|silence|nevermind|never mind|"
    r"forget it|cancel that|enough)\b",
    re.IGNORECASE,
)

def _is_voice_command(text: str) -> tuple[bool, str]:
    """Return (is_command, command_type) for a transcript.

    Returns (True, 'stop') for interrupt/stop commands.
    Returns (False, '') otherwise.
    """
    t = text.strip().rstrip(".,!?").lower()
    # Exact match first (highest confidence)
    if t in _STOP_COMMANDS:
        return True, "stop"
    # Short phrase — check with pattern (avoid false positives in long sentences)
    if len(t.split()) <= 5 and _STOP_PATTERNS.search(t):
        return True, "stop"
    return False, ""


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
        # medium.en gives dramatically better accuracy than small.en for proper nouns,
        # accented speech, and geographic names (Spain, Argentina, etc.).
        # ~3× more parameters than small.en — still real-time on CPU for short
        # conversational utterances (< 30 s).  Override via MARK_WHISPER_MODEL env var.
        # Options: tiny.en, base.en, small.en, medium.en, large-v3-turbo, large-v3
        model_size = os.environ.get("MARK_WHISPER_MODEL", "medium.en")
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


def _normalize_audio(audio: np.ndarray) -> np.ndarray:
    """Normalize utterance amplitude to a consistent RMS level.

    Whisper's accuracy degrades significantly for quiet audio — a speaker who
    is far from the mic or speaking softly can drop below the threshold where
    Whisper reliably recognises phonemes.  Normalising to _NORM_TARGET_RMS
    before every transcription call levels the playing field regardless of mic
    gain, distance, or speaking volume.

    The gain cap (_NORM_MAX_GAIN) prevents broadband noise bursts from being
    amplified into false speech — if the chunk is genuinely silent/noise, RMS
    will be tiny and the cap keeps it from blowing up into a hallucination.
    """
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms < 1e-7:
        return audio   # truly silent — don't amplify
    gain = min(_NORM_TARGET_RMS / rms, _NORM_MAX_GAIN)
    return np.clip(audio * gain, -1.0, 1.0)


def transcribe(
    audio: np.ndarray,
    *,
    partial: bool = False,
    initial_prompt: str | None = None,
    hotwords: str | None = None,
) -> str:
    """Real Faster-Whisper transcription with vocabulary boosting.

    Parameters
    ----------
    audio:         Float32 PCM in [-1, 1] at 16 kHz.
    partial:       True → fast display-only pass (beam_size=1, no hotwords).
    initial_prompt: Last 1-3 turns of conversation text as a context hint.
                   Whisper's decoder biases toward tokens it has already seen
                   here — dramatically improves accented proper-noun recall.
    hotwords:      Comma-separated vocabulary string passed to faster-whisper's
                   hotwords parameter.  Adds a positive logit bias to every
                   matching token sequence during beam search.  Most effective
                   mechanism for fixing "Spain"→"spin" type errors: the model
                   actively prefers the hotword form when audio is ambiguous.

    Transcription quality knobs (final pass only)
    ----------------------------------------------
    beam_size=10    More hypotheses explored vs default 5 — catches the correct
                    token even when greedy search picks the wrong near-homophone.
    patience=2.0    Allows the beam search to continue past the first completed
                    hypothesis — improves recall for interrupted/fast speech.
    best_of=5       With temperature fallback: sample 5 candidates and pick the
                    highest-scoring one — reduces greedy decoding errors.
    temperature=    [0.0, 0.2, 0.4] fallback ladder — greedy first, then
                    progressively more sampling if compression/logprob checks
                    flag the result as uncertain.
    """
    if audio.size == 0:
        return ""

    # ── Feature 7: Noise Separation — spectral subtraction ───────────────────
    # Estimate stationary background noise from the first 0.1 s (usually
    # pre-speech silence) and subtract it from the power spectrum.
    # This reduces mic hiss, HVAC rumble, and keyboard noise before Whisper sees
    # the audio — improving accuracy in noisy environments without any extra dep.
    # Only applied to the final pass (not partials — speed matters there).
    if not partial:
        try:
            audio = _spectral_subtract_noise(audio)
        except Exception:
            pass  # always fall through to the original audio on any error

    # Normalize amplitude before sending to Whisper
    audio = _normalize_audio(audio)

    model = _get_whisper_model()

    if partial:
        # ── Partial (display-only): fast greedy, no expensive extras ──────────
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            best_of=1,
            patience=1.0,
            temperature=0.0,
            vad_filter=False,
            word_timestamps=False,
            condition_on_previous_text=bool(initial_prompt),
            initial_prompt=initial_prompt,
            suppress_blank=True,
            suppress_tokens=[-1],
        )
    else:
        # ── Final (authoritative): balanced speed+accuracy pass ───────────────
        segments, _ = model.transcribe(
            audio,
            language="en",
            # beam_size=5: 2× faster than 10 with minimal accuracy loss for
            # conversational speech. Elena responds in ~0.3 s instead of ~0.6 s.
            beam_size=5,
            # patience=1.2: slight lookahead past first hypothesis for proper nouns.
            patience=1.2,
            # best_of=3: sample 3 candidates — good balance vs cost.
            best_of=3,
            # Temperature: greedy first, one retry at 0.2 if uncertain.
            # Dropped the 0.4 tier — rarely needed and doubles worst-case latency.
            temperature=[0.0, 0.2],
            vad_filter=False,
            word_timestamps=False,
            condition_on_previous_text=bool(initial_prompt),
            initial_prompt=initial_prompt,
            hotwords=hotwords or None,
            suppress_blank=True,
            suppress_tokens=[-1],
        )

    texts: list[str] = []
    for seg in segments:
        # 0.50 threshold: keeps real speech from accented/quiet speakers that
        # Whisper would otherwise silently drop.  Noise bursts are caught by
        # the normalization cap + length filter below.
        if getattr(seg, "no_speech_prob", 0.0) > 0.50:
            continue
        t = seg.text.strip()
        if t:
            texts.append(t)
    result = " ".join(texts).strip()

    # ── Hallucination / noise filter ───────────────────────────────────────────
    # Whisper (especially small.en) generates characteristic "stuck" outputs
    # when fed noise, room hum, or very soft audio: repeated single characters
    # ("s s s s s", "ee ee ee ee"), music stubs ("[Music]", "(applause)"), or
    # very short repeated words.  Catch and discard these before they reach Elena.
    if result:
        result = _filter_hallucination(result)

    # Post-processing: apply targeted phonetic corrections (e.g. "Spayn"→"Spain").
    # Only for final pass — partials are display-only throwaway text.
    if not partial and result:
        try:
            from smartagent.server.vocabulary import apply_corrections
            result = apply_corrections(result)
        except Exception:
            pass

    # Minimum 2 chars — "ok", "no", "yes" are valid single-word turns.
    return result if len(result) >= 2 else ""


# ── Hallucination filter ───────────────────────────────────────────────────────
# Characteristic noise/stuck outputs from Whisper — discard before sending to LLM.

_HALLUCINATION_STUBS = re.compile(
    r"^\s*(\[.*?\]|\(.*?\)|♪.*?♪|you|thanks for watching|thank you for watching|"
    r"subtitles by|transcribed by|www\..+|http[s]?://)\s*$",
    re.IGNORECASE,
)
# Repeated single-char pattern: "s s s s s", "e e e e", "ee ee ee"
_REPEATED_NOISE = re.compile(r"^(\b\w{1,3}\b\s+){4,}$", re.IGNORECASE)

# Hotword-echo hallucination: when hotwords are active and audio is unclear,
# the decoder sometimes generates a comma-separated list of country names or
# a single word repeated many times.  These look exactly like the hotword list.
# Detect by checking that the text is ONLY comma-separated tokens with no verbs,
# function words, or sentence structure — a dead giveaway of hotword hallucination.
_COMMA_LIST_RE  = re.compile(r"^[A-Za-z\s,\.]+$")  # only letters, spaces, commas, dots
_REPEATED_TOKEN = re.compile(r"\b(\w+)\b(?:,?\s+\1\b){3,}", re.IGNORECASE)  # same token 4+ times


def _filter_hallucination(text: str) -> str:
    """Return empty string if ``text`` looks like a Whisper hallucination.

    Patterns caught:
    - Metadata stubs: [Music], (applause), ♪…♪, subtitles by, www.*
    - Repeated short-token noise: "s s s s s", "ee ee ee ee"
    - Single-character repetition: "sssssss"
    - Hotword-echo lists: "Argentina, Colombia, Spain, Colombia, Chile..." (no verbs, pure nouns)
    - Same word repeated 4+ times: "Canada, Canada, Canada, Canada..."
    """
    t = text.strip()
    if not t:
        return ""

    # Known stub patterns (metadata artifacts the model generates for silence)
    if _HALLUCINATION_STUBS.match(t):
        logger.debug("voice_pipeline: hallucination stub rejected: %r", t[:60])
        return ""

    # Repeated short-token noise (e.g. "s s s s s s", "ee ee ee ee")
    if _REPEATED_NOISE.match(t + " "):
        logger.debug("voice_pipeline: repeated noise rejected: %r", t[:60])
        return ""

    # Single repeated character spanning the whole output (e.g. "sssssss")
    unique_chars = set(t.replace(" ", "").lower())
    if len(unique_chars) == 1 and len(t) >= 6:
        logger.debug("voice_pipeline: single-char hallucination rejected: %r", t[:60])
        return ""

    # Repeated single-word token 4+ times: "Canada, Canada, Canada, Canada..."
    if _REPEATED_TOKEN.search(t):
        logger.debug("voice_pipeline: repeated-token hallucination rejected: %r", t[:60])
        return ""

    # Repeated multi-word phrase: split on commas, check if any segment appears ≥ 3×.
    # Catches "the United States, the United States, the United States of A".
    # Uses prefix matching so "the United States" and "the United States of A"
    # are both counted as repetitions of the same phrase.
    if "," in t:
        segments = [s.strip().lower().rstrip(".") for s in t.split(",") if s.strip()]
        if len(segments) >= 3:
            from collections import Counter
            seg_counts = Counter(segments)
            top_seg, top_count = seg_counts.most_common(1)[0]
            # Direct repetition: same phrase ≥ 3 times
            if top_count >= 3:
                logger.debug(
                    "voice_pipeline: repeated-phrase hallucination rejected (exact): %r", t[:60]
                )
                return ""
            # Prefix repetition: phrase appears ≥ 2 times AND ≥ 3 segments start with it.
            # Catches the "United States / United States / United States of A" pattern.
            if top_count >= 2 and len(top_seg.split()) >= 2:
                prefix_count = sum(1 for s in segments if s.startswith(top_seg))
                if prefix_count >= 3:
                    logger.debug(
                        "voice_pipeline: repeated-phrase hallucination rejected (prefix): %r", t[:60]
                    )
                    return ""

    # Hotword-list hallucination: a long comma-separated string with no sentence
    # structure (no verbs, articles, or typical sentence function words).
    # This catches "Argentina, Colombia, Chile, Spain, Colombia, Chile..."
    tokens = [tok.strip().rstrip(",.") for tok in t.split(",") if tok.strip()]
    if len(tokens) >= 4 and _COMMA_LIST_RE.match(t):
        # Check if the tokens look like a noun-only list (no common function words)
        _FUNCTION_WORDS = {
            "the", "a", "an", "and", "but", "or", "so", "if", "is", "are",
            "was", "were", "i", "you", "we", "they", "he", "she", "it",
            "have", "has", "do", "did", "will", "can", "would", "could",
            "to", "of", "in", "on", "at", "for", "with", "by", "that", "this",
        }
        lower_tokens = {tok.lower() for tok in tokens if tok}
        function_word_count = sum(1 for w in lower_tokens if w in _FUNCTION_WORDS)
        if function_word_count == 0 and len(tokens) >= 4:
            logger.debug(
                "voice_pipeline: hotword-list hallucination rejected (%d tokens): %r",
                len(tokens), t[:60],
            )
            return ""

    return t


# ── Feature 7: Noise Separation — spectral subtraction ────────────────────────
# Pure-numpy implementation.  Uses the first 100ms of the utterance (which is
# usually pre-speech background) to estimate the noise floor, then subtracts that
# estimate from the power spectrum of the whole utterance.
# Reduces stationary background noise (mic hiss, HVAC rumble, fan noise) before
# Whisper sees the audio — improving accuracy in noisy environments without any
# extra dependency beyond numpy (already required).

def _spectral_subtract_noise(audio: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Spectral subtraction noise reduction.

    Estimates the stationary noise floor from the first 100 ms of the signal
    (usually silence before the speaker starts) and subtracts it from every
    short-time power spectrum frame.  Returns a float32 audio array at the
    same length as the input.

    Only applied to final-pass audio (not partials) — accuracy matters there;
    speed matters for partials.  Fails silently: any exception causes the
    original audio to be returned unchanged.
    """
    if audio.size < sr // 10:   # <100 ms — nothing to subtract
        return audio

    n_fft      = 512
    hop        = n_fft // 4
    n_noise_frames = max(1, (sr // 10) // hop)   # first ~100 ms as noise ref

    # Hanning window
    window = np.hanning(n_fft).astype(np.float32)

    # Pad so we get complete frames at both ends
    audio_padded = np.pad(audio, (n_fft // 2, n_fft // 2), mode="reflect")

    # Build STFT (analysis)
    n_frames = 1 + (len(audio_padded) - n_fft) // hop
    frames   = np.lib.stride_tricks.sliding_window_view(audio_padded, n_fft)[::hop][:n_frames]
    spectra  = np.fft.rfft(frames * window, n=n_fft)   # shape: (frames, n_fft//2+1)

    # Noise estimate from first n_noise_frames
    noise_mag_sq = np.mean(np.abs(spectra[:n_noise_frames]) ** 2, axis=0)

    # Over-subtraction factor (α=2.0) + flooring (β=0.01) — standard SS parameters
    alpha = 2.0
    beta  = 0.01
    sig_mag_sq  = np.abs(spectra) ** 2
    clean_mag_sq = np.maximum(sig_mag_sq - alpha * noise_mag_sq, beta * sig_mag_sq)
    clean_mag    = np.sqrt(clean_mag_sq)

    # Restore phase from original spectra
    phase        = np.exp(1j * np.angle(spectra))
    clean_spectra = clean_mag * phase

    # ISTFT (synthesis) — overlap-add
    reconstructed = np.zeros(len(audio_padded), dtype=np.float32)
    window_sum    = np.zeros(len(audio_padded), dtype=np.float32)
    for i, frame_start in enumerate(range(0, len(audio_padded) - n_fft + 1, hop)):
        if i >= len(clean_spectra):
            break
        frame = np.fft.irfft(clean_spectra[i], n=n_fft).astype(np.float32) * window
        reconstructed[frame_start:frame_start + n_fft] += frame
        window_sum[frame_start:frame_start + n_fft]    += window ** 2

    # Normalize by window overlap (avoid division by zero)
    mask = window_sum > 1e-8
    reconstructed[mask] /= window_sum[mask]

    # Trim the padding back to original length and clip to [-1, 1]
    result = reconstructed[n_fft // 2 : n_fft // 2 + len(audio)]
    return np.clip(result, -1.0, 1.0).astype(np.float32)


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

        # Conversation context for Whisper initial_prompt
        # Updated after every turn by update_session_context() so Whisper
        # knows the active vocabulary and topic — dramatically improves
        # recognition of names, technical terms, and accented pronunciation.
        self._conversation_context: str = ""

        # Dynamic nouns extracted from conversation text — added to hotwords
        # so Whisper's decoder is already biased toward words the user or Elena
        # just said before the next transcription call.
        self._dynamic_nouns: list[str] = []

        # Cached hotwords string rebuilt on every context update
        self._hotwords_cache: str = ""
        self._rebuild_hotwords()

    def _rebuild_hotwords(self) -> None:
        """Rebuild the cached hotwords string from user vocab + dynamic nouns.

        Called on init and whenever the conversation context changes.
        """
        try:
            from smartagent.server.vocabulary import build_hotwords, user_vocabulary
            self._hotwords_cache = build_hotwords(
                context_nouns=self._dynamic_nouns,
                user_words=user_vocabulary.words,
            )
        except Exception as exc:
            logger.debug("voice_pipeline: hotwords build failed: %s", exc)
            self._hotwords_cache = ""

    def set_context(self, context: str) -> None:
        """Update the conversation context hint fed to Whisper as initial_prompt.

        Call this after every completed turn with the last 1-3 exchange lines.
        Whisper's decoder biases toward tokens it has already seen in the
        prompt, so giving it recent conversation text significantly improves
        accuracy for:
          - Accented/non-native speakers whose phoneme patterns differ
          - Names (Elena, workspace names, project terms)
          - Domain vocabulary the owner uses regularly
          - Any word the owner pronounces differently from the training norm

        Also extracts proper-noun candidates from the context text and adds
        them to the hotwords cache so Whisper is immediately biased toward
        words just mentioned — critical for proper nouns said for the first
        time before the static vocabulary list covers them.

        The initial_prompt is capped at 200 chars so it never exceeds Whisper's
        prompt token budget (~224 tokens for the smallest models).
        """
        self._conversation_context = context.strip()[-200:]

        # Extract capitalised nouns from the conversation and rebuild hotwords
        try:
            from smartagent.server.vocabulary import extract_nouns
            nouns = extract_nouns(context)
            # Merge with existing dynamic nouns, keep most recent 40
            combined = nouns + [n for n in self._dynamic_nouns if n not in nouns]
            self._dynamic_nouns = combined[:40]
        except Exception:
            pass

        self._rebuild_hotwords()

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
            # 0.35: catches softer/accented speech without too many false positives.
            threshold=0.35,
            # 600 ms silence → VAD "end" (was 1000 ms).
            # Shorter window means Elena starts responding ~400 ms sooner after
            # the owner stops speaking. The stitch window still handles natural
            # mid-thought pauses so short fragments get merged correctly.
            min_silence_duration_ms=600,
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

                    # ── Speaker identity check ────────────────────────────────
                    # Verify before transcription so low-confidence strangers
                    # can be flagged without wasting a Whisper call.
                    try:
                        from smartagent.server.speaker_profile import speaker_manager
                        sp = speaker_manager.verify(audio)
                        if sp.is_owner:
                            events.append({
                                "type": "speaker_identified",
                                "name": sp.owner_name,
                                "confidence": round(sp.confidence, 3),
                            })
                        else:
                            logger.info(
                                "voice_pipeline: unknown speaker (confidence=%.2f)", sp.confidence
                            )
                    except Exception as _sp_exc:
                        logger.debug("voice_pipeline: speaker check skipped: %s", _sp_exc)

                    text  = transcribe(
                        audio, partial=False,
                        initial_prompt=self._conversation_context or None,
                        hotwords=self._hotwords_cache or None,
                    )
                    if text:
                        # ── Voice command detection ───────────────────────────
                        # Check BEFORE appending to stitch buffer so commands
                        # interrupt immediately and never reach the LLM.
                        is_cmd, cmd_type = _is_voice_command(text)
                        if is_cmd:
                            logger.info("voice_pipeline: voice command detected %r → %s", text, cmd_type)
                            events.append({"type": "voice_command", "command": cmd_type, "text": text})
                            self._utterance = []
                            continue

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

            elif self.speech_active and self.samples_since_partial >= SAMPLE_RATE:
                # ── Partial transcript (display only, every ~1 s of speech) ───
                # Feature 2: Streaming Speech Recognition — emit partials every
                # 1 s so the UI shows words appearing as the user speaks, not
                # in 2 s jumps.  Still bounded at a 10 s tail to cap CPU.
                # Every partial re-transcribes the accumulated utterance, so a
                # 1 s cadence + a 10 s tail bound keeps the display live at a
                # fraction of the cost; the FINAL still uses the full audio.
                self.samples_since_partial = 0
                audio = np.concatenate(self._utterance)[-10 * SAMPLE_RATE:]
                text  = transcribe(
                    audio, partial=True,
                    initial_prompt=self._conversation_context or None,
                )
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


def update_session_context(user_text: str, assistant_text: str) -> None:
    """Feed the latest conversation turn into the active VoiceSession's Whisper
    initial_prompt so the next transcription is primed with real vocabulary.

    Called by api.py after every completed brain turn.  Thread-safe: reads the
    registry under lock, then calls set_context outside it (set_context itself
    only writes a plain str field — no lock needed for CPython's GIL).

    The prompt is built as «User: …  Elena: …» so Whisper sees both sides of
    the conversation — your words tell it your topic and vocabulary; Elena's
    words reinforce names and terms she used that you're likely to echo back.
    """
    with _registry_lock:
        s = _active_session
    if s is None:
        return
    # Truncate each side so the combined prompt fits the 200-char cap in
    # set_context().  User text gets more budget (120 vs 80) because Whisper
    # recognising YOUR words is more important than recognising Elena's reply.
    u = user_text.strip()[:120]
    a = assistant_text.strip()[:80]
    prompt = f"User: {u}  Elena: {a}" if a else f"User: {u}"
    s.set_context(prompt)
    logger.debug("voice_pipeline: Whisper context updated → %r", prompt[:80])
