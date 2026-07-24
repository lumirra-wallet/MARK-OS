"""
MARK's Brain Runtime owns his voice.  This module bridges "MARK is generating
a reply" (StreamingToken events on the EventBus) with "the owner hears MARK's
real voice" (audio frames on the LiveKit audio track).

Key design decisions
--------------------
- Subscribes to StreamingToken, source="mark" only.
- Buffers text until a complete sentence forms, then hands THAT SENTENCE to a
  dedicated background worker thread for synthesis+broadcast.  Decoupling from
  the LLM token loop means slow Kokoro synthesis never stalls MARK's text stream.
- LiveKit audio: once livekit_agent registers an AudioSource via
  set_livekit_audio_source(), all synthesized PCM16 is pushed there instead of
  being broadcast as binary WebSocket frames.  The browser plays MARK's voice
  via the subscribed RemoteAudioTrack — no custom WebSocket for audio.
- Barge-in: the voice agent calls interrupt() + audio_source.clear_queue() the
  instant VAD detects speech onset.  The worker stops synthesis and clears the
  currently_speaking flag immediately.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from smartagent.server import tts_engine
from smartagent.server.events import ServerEvents

if TYPE_CHECKING:
    from smartagent.brain.events import Event
    from smartagent.server.websocket import ConnectionManager

logger = logging.getLogger(__name__)

_SENTENCE_END_RE = re.compile(r'([.!?]+["\')\]]*(?:\s+|$))')

# Force a flush when no sentence boundary has been seen for this many chars.
# 60 chars — produces the first audio chunk sooner (≈ half a sentence),
# cutting time-to-first-audio even on short utterances.  Kokoro synthesizes
# a 60-char sentence in ~0.3 s vs ~0.8 s for 160 chars.
_SOFT_FLUSH_LEN = 60

_END_OF_REPLY = object()   # sentinel in the worker queue

# ── LiveKit audio source (set by livekit_agent.start()) ───────────────────────
# When set, synthesized PCM16 is pushed here instead of broadcast over /ws.
_livekit_audio_source: Any = None      # rtc.AudioSource | None
_livekit_loop: asyncio.AbstractEventLoop | None = None


def set_livekit_audio_source(
    source: Any, loop: asyncio.AbstractEventLoop
) -> None:
    """
    Called by MARKLiveKitVoiceAgent.start() to register the AudioSource that
    backs the LiveKit LocalAudioTrack.  After this call all TTS audio goes to
    LiveKit instead of /ws binary frames.
    """
    global _livekit_audio_source, _livekit_loop
    _livekit_audio_source = source
    _livekit_loop = loop
    logger.info("speech_runtime: LiveKit AudioSource registered — TTS via LiveKit")


def _split_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Split *buffer* into complete sentences + an unterminated remainder."""
    parts = _SENTENCE_END_RE.split(buffer)
    sentences: list[str] = []
    accumulated = ""
    i = 0
    while i + 1 < len(parts):
        body  = parts[i]
        punct = parts[i + 1]
        accumulated += body
        if len(accumulated.strip()) >= 8:
            candidate = (accumulated + punct).strip()
            if candidate:
                sentences.append(candidate)
            accumulated = ""
        else:
            accumulated += punct
        i += 2
    remainder = accumulated + (parts[i] if i < len(parts) else "")

    if len(remainder) > _SOFT_FLUSH_LEN:
        cut = remainder.rfind(" ", 0, _SOFT_FLUSH_LEN)
        if cut > 0:
            head, remainder = remainder[:cut].strip(), remainder[cut:].lstrip()
            if head:
                sentences.append(head)
    return sentences, remainder


