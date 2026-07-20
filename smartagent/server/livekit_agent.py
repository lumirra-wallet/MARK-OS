"""
livekit_agent.py — MARK's LiveKit room presence agent.

Joins 'mark-presence' at server startup and stays connected for the process
lifetime.  This agent handles ONLY real-time session coordination:

  • Tracks which human participants are in the room (presence).
  • Receives data-channel control messages (tts_start / tts_end) from the
    browser and passes them to the active VoiceSession.
  • Broadcasts session state over the data channel (speech_start, partial,
    final transcript events) so all room participants stay in sync.

Audio transport — mic → STT, TTS → speaker — travels on the /ws/voice
WebSocket (Silero VAD → faster-whisper → Kokoro PCM binary frames on /ws).
LiveKit carries NO audio; it only coordinates who is in the conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Graceful import — if 'livekit' package is missing the agent is disabled
# rather than crashing the server at import time.
try:
    from livekit import rtc   # type: ignore[import-untyped]
    _LIVEKIT_AVAILABLE = True
except ImportError:
    rtc = None  # type: ignore[assignment]
    _LIVEKIT_AVAILABLE = False
    logger.warning(
        "livekit_agent: 'livekit' package not installed — "
        "LiveKit presence disabled (audio via WebSocket still works)"
    )


class MarkLiveKitAgent:
    """
    Singleton presence agent (see module-level `livekit_agent`).

    Call ``await agent.start()`` from the FastAPI lifespan; it schedules a
    background asyncio task and returns immediately.  The task connects to
    the LiveKit room and reconnects automatically on any drop.
    """

    def __init__(self) -> None:
        self._room: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # identity → participant display name (presence tracking)
        self._participants: dict[str, str] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Called once from app.py lifespan.  Non-blocking."""
        if not _LIVEKIT_AVAILABLE:
            logger.info("livekit_agent: disabled — 'livekit' package not installed")
            return
        from smartagent.server.livekit_token import livekit_configured
        if not livekit_configured():
            logger.info("livekit_agent: LIVEKIT_API_KEY / LIVEKIT_API_SECRET not set — disabled")
            return
        self._loop = asyncio.get_running_loop()
        asyncio.create_task(self._run(), name="mark-livekit-agent")
        logger.info("livekit_agent: presence background task launched")

    # ── Internal connection loop ───────────────────────────────────────────────

    async def _run(self) -> None:
        """Reconnect loop with exponential back-off (cap 30 s)."""
        backoff = 2.0
        while True:
            try:
                await self._connect_and_run()
                backoff = 2.0    # reset on clean disconnect
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
        self._participants.clear()

        # ── Event handlers (string event names — livekit SDK ≥ 1.x) ──────────

        @room.on("participant_connected")
        def _on_participant_connected(participant: Any) -> None:
            identity = getattr(participant, "identity", "")
            name     = getattr(participant, "name", identity)
            self._participants[identity] = name
            logger.info("livekit_agent: participant joined  identity=%r", identity)

        @room.on("participant_disconnected")
        def _on_participant_disconnected(participant: Any) -> None:
            identity = getattr(participant, "identity", "")
            self._participants.pop(identity, None)
            logger.info("livekit_agent: participant left   identity=%r", identity)

        @room.on("data_received")
        def _on_data_received(data: Any) -> None:
            # Fire-and-forget: schedule the coroutine on the event loop
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._handle_data(data), self._loop
                )

        _done = asyncio.Event()

        @room.on("disconnected")
        def _on_disconnected(*_: object) -> None:
            _done.set()

        # ── Connect ────────────────────────────────────────────────────────────
        logger.info("livekit_agent: connecting → %s  room=%r", livekit_url, LIVEKIT_ROOM)
        await room.connect(livekit_url, token, options=rtc.RoomOptions(auto_subscribe=False))
        logger.info("livekit_agent: joined presence room %r (%d participants)",
                    LIVEKIT_ROOM, len(room.remote_participants))

        try:
            await _done.wait()
        finally:
            self._room = None
            logger.info("livekit_agent: left room %r", LIVEKIT_ROOM)

    # ── Data channel ───────────────────────────────────────────────────────────

    async def _handle_data(self, data: Any) -> None:
        """Control messages from the browser over the LiveKit data channel.

        Currently used for session state sync.  Audio-gate signals (tts_start /
        tts_end) are also handled by /ws/voice — this is just a belt-and-suspenders
        path so room participants who connect via LiveKit also stay in sync.
        """
        try:
            payload  = getattr(data, "data", b"")
            msg      = json.loads(bytes(payload).decode())
        except Exception:
            return

        msg_type = msg.get("type", "")
        logger.debug("livekit_agent: data-channel msg type=%r", msg_type)

    async def broadcast_session_event(self, event: dict) -> None:
        """Broadcast a JSON event to all room participants via the data channel.

        Called externally (e.g. from api.py) to push speech_start / transcript
        events to all LiveKit room participants so any dashboard connected via
        LiveKit stays in sync with the voice session state.
        """
        if not self._room:
            return
        try:
            payload = json.dumps(event).encode()
            await self._room.local_participant.publish_data(
                payload,
                kind=rtc.DataPacketKind.KIND_RELIABLE,
            )
        except Exception as exc:
            logger.debug("livekit_agent: broadcast_session_event: %s", exc)


# ── Module-level singleton ─────────────────────────────────────────────────────
livekit_agent = MarkLiveKitAgent()
