"""
MARK's Brain Runtime owns his voice.  This module bridges "MARK is generating
a reply" (StreamingToken events on the EventBus) with "the owner hears MARK's
real voice" (binary PCM16 audio frames on /ws).

Key design decisions
--------------------
- Subscribes to StreamingToken, source="mark" only.
- Buffers text until a complete sentence forms, then hands THAT SENTENCE to a
  dedicated background worker thread for synthesis+broadcast.  Decoupling from
  the LLM token loop means slow Kokoro synthesis never stalls MARK's text stream.
- Proactive mic mute: the moment the worker is about to send the FIRST audio
  byte of a new reply, it calls voice_pipeline.mute_active_session().  This
  happens BEFORE any audio reaches the browser, so MARK's speaker output is
  never captured by the mic.  No round-trip through the browser is needed.
- Post-speech holdoff: after the last audio byte, unmute_active_session() is
  called.  VoiceSession's own holdoff (900ms, sample-accurate) absorbs room
  reverb + AEC settling before transcription re-opens.
- Real interruption: voice_websocket() calls interrupt() the instant VAD fires
  speech_start; the worker discards any further synthesis and signals the
  voice pipeline to return to LISTENING immediately.
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
# ~25 words — keeps TTS chunks short and TTFA low on long run-on sentences.
_SOFT_FLUSH_LEN = 160

_END_OF_REPLY = object()   # sentinel in the worker queue


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
        """Call the instant the owner starts speaking (VAD speech_start)."""
        if not self._interrupted.is_set():
            self._interrupted.set()
            self._broadcast_event(ServerEvents.SPEECH_INTERRUPTED, {})

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
                    # Unmute the active voice session.  VoiceSession's own
                    # POST_SPEECH holdoff (900ms, sample-accurate) handles
                    # the echo cool-down — we don't need to sleep here.
                    self._unmute_mic()
                self._spoke_anything = False
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
            # ── Proactive mute: silence the mic BEFORE the first audio byte ──
            # This is the key fix for the self-echo loop.  By muting here, we
            # guarantee MARK's speaker output is never processed by the VAD,
            # regardless of browser AEC latency or round-trip timing.
            self._mute_mic()
            self._broadcast_event(ServerEvents.SPEECH_START, {})
        self._broadcast_bytes(pcm)

    # ── Mic control helpers ───────────────────────────────────────────────────

    def _mute_mic(self) -> None:
        try:
            from smartagent.server.voice_pipeline import mute_active_session
            mute_active_session()
        except Exception as exc:
            logger.debug("speech_runtime: mute_active_session failed: %s", exc)

    def _unmute_mic(self) -> None:
        try:
            from smartagent.server.voice_pipeline import unmute_active_session
            unmute_active_session()
        except Exception as exc:
            logger.debug("speech_runtime: unmute_active_session failed: %s", exc)

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
