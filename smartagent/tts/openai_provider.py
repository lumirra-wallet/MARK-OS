"""OpenAIProvider — wraps the OpenAI tts-1-hd API, mirroring the logic already
used by the existing ``/voice/speak-openai`` endpoint in ``api.py``."""

from __future__ import annotations

import os

VALID_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
DEFAULT_VOICE = "nova"


class OpenAIProvider:
    @property
    def available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())

    def synthesize(self, text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
        if not self.available:
            raise RuntimeError("OPENAI_API_KEY not configured")
        voice = voice if voice in VALID_VOICES else DEFAULT_VOICE
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.audio.speech.create(
            model="tts-1-hd", voice=voice, input=text, response_format="mp3",
        )
        return response.content

    def list_voices(self) -> list[str]:
        return list(VALID_VOICES)
