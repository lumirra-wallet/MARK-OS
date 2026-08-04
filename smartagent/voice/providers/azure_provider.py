"""
Azure Speech Provider (Stub / Extensible Implementation).

Demonstrates provider abstraction for easy switching to Azure Speech Service.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from smartagent.voice.providers.abstract_provider import (
    ErrorEvent,
    VoiceEvent,
    VoiceProvider,
)

logger = logging.getLogger("smartagent.voice.providers.azure")


class AzureProvider(VoiceProvider):
    """
    Azure Speech Provider Stub.
    """

    def __init__(self, subscription_key: Optional[str] = None, region: str = "eastus") -> None:
        self.subscription_key = subscription_key
        self.region = region
        self._connected = False
        self._event_queue: asyncio.Queue[VoiceEvent] = asyncio.Queue()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        logger.info("Initializing Azure Speech Provider...")
        if not self.subscription_key:
            err = "Azure Subscription Key missing."
            await self._event_queue.put(ErrorEvent(message=err))
            raise ValueError(err)
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_audio_chunk(self, pcm_data: bytes) -> None:
        pass

    async def send_text(self, text: str) -> None:
        pass

    async def send_tool_response(self, call_id: str, name: str, response: Dict[str, Any]) -> None:
        pass

    async def receive_events(self) -> AsyncGenerator[VoiceEvent, None]:
        while True:
            event = await self._event_queue.get()
            yield event
            self._event_queue.task_done()
