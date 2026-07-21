"""
livekit_agent.py — MARK's persistent LiveKit voice agent.

MARK joins 'mark-presence' at server startup and stays connected indefinitely.
When a browser participant publishes a mic audio track, the agent subscribes
and runs the full voice pipeline server-side:

  Browser mic (LiveKit AudioTrack)
  → rtc.AudioStream (PCM16, 16 kHz mono)
  → Silero VAD (livekit-plugins-silero)   — speech boundary detection
  → Faster-Whisper                        — STT
  → MARK Brain (_voice_chat_response)     — LLM + memory + knowledge
  → speech_runtime (sentence streaming)  — Kokoro TTS
  → rtc.AudioSource.capture_frame         — PCM pushed to LiveKit
  → LocalAudioTrack (published to room)
  → Browser RemoteAudioTrack              — played by livekit-client SDK

Barge-in (< 200 ms):
  VAD START_OF_SPEECH while TTS is playing →
    audio_source.clear_queue()   — stops queued audio immediately
    speech_runtime.interrupt()   — stops new synthesis

The dashboard connects TO MARK.  MARK is already in the room first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

try:
    from livekit import rtc  # type: ignore[import-untyped]
    _LIVEKIT_AVAILABLE = True
except ImportError:
    rtc = None   # type: ignore[assignment]
    _LIVEKIT_AVAILABLE = False
    logger.warning(
        "livekit_agent: 'livekit' package not installed — voice pipeline disabled"
    )


class MARKLiveKitVoiceAgent:
    """
    Persistent voice agent — connects once at server start, stays forever.

    Audio flows entirely through LiveKit.  No custom /ws/voice WebSocket,
    no browser HTTP POST for utterances.
    """

    def __init__(self) -> None:
        self._room: Any = None
        # AudioSource drives the LocalAudioTrack; speech_runtime pushes PCM16 here.
        self._audio_source: Any = None
        self._tts_track: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # identity → asyncio.Task for each active browser participant
        self._participant_tasks: dict[str, "asyncio.Task[None]"] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Called once from app.py lifespan.  Non-blocking."""
        if not _LIVEKIT_AVAILABLE:
            logger.info("livekit_agent: disabled — 'livekit' package not installed")
            return
        from smartagent.server.livekit_token import livekit_configured
        if not livekit_configured():
            logger.info(
                "livekit_agent: LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set — disabled"
            )
            return

        self._loop = asyncio.get_running_loop()

        # AudioSource: 24 kHz mono — matches Kokoro's native output rate.
        self._audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)

        # Wire speech_runtime → this AudioSource so Kokoro TTS goes to LiveKit.
        from smartagent.server.speech_runtime import set_livekit_audio_source
        set_livekit_audio_source(self._audio_source, self._loop)

        asyncio.create_task(self._run(), name="mark-livekit-voice-agent")
        logger.info("livekit_agent: voice agent task launched")

    async def broadcast_session_event(self, event: dict) -> None:
        """Broadcast a JSON event to all room participants via data channel."""
        if not self._room:
            return
        try:
            await self._room.local_participant.publish_data(
                json.dumps(event).encode(),
                kind=rtc.DataPacketKind.KIND_RELIABLE,
            )
        except Exception as exc:
            logger.debug("livekit_agent: broadcast_session_event: %s", exc)

    # ── Connection loop ────────────────────────────────────────────────────────

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
                    "livekit_agent: disconnected (%s) — reconnecting in %.0f s",
                    exc, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _connect_and_run(self) -> None:
        from smartagent.server.livekit_token import create_agent_token, LIVEKIT_ROOM

        livekit_url = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
        token = create_agent_token(identity="mark-voice-agent")

        room = rtc.Room()
        self._room = room
        self._participant_tasks.clear()

        # Create TTS track backed by the persistent AudioSource.
        tts_track = rtc.LocalAudioTrack.create_audio_track("mark-voice", self._audio_source)
        self._tts_track = tts_track

        _done = asyncio.Event()

        @room.on("participant_connected")
        def _on_connected(participant: Any) -> None:
            logger.info("livekit_agent: participant joined  identity=%r", participant.identity)

        @room.on("participant_disconnected")
        def _on_disconnected_p(participant: Any) -> None:
            identity = getattr(participant, "identity", "")
            logger.info("livekit_agent: participant left   identity=%r", identity)
            task = self._participant_tasks.pop(identity, None)
            if task and not task.done():
                task.cancel()

        @room.on("track_subscribed")
        def _on_track_subscribed(
            track: Any, publication: Any, participant: Any
        ) -> None:
            identity = getattr(participant, "identity", "")
            if getattr(track, "kind", None) != rtc.TrackKind.KIND_AUDIO:
                return
            # Never process MARK's own tracks.
            if identity.startswith("mark-"):
                return
            logger.info(
                "livekit_agent: audio track subscribed from %r — starting pipeline",
                identity,
            )
            # Cancel previous task for this participant if it's still running.
            old = self._participant_tasks.pop(identity, None)
            if old and not old.done():
                old.cancel()
            task = asyncio.ensure_future(
                self._process_audio_track(track, identity)
            )
            self._participant_tasks[identity] = task

        @room.on("disconnected")
        def _on_room_disconnected(*_: object) -> None:
            _done.set()

        # ── Connect ────────────────────────────────────────────────────────────
        logger.info(
            "livekit_agent: connecting → %s  room=%r", livekit_url, LIVEKIT_ROOM
        )
        await room.connect(
            livekit_url, token,
            options=rtc.RoomOptions(auto_subscribe=True),
        )

        # Publish MARK's TTS audio track so the browser can subscribe.
        await room.local_participant.publish_track(
            tts_track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        logger.info(
            "livekit_agent: ✓ connected to %r — TTS track live", LIVEKIT_ROOM
        )

        # Handle any participants already in the room at connect time.
        for p in room.remote_participants.values():
            for pub in p.track_publications.values():
                t = getattr(pub, "track", None)
                if t and getattr(t, "kind", None) == rtc.TrackKind.KIND_AUDIO:
                    _on_track_subscribed(t, pub, p)

        try:
            await _done.wait()
        finally:
            self._room = None
            for task in self._participant_tasks.values():
                task.cancel()
            self._participant_tasks.clear()
            logger.info("livekit_agent: left room %r", LIVEKIT_ROOM)

    # ── Voice pipeline ─────────────────────────────────────────────────────────

    async def _process_audio_track(self, track: Any, identity: str) -> None:
        """
        Full voice pipeline for one browser participant's mic track.

        Runs two concurrent coroutines:
          feed_loop    — reads AudioStream frames → VAD stream + utterance buffer
          vad_event_loop — processes VAD events → barge-in / utterance dispatch
        """
        from livekit.agents import vad as _vad
        from livekit.plugins.silero import VAD as SileroVAD

        logger.info("livekit_agent: pipeline starting for %r", identity)

        vad_instance = SileroVAD.load(
            # 800 ms silence → END_OF_SPEECH.  Faster than the old 2 s window
            # (the old window was for stitching; stitching is now done here via
            # the stitch_timer below).
            min_silence_duration=0.8,
            min_speech_duration=0.1,
            prefix_padding_duration=0.3,
            activation_threshold=0.5,
        )
        vad_stream = vad_instance.stream()

        # Shared state between feed_loop and vad_event_loop.
        # Python GIL makes plain bool reads/writes safe across coroutines on
        # the same thread; the lock is only needed for the list mutation.
        utterance_chunks: list[bytes] = []
        is_speaking = False
        chunks_lock = threading.Lock()

        async def feed_loop() -> None:
            nonlocal is_speaking, utterance_chunks
            audio_stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
            async for frame_event in audio_stream:
                frame = frame_event.frame
                vad_stream.push_frame(frame)
                if is_speaking:
                    with chunks_lock:
                        utterance_chunks.append(bytes(frame.data))

        async def vad_event_loop() -> None:
            nonlocal is_speaking, utterance_chunks
            async for event in vad_stream:
                if event.type == _vad.VADEventType.START_OF_SPEECH:
                    is_speaking = True
                    with chunks_lock:
                        utterance_chunks = []
                    logger.info("livekit_agent: speech started (%r)", identity)

                    # Barge-in: stop MARK if he's currently producing audio.
                    from smartagent.server.speech_runtime import speech_runtime
                    if speech_runtime.currently_speaking:
                        logger.warning(
                            "livekit_agent: barge-in detected — stopping TTS"
                        )
                        if self._audio_source is not None:
                            self._audio_source.clear_queue()
                        speech_runtime.interrupt()

                    asyncio.ensure_future(
                        self._broadcast({"type": "speech_start"})
                    )

                elif event.type == _vad.VADEventType.END_OF_SPEECH:
                    if not is_speaking:
                        continue
                    is_speaking = False
                    with chunks_lock:
                        audio_bytes = b"".join(utterance_chunks)
                        utterance_chunks = []
                    logger.info(
                        "livekit_agent: speech ended — %.1f KB", len(audio_bytes) / 1024
                    )
                    asyncio.ensure_future(
                        self._handle_utterance(audio_bytes, identity)
                    )

        try:
            await asyncio.gather(feed_loop(), vad_event_loop())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("livekit_agent: pipeline error for %r: %s", identity, exc)
        finally:
            await vad_stream.aclose()
            logger.info("livekit_agent: pipeline ended for %r", identity)

    async def _handle_utterance(self, audio_bytes: bytes, identity: str) -> None:
        """STT → transcript broadcast → MARK Brain LLM response."""
        if not audio_bytes:
            return

        # ── STT: Faster-Whisper (blocking — run in thread) ─────────────────────
        try:
            from smartagent.server.voice_pipeline import transcribe, pcm16_to_float32
            audio_f32 = pcm16_to_float32(audio_bytes)
            text = await asyncio.to_thread(transcribe, audio_f32)
        except Exception as exc:
            logger.warning("livekit_agent: STT failed: %s", exc)
            return

        if not text:
            logger.debug("livekit_agent: STT empty — discarding")
            return

        logger.warning("livekit_agent: TRANSCRIPT %r", text[:120])

        # Broadcast final transcript to dashboard + data channel.
        await self._broadcast({"type": "final", "text": text})

        # ── LLM: MARK brain handles dedup, history, token streaming, TTS ──────
        # _voice_chat_response drives speech_runtime which publishes audio via
        # the registered AudioSource (set_livekit_audio_source).
        try:
            from smartagent.server.api import _voice_chat_response
            await _voice_chat_response(text, "")
        except Exception as exc:
            logger.warning("livekit_agent: LLM call failed: %s", exc)

    async def _broadcast(self, msg: dict) -> None:
        """Publish to LiveKit data channel + main /ws for dashboard UI."""
        # Data channel — all LiveKit room participants
        if self._room:
            try:
                await self._room.local_participant.publish_data(
                    json.dumps(msg).encode(),
                    kind=rtc.DataPacketKind.KIND_RELIABLE,
                )
            except Exception as exc:
                logger.debug("livekit_agent: data channel broadcast: %s", exc)

        # Main WebSocket — dashboard panels driven by MARK events
        try:
            from smartagent.server.websocket import connection_manager
            from datetime import datetime, timezone
            name_map = {
                "speech_start": "voice_speech_start",
                "partial":      "voice_partial",
                "final":        "voice_final",
            }
            await connection_manager.broadcast({
                "type":      "event",
                "name":      name_map.get(msg.get("type", ""), "voice_event"),
                "payload":   msg,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
        except Exception:
            pass


# ── Module-level singleton ─────────────────────────────────────────────────────
# Imported by app.py as `from smartagent.server.livekit_agent import livekit_agent`.
livekit_agent = MARKLiveKitVoiceAgent()
