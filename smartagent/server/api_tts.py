"""
TTS Provider API — Kokoro (default) / Piper / OpenAI / Browser.

New endpoints, additive only — the existing ``/voice/*`` endpoints in
``api.py`` (Piper-via-sounddevice, OpenAI-via-``/voice/speak-openai``) are
untouched for backward compatibility. This router is what the simplified
Narration panel (Voice Provider / Voice Selection / Speaking Status / Volume
/ Mute) actually talks to, and what ``DevPipeline``'s executive-summary
narration (see ``smartagent/server/events.py``'s ``NARRATION`` event) is
meant to be spoken through.

Endpoints
---------
GET  /tts/status     — availability of every provider + the active one
POST /tts/provider   — switch the active provider
GET  /tts/voices     — voice catalogue for a provider (defaults to active)
POST /tts/speak      — synthesize text via the active provider, returns audio bytes
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from smartagent.tts import factory

router = APIRouter()

_MEDIA_TYPES = {
    "kokoro": "audio/wav",
    "piper":  "audio/wav",
    "openai": "audio/mpeg",
}


@router.get("/tts/status")
async def tts_status() -> dict:
    return {
        "active":     factory.get_active_provider_name(),
        "providers":  factory.provider_status(),
    }


class SwitchProviderRequest(BaseModel):
    provider: str


@router.post("/tts/provider")
async def tts_switch_provider(req: SwitchProviderRequest) -> dict:
    try:
        provider = factory.switch_provider(req.provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "provider": provider}


@router.get("/tts/voices")
async def tts_voices(provider: str | None = None) -> dict:
    return {"voices": factory.list_voices(provider)}


class SpeakRequest(BaseModel):
    text:  str
    voice: str | None = None
    speed: float = 1.0


@router.post("/tts/speak")
async def tts_speak(req: SpeakRequest) -> Response:
    """
    Synthesize ``req.text`` via the active provider and return audio bytes.

    503 when the active provider is unavailable (not configured, missing
    model files, no API key, or explicitly set to "browser") — the frontend
    catches this and falls back to ``window.speechSynthesis``, matching
    "Kokoro is the default provider, with browser TTS available only as a
    fallback."
    """
    active = factory.get_active_provider_name()
    try:
        audio = await asyncio.to_thread(factory.synthesize, req.text, req.voice, req.speed)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(
        content=audio,
        media_type=_MEDIA_TYPES.get(active, "audio/wav"),
        headers={"Cache-Control": "no-cache"},
    )