class SpeechRuntime:
    """One process-wide singleton.  Thread-safe: all mutable state (buffer,
    queue, flags) is only written by the caller thread (attach/reset/on_token/
    flush) or the single worker thread — never concurrently."""

    def __init__(self) -> None:
        self._manager: "ConnectionManager | None" = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._buffer = ""
        self._interrupted = threading.Event()
        self._spoke_anything = False
        # True while MARK is actively pushing audio (checked by voice agent for barge-in).
        self._currently_speaking = False
        self._queue: "queue.SimpleQueue[str | object]" = queue.SimpleQueue()
        self._worker_lock = threading.Lock()
        self._worker_started = False

    def attach(self, manager: "ConnectionManager", loop: asyncio.AbstractEventLoop) -> None:
        self._manager = manager
        self._loop = loop

    def reset(self) -> None:
        """Call at the start of every new MARK reply.  Drains stale queued
        sentences from any previous reply that completed without a VAD interrupt."""
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        self._buffer = ""
        self._interrupted.clear()
        self._spoke_anything = False
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker_started:
                return
            self._worker_started = True
            threading.Thread(
                target=self._worker_loop, daemon=True, name="mark-speech-worker"
            ).start()

    def interrupt(self) -> None:
        """Call the instant the user starts speaking (VAD speech_start).
        Stops synthesis and clears the currently_speaking flag immediately."""
        if not self._interrupted.is_set():
            self._interrupted.set()
            self._currently_speaking = False
            self._broadcast_event(ServerEvents.SPEECH_INTERRUPTED, {})

    @property
    def currently_speaking(self) -> bool:
        """True while MARK is actively producing TTS audio.
        Read by the voice agent to decide whether to barge-in."""
        return self._currently_speaking

    def on_token(self, event: "Event") -> None:
        """EventBus subscriber for StreamingToken.  Enqueues only — never
        synthesizes here — so the LLM token loop is never stalled."""
        if self._interrupted.is_set():
            return
        if event.payload.get("source") != "mark":
            return
        text = event.payload.get("text") or ""
        if not text:
            return
        self._buffer += text
        sentences, self._buffer = _split_complete_sentences(self._buffer)
        for sentence in sentences:
            self._queue.put(sentence)

    def flush(self) -> None:
        """Call once the run/chat response is fully done."""
        remainder, self._buffer = self._buffer.strip(), ""
        if remainder:
            self._queue.put(remainder)
        self._queue.put(_END_OF_REPLY)

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _END_OF_REPLY:
                if self._spoke_anything:
                    if not self._interrupted.is_set():
                        self._broadcast_event(ServerEvents.SPEECH_END, {})
                    self._unmute_mic()
                self._spoke_anything = False
                self._currently_speaking = False
                continue
            self._speak_sentence(item)  # type: ignore[arg-type]

    def _speak_sentence(self, text: str) -> None:
        if self._interrupted.is_set() or not text.strip():
            return
        try:
            pcm = tts_engine.synthesize(text)
        except Exception as exc:
            logger.warning("speech_runtime: synthesis failed: %s", exc)
            return
        if not pcm or self._interrupted.is_set():
            return   # discarded — never send audio for text MARK was cut off on
        if not self._spoke_anything:
            self._spoke_anything = True
            self._currently_speaking = True
            self._mute_mic()
            self._broadcast_event(ServerEvents.SPEECH_START, {})
        self._broadcast_bytes(pcm)

    # ── Mic control helpers ───────────────────────────────────────────────────

    def _mute_mic(self) -> None:
        try:
            from smartagent.server.voice_pipeline import mute_active_session, set_tts_active
            set_tts_active(True)
            mute_active_session()
        except Exception as exc:
            logger.debug("speech_runtime: mute_active_session failed (expected in LiveKit mode): %s", exc)

    def _unmute_mic(self) -> None:
        try:
            from smartagent.server.voice_pipeline import unmute_active_session, set_tts_active
            unmute_active_session()
            set_tts_active(False)
        except Exception as exc:
            logger.debug("speech_runtime: unmute_active_session failed (expected in LiveKit mode): %s", exc)

    # ── Broadcast helpers ─────────────────────────────────────────────────────

    def _broadcast_event(self, name: str, payload: dict[str, Any]) -> None:
        if self._manager is None or self._loop is None or self._loop.is_closed():
            return
        msg = {
            "type": "event", "name": name, "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            asyncio.run_coroutine_threadsafe(self._manager.broadcast(msg), self._loop)
        except RuntimeError:
            pass

    def _broadcast_bytes(self, data: bytes) -> None:
        """Push synthesized PCM16 audio.

        Priority 1 (new): LiveKit AudioSource — audio published via LocalAudioTrack.
        Priority 2 (legacy fallback): broadcast binary frames over /ws.
        """
        src = _livekit_audio_source
        loop = _livekit_loop

        if src is not None and loop is not None and not loop.is_closed():
            # Push via LiveKit AudioSource (24 kHz mono; Kokoro output rate).
            try:
                from livekit import rtc  # type: ignore[import-untyped]
                num_samples = len(data) // 2  # int16 = 2 bytes per sample
                if num_samples > 0:
                    frame = rtc.AudioFrame(
                        data=data,
                        sample_rate=24000,
                        num_channels=1,
                        samples_per_channel=num_samples,
                    )
                    asyncio.run_coroutine_threadsafe(
                        src.capture_frame(frame), loop
                    )
            except Exception as exc:
                logger.debug("speech_runtime: LiveKit capture_frame failed: %s", exc)
            return

        # Legacy path: binary frames on main /ws (used when LiveKit is not configured).
        if self._manager is None or self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._manager.broadcast_bytes(data), self._loop
            )
        except RuntimeError:
            pass


# Module-level singleton shared with api.py and events.py.
speech_runtime = SpeechRuntime()
