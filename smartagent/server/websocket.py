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

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new client."""
        await ws.accept()
        self._active.add(ws)
        logger.info("WebSocket client connected  total=%d", len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        """Unregister a disconnected client."""
        self._active.discard(ws)
        logger.info("WebSocket client disconnected  total=%d", len(self._active))

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

    async def send_to(self, ws: WebSocket, message: dict[str, Any]) -> None:
        """Send a message to a single client."""
        try:
            await ws.send_text(json.dumps(message, default=str))
        except Exception:
            self._active.discard(ws)

    async def broadcast_bytes(self, data: bytes) -> None:
        """
        Send a raw binary frame (MARK's synthesized speech audio — PCM16
        mono, 24kHz) to every connected client. Same dead-connection
        cleanup as broadcast(); a separate method because audio frames are
        binary WebSocket frames, not JSON text frames.
        """
        if not self._active:
            return
        dead: set[WebSocket] = set()
        for ws in set(self._active):
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.add(ws)
        self._active -= dead

    @property
    def count(self) -> int:
        return len(self._active)


# Module-level singleton shared across api.py, events.py, and the WS handler.
connection_manager = ConnectionManager()
