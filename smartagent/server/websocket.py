"""
WebSocket connection manager.

Maintains the set of connected dashboard clients and broadcasts JSON
messages to all of them.  Thread-safe (broadcast is an async method called
via asyncio.run_coroutine_threadsafe from the event bridge).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections and broadcasts messages to all clients.

    Audio (binary PCM frames) is sent to the *audio owner* only — the most
    recently connected client.  Replit's reverse proxy opens 4-9 parallel
    transport connections from the same browser tab, so sending binary frames
    to every connection causes the browser to play each phrase that many times.
    Tracking a single owner means exactly one copy reaches the browser
    regardless of how many transport sockets the infra keeps open.

    JSON event frames still go to every connected client so state stays in
    sync across all connections.

    Usage::

        manager = ConnectionManager()

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket):
            await manager.connect(ws)
            try:
                while True:
                    await ws.receive_text()   # keep alive / handle pings
            except WebSocketDisconnect:
                manager.disconnect(ws)
    """

    def __init__(self) -> None:
        self._active: set[WebSocket] = set()
        # The most-recently-connected client.  Receives binary audio frames.
        # Rotates to the next surviving connection when the owner disconnects.
        self._audio_owner: WebSocket | None = None

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new client; it becomes the audio owner."""
        await ws.accept()
        self._active.add(ws)
        self._audio_owner = ws
        logger.info(
            "WebSocket client connected  total=%d  audio_owner=new", len(self._active)
        )

    def disconnect(self, ws: WebSocket) -> None:
        """Unregister a disconnected client."""
        self._active.discard(ws)
        if self._audio_owner is ws:
            # Pass audio ownership to whatever connection is still alive so
            # playback survives a reconnect race where the new connection
            # registered before this disconnect fires.
            self._audio_owner = next(iter(self._active), None)
        logger.info(
            "WebSocket client disconnected  total=%d  audio_owner=%s",
            len(self._active), "yes" if self._audio_owner else "none",
        )

    async def broadcast(self, message: dict[str, Any]) -> None:
        """
        Serialize *message* to JSON and send it to every connected client.

        Dead connections are silently removed.
        """
        if not self._active:
            return
        text = json.dumps(message, default=str)
        dead: set[WebSocket] = set()
        for ws in set(self._active):           # iterate copy to allow mutation
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        self._active -= dead
        # Rotate audio owner away from any dead connections
        if self._audio_owner in dead:
            self._audio_owner = next(iter(self._active), None)

    async def send_to(self, ws: WebSocket, message: dict[str, Any]) -> None:
        """Send a message to a single client."""
        try:
            await ws.send_text(json.dumps(message, default=str))
        except Exception:
            self._active.discard(ws)
            if self._audio_owner is ws:
                self._audio_owner = next(iter(self._active), None)

    async def broadcast_bytes(self, data: bytes) -> None:
        """
        Send a raw binary frame (MARK's synthesized speech audio — PCM16
        mono, 24kHz) to the *audio owner only*.

        Sending to every connected client causes the browser to play the
        phrase as many times as there are open transport connections —
        typically 4-9 on Replit's proxy — hence the owner-only model.
        """
        owner = self._audio_owner
        if owner is None:
            return
        try:
            await owner.send_bytes(data)
        except Exception:
            self._active.discard(owner)
            self._audio_owner = next(iter(self._active), None)

    @property
    def count(self) -> int:
        return len(self._active)

    @property
    def active_connections(self) -> int:
        """Alias for count — used by the idle inspector and other callers."""
        return len(self._active)


# Module-level singleton shared across api.py, events.py, and the WS handler.
connection_manager = ConnectionManager()
