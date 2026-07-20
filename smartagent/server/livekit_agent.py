"""
livekit_agent.py — MARK's persistent LiveKit room participant.

Joins 'mark-presence' at server startup and stays connected for the process
lifetime. Handles the audio transport between the browser and MARK's Brain
Runtime:

  Inbound : browser mic → LiveKit → AudioStream → VoiceSession.feed() → VAD+STT
  Outbound: speech_runtime → enqueue_audio() → capture_frame() → LiveKit → browser

MARK's Brain Runtime (voice_pipeline, tts_engine, speech_runtime) is
completely unchanged. Only the transport carrier moves: WebSocket → LiveKit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue as stdlib_queue
from typing import Any

logger = logging.getLogger(__name__)

# Graceful import — if 'livekit' package is missing, the agent is disabled
# rather than crashing the entire server at import time.
try:
    from livekit import rtc  # type: ignore[import-untyped]
    _LIVEKIT_AVAILABLE = True
except ImportError:
    rtc = None  # type: ignore[assignment]
    _LIVEKIT_AVAILABLE = False
    logger.warning(
        "livekit_agent: 'livekit' package not installed — "
        "run `pip install livekit` or add it to requirements.minimal.txt"
    )


class MarkLiveKitAgent:
    """
    One instance per server process (see module-level singleton below).

    Call ``await agent.start()`` from the FastAPI lifespan; it schedules a
    background asyncio task and returns immediately.  The task connects to
    the LiveKit room and reconnects automatically on any drop.
    """

    def __init__(self) -> None:
        # Thread-safe queue: speech_runtime worker → asyncio capture_frame.
        # maxsize=64 at 24 kHz / ~1024-sample chunks ≈ ≥2.5 s of audio buffer.
        self._out_queue: stdlib_queue.Queue[bytes] = stdlib_queue.Queue(maxsize=64)
        self._audio_source: Any = None  # rtc.AudioSource when connected
        self._room: Any = None          # rtc.Room when connected
        self._loop: asyncio.AbstractEventLoop | None = None
        # identity → VoiceSession (one session per human participant)
        self._sessions: dict[str, Any] = {}

    # ── Public API (called from other modules) ─────────────────────────────────

    async def start(self) -> None:
        """Called once from app.py lifespan.  Non-blocking."""
        if not _LIVEKIT_AVAILABLE:
            logger.info("livekit_agent: disabled — package not installed")
            return
        from smartagent.server.livekit_token import livekit_configured
        if not livekit_configured():
            logger.info(
                "livekit_agent: LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set "
                "(run `python -m smartagent.server.livekit_setup` to configure)"
            )
            return
        self._loop = asyncio.get_running_loop()
        asyncio.create_task(self._run(), name="mark-livekit-agent")
        logger.info("livekit_agent: background task launched")

    def enqueue_audio(self, pcm_bytes: bytes) -> None:
        """Thread-safe.  Called from speech_runtime's TTS worker thread.

        Puts a PCM16 chunk (24 kHz, mono) into the output queue so the asyncio
        task can publish it via LiveKit.  Drops silently when the queue is full
        — real-time audio, stale frames are useless.
        """
        try:
            self._out_queue.put_nowait(pcm_bytes)
        except stdlib_queue.Full:
            pass  # drop — TTS worker must never block here

    # ── Main reconnect loop ────────────────────────────────────────────────────

    async def _run(self) -> None:
        backoff = 2.0
        while True:
            try:
                await self._connect_and_run()
                backoff = 2.0
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(
                    "livekit_agent: disconnected (%s) — reconnecting in %.0f s", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _connect_and_run(self) -> None:
        import os
        from smartagent.server.livekit_token import create_agent_token, LIVEKIT_ROOM

        livekit_url = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
        token       = create_agent_token()

        room = rtc.Room()
        self._room = room
        self._sessions.clear()

        # ── Event handlers ───────────────────────────────────────────────────

        @room.on("participant_disconnected")
        def _on_participant_disconnected(participant: Any) -> None:
            identity = getattr(participant, "identity", "")
            dropped  = self._sessions.pop(identity, None)
            if dropped:
                logger.debug("livekit_agent: session closed for '%s'", identity)

        @room.on("track_subscribed")
        def _on_track_subscribed(
            track: Any, publication: Any, participant: Any
        ) -> None:
            if not _LIVEKIT_AVAILABLE:
                return
            if isinstance(track, rtc.RemoteAudioTrack):
                identity = getattr(participant, "identity", "unknown")
                logger.info("livekit_agent: subscribing to audio from '%s'", identity)
                asyncio.ensure_future(
                    self._receive_audio(track, identity),
                    loop=self._loop,
                )

        @room.on("data_received")
        def _on_data_received(data: Any) -> None:
            asyncio.ensure_future(
                self._handle_data(data),
                loop=self._loop,
            )

        # ── Connect ──────────────────────────────────────────────────────────
        logger.info("livekit_agent: connecting → %s  room='%s'", livekit_url, LIVEKIT_ROOM)
        await room.connect(livekit_url, token, options=rtc.RoomOptions(auto_subscribe=True))
        logger.info("livekit_agent: joined '%s'", LIVEKIT_ROOM)

        # ── Publish MARK's TTS audio track ───────────────────────────────────
        source = rtc.AudioSource(sample_rate=24000, num_channels=1)
        self._audio_source = source
        track = rtc.LocalAudioTrack.create_audio_track("mark-voice", source)
        await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        logger.info("livekit_agent: MARK voice track published (24 kHz mono)")

        # ── Audio output pump ─────────────────────────────────────────────────
        out_task = asyncio.create_task(self._audio_out_loop(), name="livekit-out")

        try:
            await room.wait_until_disconnected()
        finally:
            out_task.cancel()
            self._audio_source = None
            self._room = None
            logger.info("livekit_agent: left room '%s'", LIVEKIT_ROOM)

    # ── Inbound: browser mic → VoiceSession ───────────────────────────────────

    async def _receive_audio(self, track: Any, identity: str) -> None:
        """Stream browser mic frames through VoiceSession (VAD+STT, unchanged)."""
        session = self._get_or_create_session(identity)
        # Resample to 16 kHz mono — exactly what VoiceSession.feed() expects.
        stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
        async for event in stream:
            frame     = event.frame
            pcm_bytes = bytes(frame.data)
            try:
                events = await asyncio.to_thread(session.feed, pcm_bytes)
            except Exception as exc:
                logger.debug("livekit_agent: session.feed error: %s", exc)
                continue
            for ev in events:
                await self._handle_vad_event(ev, identity)

    async def _handle_vad_event(self, ev: dict, identity: str) -> None:
        from smartagent.server.speech_runtime import speech_runtime
        from smartagent.server import api as _api

        etype = ev.get("type", "")

        if etype == "speech_start":
            # 1. Stop synthesis — interrupt flag prevents any new frames
            speech_runtime.interrupt()
            # 2. Cancel the current inference task
            task = getattr(_api, "_current_inference_task", None)
            if task and not task.done():
                task.cancel()
            # 3. Notify MARK's brain layer
            brain = getattr(_api, "_brain", None)
            if brain is not None:
                try:
                    await brain.voice_interrupted()
                except Exception:
                    pass
            # 4. Tell the browser to stop playback immediately (data channel)
            await self._send_data({"type": "speech_start"})
            logger.debug("livekit_agent: barge-in from '%s'", identity)

        elif etype in ("partial", "final"):
            # Forward transcript to all room participants so the dashboard
            # can show interim text while the user is speaking.
            await self._send_data(ev)

    # ── Data channel: tts_start / tts_end from browser ───────────────────────

    async def _handle_data(self, data: Any) -> None:
        """Control messages from the browser — gate the mic echo guard."""
        try:
            payload  = getattr(data, "data", b"")
            msg      = json.loads(bytes(payload).decode())
            participant = getattr(data, "participant", None)
            identity = getattr(participant, "identity", "") if participant else ""
        except Exception:
            return

        session  = self._sessions.get(identity)
        msg_type = msg.get("type", "")

        if msg_type == "tts_start":
            if session:
                try:
                    await asyncio.to_thread(session.mute)
                except Exception:
                    pass
        elif msg_type == "tts_end":
            # 350 ms holdoff matches the existing voice pipeline behaviour.
            await asyncio.sleep(0.35)
            if session:
                try:
                    await asyncio.to_thread(session.unmute)
                except Exception:
                    pass

    # ── Outbound: PCM queue → LiveKit room ────────────────────────────────────

    async def _audio_out_loop(self) -> None:
        """Drain the thread-safe PCM queue; publish each chunk as an AudioFrame.

        Uses run_in_executor so queue.get() blocks a threadpool thread — never
        the asyncio event loop.  1-second timeout keeps the task responsive to
        cancellation even when the TTS queue is empty.
        """
        loop = asyncio.get_running_loop()
        while True:
            try:
                pcm = await asyncio.wait_for(
                    loop.run_in_executor(None, self._out_queue.get),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return

            if not pcm or not self._audio_source:
                continue

            # Interrupt check: don't send audio that was queued before a barge-in
            # arrived.  The queue may have accumulated a few chunks between when
            # interrupt() was called and when the worker noticed the flag.
            from smartagent.server.speech_runtime import speech_runtime as _sr
            if _sr._interrupted.is_set():
                # Drain the queue without publishing
                while True:
                    try:
                        self._out_queue.get_nowait()
                    except stdlib_queue.Empty:
                        break
                continue

            num_samples = len(pcm) // 2  # int16 LE → samples
            frame = rtc.AudioFrame(
                data=pcm,
                sample_rate=24000,
                num_channels=1,
                samples_per_channel=num_samples,
            )
            try:
                await self._audio_source.capture_frame(frame)
            except Exception as exc:
                logger.debug("livekit_agent: capture_frame: %s", exc)

    # ── Data channel helper ────────────────────────────────────────────────────

    async def _send_data(self, msg: dict) -> None:
        if not self._room:
            return
        try:
            await self._room.local_participant.publish_data(
                json.dumps(msg).encode(),
                kind=rtc.DataPacketKind.KIND_RELIABLE,
            )
        except Exception as exc:
            logger.debug("livekit_agent: publish_data: %s", exc)

    # ── Session factory ────────────────────────────────────────────────────────

    def _get_or_create_session(self, identity: str) -> Any:
        if identity not in self._sessions:
            from smartagent.server.voice_pipeline import VoiceSession
            logger.info("livekit_agent: new VoiceSession for '%s'", identity)
            self._sessions[identity] = VoiceSession()
        return self._sessions[identity]


# ── Module-level singleton ─────────────────────────────────────────────────────
# speech_runtime imports this to call enqueue_audio().
# app.py imports this to call start() and attach_livekit().
livekit_agent = MarkLiveKitAgent()
