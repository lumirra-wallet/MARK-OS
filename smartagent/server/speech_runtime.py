"""
MARK's Brain Runtime owns his voice — not the browser, not a bolted-on
demo. This module is the live bridge between "MARK is generating a reply"
(StreamingToken events on the run's EventBus, published from
_stream_llm_response and the chat/identity/clarification fast paths in
api.py) and "the owner hears MARK's real voice" (binary PCM16 audio frames
broadcast on the same /ws connection everything else already flows over).

Design
------
- Subscribes to StreamingToken, source="mark" only — worker/terminal
  output streamed for the dashboard's own benefit (source="print") is
  never spoken aloud.
- Buffers text until a complete sentence forms, then hands THAT SENTENCE
  ALONE to a dedicated background worker thread for synthesis+broadcast.
  Handing off to a queue (not synthesizing inline) matters: measured on
  this machine, Kokoro's real-time-factor on CPU is >1 (synthesis takes
  *longer* than the audio's own duration, not faster — see MARK-VOICE
  status notes) — if synthesis ran inline on the same thread that's
  pulling tokens from the LLM, every completed sentence would stall
  MARK's TEXT from streaming for as long as its audio took to render.
  With the queue, text keeps flowing at the LLM's own pace and MARK's
  VOICE may lag a little behind on slower hardware — audibly imperfect
  sometimes, but never at the cost of stalling the reply itself.
- Real interruption: /ws/voice's VoiceSession already detects the owner
  starting to speak (Silero VAD, speech_start) well before transcription
  completes; voice_websocket() calls interrupt() the instant that fires.
  The worker checks the interrupt flag before AND after synthesizing each
  sentence, so nothing further gets spoken or sent once set. The frontend
  independently stops audio PLAYBACK the moment it sees the same
  speech_start event on its own /ws/voice connection — that's the part
  that actually feels instant, since it doesn't wait on this module at
  all. A sentence already mid-synthesis when interrupted finishes
  rendering (Kokoro has no native cancel-mid-inference) but is discarded,
  never sent.

No setInterval-equivalent, no fake activity: every audio frame sent here
is real Kokoro output for real text MARK actually said.
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

# A "sentence" ends at ., !, or ? (optionally followed by a closing
# quote/paren) followed by whitespace or end-of-buffer. Not a
# linguistically perfect tokenizer (e.g. "Mr. Smith" can split early) —
# an acceptable tradeoff for how much sooner MARK starts speaking.
_SENTENCE_END_RE = re.compile(r'([.!?]+["\')\]]*(?:\s+|$))')

# A long unpunctuated stretch shouldn't block MARK from starting to speak —
# past this many buffered characters, force a flush at the last space.
# 160 chars (≈ 25 words) keeps TTS chunks short enough to start playing
# quickly and stay intelligible even without a natural sentence boundary.
_SOFT_FLUSH_LEN = 160

# Sentinel enqueued by flush() to mark "no more sentences for this reply".
_END_OF_REPLY = object()


def _split_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Split *buffer* into complete sentences plus a remainder that isn't
    terminated yet.

    Key fix: require at least 8 accumulated characters before treating a
    period as a sentence boundary. This filters abbreviations ("Mr.", "Dr.",
    "vs.", "U.S.") that have very short bodies before the period — they are
    folded back into the accumulator so the TTS never receives a garbled
    fragment like "Mr" as a standalone utterance.
    """
    parts = _SENTENCE_END_RE.split(buffer)
    sentences: list[str] = []
    accumulated = ""   # text built up across short/abbreviation boundaries
    i = 0
    while i + 1 < len(parts):
        body  = parts[i]
        punct = parts[i + 1]
        accumulated += body
        # Commit a sentence boundary only when there is enough substance.
        # "Mr. Smith" → body="Mr" (2 chars) → abbreviation, keep going.
        # "Hello there. " → body="Hello there" (11 chars) → real boundary.
        if len(accumulated.strip()) >= 8:
            candidate = (accumulated + punct).strip()
            if candidate:
                sentences.append(candidate)
            accumulated = ""
        else:
            # Abbreviation — fold punctuation back and keep accumulating.
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
    """One instance for the whole server process — see `speech_runtime`
    singleton at module bottom, matching connection_manager's own
    module-level-singleton pattern. Owns one persistent background worker
    thread (started lazily, lives for the process) that synthesizes
    queued sentences one at a time, in order — kept off the LLM-generation
    thread so slow synthesis never stalls MARK's text."""

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
        """Called once per run (loop is the same running loop each time,
        but re-attaching is cheap and avoids assuming call order)."""
        self._manager = manager
        self._loop = loop

    def reset(self) -> None:
        """Call at the start of every new MARK reply. Drains any sentences
        still queued from a reply that ended without a real VAD
        interrupt (e.g. the owner typed a new message instead of talking
        over MARK) — a new reply shouldn't have to play out behind stale
        audio. (There's a narrow window where a sentence already
        mid-synthesis on the worker thread at this exact moment could
        still slip through afterward — accepted as a rare, cosmetic
        edge case, not a functional one: real audio, real interruption,
        and real ordering all still hold.)"""
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
            threading.Thread(target=self._worker_loop, daemon=True, name="mark-speech-worker").start()

    def interrupt(self) -> None:
        """Call the instant the owner starts speaking (VAD speech_start)."""
        if not self._interrupted.is_set():
            self._interrupted.set()
            self._broadcast_event(ServerEvents.SPEECH_INTERRUPTED, {})

    def on_token(self, event: "Event") -> None:
        """EventBus subscriber for StreamingToken (see events.py). Only
        enqueues — never synthesizes here — so this returns immediately
        and the LLM's own token loop is never blocked on audio rendering."""
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
        """Call once the run/chat response is fully done — enqueues
        whatever text never reached a sentence boundary (e.g. a short
        reply with no terminal punctuation), then marks the reply's end
        so the worker emits SpeechEnd once it's actually spoken."""
        remainder, self._buffer = self._buffer.strip(), ""
        if remainder:
            self._queue.put(remainder)
        self._queue.put(_END_OF_REPLY)

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _END_OF_REPLY:
                if self._spoke_anything and not self._interrupted.is_set():
                    self._broadcast_event(ServerEvents.SPEECH_END, {})
                self._spoke_anything = False
                continue
            self._speak_sentence(item)  # type: ignore[arg-type]

    def _speak_sentence(self, text: str) -> None:
        if self._interrupted.is_set() or not text.strip():
            return
        try:
            pcm = tts_engine.synthesize(text)
        except Exception as exc:
            logger.warning("speech_runtime: synthesis failed for a sentence: %s", exc)
            return
        if not pcm or self._interrupted.is_set():
            return  # dropped — never send audio for text MARK was cut off saying
        if not self._spoke_anything:
            self._spoke_anything = True
            self._broadcast_event(ServerEvents.SPEECH_START, {})
        self._broadcast_bytes(pcm)

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
            asyncio.run_coroutine_threadsafe(self._manager.broadcast_bytes(data), self._loop)
        except RuntimeError:
            pass


# Module-level singleton used by api.py — mirrors connection_manager.
speech_runtime = SpeechRuntime()
