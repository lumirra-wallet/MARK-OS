"""
Gemini Live voice provider — real-time bidirectional audio via Google's
Live API, implemented on the official `google-genai` SDK.

Role (per the owner's architecture decision, 2026-08-04):
    Gemini Live is ONLY the voice transport layer — microphone understanding,
    low-latency conversational flow, barge-in, and speech synthesis. It does
    NOT own reasoning, memory, tools, or personality. Anything substantive is
    delegated to MARK via function-calling (see smartagent/brain/elina_bridge
    and smartagent/server/gemini_voice). Gemini may answer trivial
    acknowledgements itself for responsiveness; everything else → MARK.

Swappability:
    This class implements the VoiceProvider interface (abstract_provider.py),
    so Gemini can later be replaced by OpenAI Realtime / Azure / a local
    provider by swapping only this file — nothing above it changes.

Audio contract:
    * input  : raw PCM16 mono @ 16 kHz  (what the browser mic sends)
    * output : raw PCM16 mono @ 24 kHz  (what the browser SpeechPlayer plays)

Config (all from env — no hardcoded secrets):
    GOGLE_LIVE / GOOGLE_LIVE / GEMINI_API_KEY   API key or ephemeral token
    GEMINI_LIVE_MODEL     default gemini-2.5-flash-native-audio-preview-09-2025
    GEMINI_LIVE_API_VER   default v1alpha
    GEMINI_VOICE_NAME     default Zephyr
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

from smartagent.voice.providers.abstract_provider import (
    VoiceProvider, VoiceEvent, AudioOutputEvent, TextOutputEvent,
    InterruptionEvent, ToolCallEvent, TurnCompleteEvent, ErrorEvent,
)

logger = logging.getLogger("smartagent.voice.gemini")

# Verified working against this account (2026-08-04): v1alpha + the native
# audio model streams real 24 kHz audio back. Overridable via env so a newer
# model/version can be adopted without a code change.
_DEFAULT_MODEL = os.environ.get(
    "GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-09-2025"
)
_DEFAULT_API_VERSION = os.environ.get("GEMINI_LIVE_API_VER", "v1alpha")
_DEFAULT_VOICE = os.environ.get("GEMINI_VOICE_NAME", "Zephyr")


def gemini_api_key() -> str | None:
    """The Gemini credential, from any of the accepted env var names.

    GOGLE_LIVE is the owner's (misspelled) variable; GOOGLE_LIVE and
    GEMINI_API_KEY are also accepted. May be a long-lived AI Studio key
    (starts 'AIza') or a short-lived ephemeral token (starts 'AQ.').
    """
    return (
        os.environ.get("GOGLE_LIVE")
        or os.environ.get("GOOGLE_LIVE")
        or os.environ.get("GEMINI_API_KEY")
        or None
    )


def gemini_configured() -> bool:
    return bool(gemini_api_key())


class GeminiLiveProvider(VoiceProvider):
    """VoiceProvider backed by Gemini Live (google-genai SDK)."""

    def __init__(
        self,
        *,
        system_instruction: str = "",
        tool_declarations: Optional[List[Dict[str, Any]]] = None,
        model: str = _DEFAULT_MODEL,
        voice_name: str = _DEFAULT_VOICE,
        api_version: str = _DEFAULT_API_VERSION,
    ) -> None:
        self._model = model
        self._voice = voice_name
        self._api_version = api_version
        self._system_instruction = system_instruction
        self._tools = tool_declarations or []

        self._client: Any = None
        self._session: Any = None
        self._cm: Any = None                    # the live-connect context manager
        self._events: "asyncio.Queue[VoiceEvent]" = asyncio.Queue()
        self._connected = False

    # ── connection ──────────────────────────────────────────────────────────

    async def connect(self) -> None:
        from google import genai
        from google.genai import types

        key = gemini_api_key()
        if not key:
            raise RuntimeError(
                "No Gemini key — set GOGLE_LIVE (or GOOGLE_LIVE / GEMINI_API_KEY)."
            )

        self._client = genai.Client(
            api_key=key, http_options={"api_version": self._api_version}
        )

        config: Dict[str, Any] = {
            "response_modalities": ["AUDIO"],
            # Gemini transcribes both sides so MARK can log/store them and the
            # dashboard can display them — transcript is for record only.
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._voice
                    )
                )
            ),
        }
        if self._system_instruction:
            config["system_instruction"] = self._system_instruction
        if self._tools:
            config["tools"] = [{"function_declarations": self._tools}]

        # Enter the async context manager and keep it open for the session life.
        self._cm = self._client.aio.live.connect(model=self._model, config=config)
        self._session = await self._cm.__aenter__()
        self._connected = True
        logger.info(
            "gemini: connected (model=%s, voice=%s, api=%s)",
            self._model, self._voice, self._api_version,
        )
        asyncio.create_task(self._receive_loop())

    async def disconnect(self) -> None:
        self._connected = False
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                pass
        self._cm = None
        self._session = None
        logger.info("gemini: disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    # ── send ────────────────────────────────────────────────────────────────

    async def send_audio_chunk(self, pcm_data: bytes) -> None:
        """Stream one PCM16 @ 16 kHz mic chunk to Gemini."""
        if not self.is_connected:
            return
        try:
            from google.genai import types
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm_data, mime_type="audio/pcm;rate=16000")
            )
        except Exception as exc:
            logger.debug("gemini: send_audio failed: %s", exc)
            self._connected = False

    async def send_text(self, text: str) -> None:
        if not self.is_connected:
            return
        from google.genai import types
        await self._session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]),
            turn_complete=True,
        )

    async def send_tool_response(
        self, call_id: str, name: str, response: Dict[str, Any]
    ) -> None:
        """Return a MARK tool result to Gemini so it can speak the answer."""
        if not self.is_connected:
            return
        from google.genai import types
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(id=call_id, name=name, response=response)
            ]
        )

    # ── receive ─────────────────────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """Translate raw Gemini messages into our provider-neutral VoiceEvents."""
        try:
            while self._connected and self._session is not None:
                async for msg in self._session.receive():
                    await self._translate(msg)
        except Exception as exc:
            logger.warning("gemini: receive loop ended: %s", exc)
            self._connected = False
            await self._events.put(ErrorEvent(message=str(exc)))

    async def _translate(self, msg: Any) -> None:
        # Tool calls → ToolCallEvent (dispatched to MARK by the bridge)
        tc = getattr(msg, "tool_call", None)
        if tc and getattr(tc, "function_calls", None):
            for fc in tc.function_calls:
                await self._events.put(ToolCallEvent(
                    call_id=getattr(fc, "id", "") or "",
                    name=getattr(fc, "name", "") or "",
                    args=dict(getattr(fc, "args", {}) or {}),
                ))
            return

        sc = getattr(msg, "server_content", None)
        if not sc:
            return

        # Barge-in: Gemini detected the user speaking over MARK.
        if getattr(sc, "interrupted", None):
            await self._events.put(InterruptionEvent())

        # Output audio + output transcript
        mt = getattr(sc, "model_turn", None)
        if mt and getattr(mt, "parts", None):
            for p in mt.parts:
                inline = getattr(p, "inline_data", None)
                if inline and inline.data:
                    await self._events.put(AudioOutputEvent(data=inline.data))
                if getattr(p, "text", None):
                    await self._events.put(TextOutputEvent(text=p.text, is_final=False))

        out_tx = getattr(sc, "output_transcription", None)
        if out_tx and getattr(out_tx, "text", None):
            await self._events.put(TextOutputEvent(text=out_tx.text, is_final=False))

        # Input transcript (what the user said) — tagged is_final for logging.
        in_tx = getattr(sc, "input_transcription", None)
        if in_tx and getattr(in_tx, "text", None):
            await self._events.put(TextOutputEvent(text=in_tx.text, is_final=True))

        if getattr(sc, "turn_complete", None):
            await self._events.put(TurnCompleteEvent())

    async def receive_events(self) -> AsyncGenerator[VoiceEvent, None]:
        while True:
            event = await self._events.get()
            yield event
