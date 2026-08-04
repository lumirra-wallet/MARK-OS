"""
Abstract Voice Provider Interface.

Defines the contract for real-time bi-directional streaming voice providers.
Supports Gemini Live API, OpenAI Realtime API, Azure Speech, etc.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional


@dataclass(kw_only=True)
class VoiceEvent:
    """Base event emitted by voice providers."""

    type: str  # 'audio', 'text', 'interrupted', 'tool_call', 'turn_complete', 'error'


@dataclass(kw_only=True)
class AudioOutputEvent(VoiceEvent):
    """Audio output chunk from provider (24kHz 16-bit PCM)."""

    data: bytes
    type: str = "audio"


@dataclass(kw_only=True)
class TextOutputEvent(VoiceEvent):
    """Partial or complete text transcript from provider."""

    text: str
    is_final: bool = False
    type: str = "text"


@dataclass(kw_only=True)
class InterruptionEvent(VoiceEvent):
    """Event signaling server detected user interruption (barge-in)."""

    type: str = "interrupted"


@dataclass(kw_only=True)
class ToolCallEvent(VoiceEvent):
    """Event requesting Elina tool execution."""

    call_id: str
    name: str
    args: Dict[str, Any]
    type: str = "tool_call"


@dataclass(kw_only=True)
class TurnCompleteEvent(VoiceEvent):
    """Event signaling assistant turn completion."""

    type: str = "turn_complete"


@dataclass(kw_only=True)
class ErrorEvent(VoiceEvent):
    """Error event from voice provider."""

    message: str
    type: str = "error"


class VoiceProvider(abc.ABC):
    """
    Abstract interface for real-time voice providers.
    Every provider (Gemini Live, OpenAI Realtime, Azure, etc.) implements this interface.
    """

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish WebSocket / bi-directional stream with provider."""
        pass

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from provider."""
        pass

    @abc.abstractmethod
    async def send_audio_chunk(self, pcm_data: bytes) -> None:
        """Send raw 16kHz 16-bit PCM audio chunk to provider."""
        pass

    @abc.abstractmethod
    async def send_text(self, text: str) -> None:
        """Send text input to provider."""
        pass

    @abc.abstractmethod
    async def send_tool_response(self, call_id: str, name: str, response: Dict[str, Any]) -> None:
        """Send result of an Elina tool execution back to provider."""
        pass

    @abc.abstractmethod
    def receive_events(self) -> AsyncGenerator[VoiceEvent, None]:
        """Stream incoming voice events from provider."""
        pass

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Check if provider connection is active."""
        pass
