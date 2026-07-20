"""Tests for smartagent.server.speech_runtime.

_split_complete_sentences is pure and fast — tested directly. The
SpeechRuntime tests use the REAL Kokoro engine (slow, real inference) and a
real background asyncio loop (matching how api.py actually drives it via
asyncio.run_coroutine_threadsafe) — only the WebSocket ConnectionManager is
faked, since exercising a real one needs a live FastAPI connection, which
belongs at the voice_websocket/api level instead.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from smartagent.brain.events import Event
from smartagent.server.speech_runtime import SpeechRuntime, _split_complete_sentences


class FakeConnectionManager:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.audio_chunks: list[bytes] = []

    async def broadcast(self, message: dict) -> None:
        self.events.append(message)

    async def broadcast_bytes(self, data: bytes) -> None:
        self.audio_chunks.append(data)


@pytest.fixture
def loop_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def _wait_until(predicate, timeout: float = 20.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestSentenceSplitting:
    def test_splits_multiple_complete_sentences(self):
        sentences, remainder = _split_complete_sentences("Hello there. How are you? ")
        assert sentences == ["Hello there.", "How are you?"]
        assert remainder == ""

    def test_leaves_incomplete_sentence_in_remainder(self):
        sentences, remainder = _split_complete_sentences("Hello there. This is unfin")
        assert sentences == ["Hello there."]
        assert remainder == "This is unfin"

    def test_empty_buffer_returns_nothing(self):
        sentences, remainder = _split_complete_sentences("")
        assert sentences == []
        assert remainder == ""

    def test_long_unpunctuated_stretch_soft_flushes(self):
        long_text = "word " * 60  # 300 chars, no terminal punctuation
        sentences, remainder = _split_complete_sentences(long_text)
        assert len(sentences) >= 1
        assert len(remainder) < len(long_text)


@pytest.mark.slow
class TestSpeechRuntimeReal:
    def test_speaks_complete_sentences_as_real_audio(self, loop_thread):
        manager = FakeConnectionManager()
        runtime = SpeechRuntime()
        runtime.attach(manager, loop_thread)
        runtime.reset()

        runtime.on_token(Event(name="StreamingToken", payload={"text": "Hello there. ", "source": "mark"}))
        assert _wait_until(lambda: len(manager.audio_chunks) >= 1), "no audio was broadcast for a complete sentence"
        assert len(manager.audio_chunks[0]) > 0
        assert any(e["name"] == "SpeechStart" for e in manager.events)

        runtime.flush()
        assert _wait_until(lambda: any(e["name"] == "SpeechEnd" for e in manager.events))

    def test_interrupt_stops_further_sentences(self, loop_thread):
        manager = FakeConnectionManager()
        runtime = SpeechRuntime()
        runtime.attach(manager, loop_thread)
        runtime.reset()

        runtime.on_token(Event(name="StreamingToken", payload={"text": "First sentence. ", "source": "mark"}))
        assert _wait_until(lambda: len(manager.audio_chunks) >= 1)
        chunks_before_interrupt = len(manager.audio_chunks)

        runtime.interrupt()
        assert _wait_until(lambda: any(e["name"] == "SpeechInterrupted" for e in manager.events))

        runtime.on_token(Event(
            name="StreamingToken",
            payload={"text": "Second sentence should never be spoken. ", "source": "mark"},
        ))
        time.sleep(0.5)  # give it a chance to (wrongly) synthesize if the flag were broken
        assert len(manager.audio_chunks) == chunks_before_interrupt

    def test_ignores_non_mark_source_tokens(self, loop_thread):
        manager = FakeConnectionManager()
        runtime = SpeechRuntime()
        runtime.attach(manager, loop_thread)
        runtime.reset()

        runtime.on_token(Event(
            name="StreamingToken",
            payload={"text": "print output should not be spoken. ", "source": "print"},
        ))
        time.sleep(0.5)
        assert len(manager.audio_chunks) == 0
