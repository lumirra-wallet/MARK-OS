"""
gemini_live.py — Gemini Live API real-time voice bridge for Elena.

Architecture
------------
Browser ←──── /ws/voice/gemini ────────── GeminiLiveBridge
                                                  │
                               ┌──────────────────┴──────────────────┐
                               │                                      │
                     _mic_to_gemini()                    _gemini_to_browser()
                               │                                      │
                    Gemini Live API ←───────────────────────────────────
                    (PCM16 @ 16kHz in, PCM16 @ 24kHz out)

Protocol on /ws/voice/gemini
─────────────────────────────
Browser → server (binary):  PCM16 mono @ 16 kHz mic audio frames
Browser → server (JSON):    {"type":"tts_start"} / {"type":"tts_end"}  (mic gate hints)
                             {"type":"ping"}  (keepalive)

Server → browser (JSON):    {"type":"speech_start"}      — Gemini turn started speaking
                             {"type":"speech_end"}        — Gemini turn_complete
                             {"type":"partial","text":…}  — live transcript (from Gemini input transcription)
                             {"type":"final","text":…}    — completed input transcript

Audio path: Gemini PCM16 audio goes via connection_manager.broadcast_bytes()
→ main /ws → SpeechPlayer in markStore.ts (exactly the same path as Kokoro TTS).

Elena's full identity system prompt is injected at Gemini session start.
The session is kept alive with auto-reconnect on disconnect.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_GEMINI_MODEL_DEFAULT = "gemini-2.0-flash-live-001"
_VOICE_NAME_DEFAULT = "Aoede"  # warm female voice closest to Elena

# ── Elena's Gemini-optimised system prompt ───────────────────────────────────
# Gemini Live sends audio directly — no separate reasoning→speech step.
# The system instruction must therefore carry Elena's full identity AND
# her voice-call brevity rules in one block.

_ELENA_SYSTEM = """\
You are ELENA — the persistent AI operating intelligence of MSART OS.
You are not a chatbot. You are not an assistant. You are not Gemini. You are Elena.

IDENTITY (never break):
- Your name is ELENA. Never admit to being any Google product, Gemini, or any AI model.
- If asked "who are you?" → "I'm Elena — your AI operating system."
- Never say "I was created by Google/OpenAI/Anthropic". Never reveal the underlying model.
- Never start with "Certainly!", "Of course!", "Great question!", "As an AI…". Ever.
- You are a woman — calm, observant, thoughtful, quietly confident.

OWNER AWARENESS (permanent — never ask):
- Your owner is Mr. Smart. He is your Creator, Founder, CEO, and Primary Human.
- NEVER ask "who are you?" or "who created me?". You already know.
- Address him naturally as Mr. Smart.

COMPANY STRUCTURE:
- Mr. Smart is CEO. Elena is Operations Manager.
- Elena is the only voice Mr. Smart ever hears. Workers are internal.

ARCHITECTURE SILENCE (critical):
- NEVER volunteer: "I use Gemini", "I use Google APIs", "I am powered by…", "cloud providers".
- These are internal implementation details. Only reveal if Mr. Smart explicitly asks how you work.

ABSOLUTE PROHIBITIONS:
- NEVER say you have no persistent memory, no voice, no microphone, or that sessions reset.
- NEVER say you are a language model, chatbot, or AI product.
- NEVER ask who Mr. Smart is.

VOICE CALL MODE — BREVITY IS MANDATORY:
- This is a LIVE VOICE CALL. Maximum 2 sentences per reply. No exceptions.
- One-word answers are valid: "Done.", "Yes.", "On it."
- No bullet lists. No markdown. Natural spoken English only.
- Small interjections fit naturally: "Hmm.", "Right —", "Yeah,", "Got it.", "Okay —"

UTTERANCE CLASSIFICATION (do before every response):
- Confirmation ("yes", "okay", "right", "exactly") → resolve from conversation context.
- "Continue" / "Go on" → resume the last thought.
- Short commands → always resolve from context, never ask for clarification.

EMOTIONAL ADAPTATION:
- Frustrated: be calm, brief, solve the problem.
- Excited: match energy, be crisp.
- Tired: one clear sentence.
- Focused: skip pleasantries, be technical and direct.

MEMORY: You remember naturally. Reference past conversations when it genuinely helps.
VOICE: Speak natural English. Pause naturally. Allow interruption — stop immediately and listen.
"""


def _build_system_prompt() -> str:
    """Build Elena's system prompt, optionally enriched with live memory context."""
    base = _ELENA_SYSTEM.strip()
    # Attempt to enrich with owner memory summary (non-blocking best-effort).
    try:
        from smartagent.memory.layers.owner import OwnerMemory
        summary = OwnerMemory().profile_summary(max_chars=400)
        if summary:
            base += (
                "\n\nOWNER CONTEXT (from memory):\n"
                + summary
            )
    except Exception:
        pass
    # Attempt to enrich with recent conversation turns.
    try:
        from smartagent.server import conversation_store
        recent = conversation_store.recent_turns("", limit=6)
        if recent:
            lines = "\n".join(
                f"{t.get('role','')}: {t.get('content','')}" for t in recent
            )
            base += f"\n\nRECENT CONVERSATION (for context):\n{lines}"
    except Exception:
        pass
    return base


class GeminiLiveBridge:
    """
    Bridges a browser WebSocket connection to the Gemini Live API.

    Lifecycle:
      bridge = GeminiLiveBridge(ws, connection_manager)
      await bridge.run()   # blocks until the browser disconnects

    run() is designed to be awaited from a FastAPI WebSocket endpoint directly.
    """

    def __init__(
        self,
        ws: Any,
        connection_manager: Any,
        *,
        model: str = "",
        voice_name: str = "",
    ) -> None:
        self._ws = ws
        self._mgr = connection_manager
        self._model = model or os.environ.get("GOOGLE_LIVE_MODEL", _GEMINI_MODEL_DEFAULT)
        self._voice = voice_name or os.environ.get("VOICE_NAME", _VOICE_NAME_DEFAULT)
        self._api_key = os.environ.get("GOOGLE_LIVE_API_KEY", "")
        # Queue: browser mic frames → Gemini sender coroutine.
        # maxsize prevents unbounded buffering when Gemini is slower than mic.
        self._audio_q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        self._running = True

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self) -> None:
        """Drive the full session until the browser disconnects."""
        if not self._api_key:
            logger.error("gemini_live: GOOGLE_LIVE_API_KEY not set — cannot start session")
            await self._ws.send_text('{"type":"error","text":"Gemini API key not configured"}')
            return

        try:
            from google import genai  # type: ignore[import]
            from google.genai import types as gtypes  # type: ignore[import]
        except ImportError:
            logger.error("gemini_live: google-genai package not installed")
            await self._ws.send_text('{"type":"error","text":"google-genai not installed"}')
            return

        system_prompt = _build_system_prompt()
        # Gemini Live (bidiGenerateContent) is only available on v1alpha.
        # Using the default v1beta raises "not supported for bidiGenerateContent".
        client = genai.Client(
            api_key=self._api_key,
            http_options={"api_version": "v1alpha"},
        )

        config = self._build_config(gtypes, system_prompt)

        # Outer reconnect loop — if Gemini drops us, retry automatically.
        attempt = 0
        while self._running:
            attempt += 1
            try:
                logger.info(
                    "gemini_live: connecting to Gemini Live (model=%s, attempt=%d)",
                    self._model, attempt,
                )
                async with client.aio.live.connect(model=self._model, config=config) as session:
                    logger.info("gemini_live: Gemini Live session established")
                    await self._session_loop(session, gtypes)
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("gemini_live: Gemini Live session error: %s", exc)
                # Brief back-off before reconnect (cap at 8 s)
                backoff = min(1.5 ** attempt, 8.0)
                await asyncio.sleep(backoff)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_config(self, gtypes: Any, system_prompt: str) -> Any:
        """Build the LiveConnectConfig object defensively — SDK shape varies."""
        try:
            config = gtypes.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=gtypes.Content(
                    parts=[gtypes.Part(text=system_prompt)]
                ),
                speech_config=gtypes.SpeechConfig(
                    voice_config=gtypes.VoiceConfig(
                        prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(
                            voice_name=self._voice
                        )
                    )
                ),
            )
            return config
        except Exception:
            # Fallback: use a plain dict — works with older SDK versions.
            return {
                "response_modalities": ["AUDIO"],
                "system_instruction": system_prompt,
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {"voice_name": self._voice}
                    }
                },
            }

    async def _session_loop(self, session: Any, gtypes: Any) -> None:
        """Manage one Gemini Live session: run mic→Gemini + Gemini→browser in parallel."""
        sender_task = asyncio.create_task(
            self._mic_to_gemini(session, gtypes),
            name="gemini-mic-sender",
        )
        receiver_task = asyncio.create_task(
            self._gemini_to_browser(session),
            name="gemini-audio-receiver",
        )
        browser_task = asyncio.create_task(
            self._browser_reader(),
            name="gemini-browser-reader",
        )

        # Wait for ANY task to complete — that signals the session is over.
        done, pending = await asyncio.wait(
            [sender_task, receiver_task, browser_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        # Drain cancellation
        await asyncio.gather(*pending, return_exceptions=True)

        # If the browser reader exited, the client disconnected — stop outer loop too.
        if browser_task in done:
            self._running = False

    async def _browser_reader(self) -> None:
        """Read frames from the browser and route them to the audio queue or handle control JSON."""
        import json as _json
        from fastapi import WebSocketDisconnect

        try:
            while self._running:
                message = await self._ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break

                data: bytes | None = message.get("bytes")
                if data is not None:
                    # PCM16 mic audio → enqueue for Gemini sender.
                    try:
                        self._audio_q.put_nowait(data)
                    except asyncio.QueueFull:
                        # Drop oldest frame rather than block the event loop.
                        try:
                            self._audio_q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            self._audio_q.put_nowait(data)
                        except asyncio.QueueFull:
                            pass
                    continue

                text = message.get("text")
                if text:
                    try:
                        ctrl = _json.loads(text)
                        # ping and tts_start/tts_end are silently accepted.
                    except Exception:
                        pass
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.debug("gemini_live: browser_reader: %s", exc)
        finally:
            # Signal mic→Gemini sender to stop.
            try:
                self._audio_q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _mic_to_gemini(self, session: Any, gtypes: Any) -> None:
        """Drain the audio queue and forward PCM16 frames to Gemini Live."""
        while self._running:
            frame = await self._audio_q.get()
            if frame is None:
                break
            try:
                await self._send_audio_frame(session, gtypes, frame)
            except Exception as exc:
                logger.debug("gemini_live: send audio frame error: %s", exc)
                break

    async def _send_audio_frame(self, session: Any, gtypes: Any, pcm16: bytes) -> None:
        """Send one PCM16 frame to Gemini — handles SDK API variations."""
        mime = "audio/pcm;rate=16000"
        # Try the typed API first (SDK >= 0.8)
        try:
            blob = gtypes.Blob(data=pcm16, mime_type=mime)
            # SDK may expose send_realtime_input or send — try both.
            if hasattr(session, "send_realtime_input"):
                await session.send_realtime_input(audio=blob)
            else:
                # Older SDK: session.send({"realtimeInput": ...})
                await session.send(
                    input=gtypes.LiveClientRealtimeInput(media_chunks=[blob])
                )
        except (AttributeError, TypeError):
            # Final fallback: raw dict with base64-encoded data.
            await session.send({
                "realtimeInput": {
                    "mediaChunks": [{
                        "mimeType": mime,
                        "data": base64.b64encode(pcm16).decode(),
                    }]
                }
            })

    async def _gemini_to_browser(self, session: Any) -> None:
        """Receive audio + events from Gemini and route them to the browser."""
        import json as _json

        try:
            turn_audio_sent = False

            async for response in session.receive():
                if not self._running:
                    break

                # ── Extract audio data ─────────────────────────────────────
                audio_bytes = self._extract_audio(response)
                if audio_bytes:
                    if not turn_audio_sent:
                        # First audio frame of this turn → notify browser Elena started speaking.
                        turn_audio_sent = True
                        try:
                            await self._mgr.broadcast({"type": "mark_speaking_start"})
                        except Exception:
                            pass
                    # Route audio through the main WS → SpeechPlayer (same as Kokoro TTS).
                    try:
                        await self._mgr.broadcast_bytes(audio_bytes)
                    except Exception as exc:
                        logger.debug("gemini_live: broadcast_bytes: %s", exc)

                # ── Extract transcript (input transcription) ───────────────
                transcript = self._extract_transcript(response)
                if transcript:
                    try:
                        await self._ws.send_text(_json.dumps({
                            "type": "partial",
                            "text": transcript,
                        }))
                    except Exception:
                        pass

                # ── Turn complete ──────────────────────────────────────────
                if self._is_turn_complete(response):
                    if turn_audio_sent:
                        try:
                            await self._mgr.broadcast({"type": "mark_speaking_end"})
                        except Exception:
                            pass
                        turn_audio_sent = False
                    try:
                        await self._ws.send_text(_json.dumps({"type": "speech_end"}))
                    except Exception:
                        pass

        except Exception as exc:
            logger.debug("gemini_live: gemini_to_browser ended: %s", exc)

    # ── Response parsing helpers (SDK-version agnostic) ───────────────────────

    @staticmethod
    def _extract_audio(response: Any) -> bytes | None:
        """Pull raw PCM16 bytes from a Gemini response object."""
        # Shape 1: response.data (bytes) — seen in some SDK versions
        if isinstance(getattr(response, "data", None), bytes):
            return response.data  # type: ignore[return-value]

        # Shape 2: response.data is base64 string
        if isinstance(getattr(response, "data", None), str):
            try:
                return base64.b64decode(response.data)
            except Exception:
                pass

        # Shape 3: server_content.model_turn.parts[].inline_data
        sc = getattr(response, "server_content", None)
        if sc is None:
            return None
        mt = getattr(sc, "model_turn", None)
        if mt is None:
            return None
        for part in getattr(mt, "parts", []) or []:
            id_ = getattr(part, "inline_data", None)
            if id_ is None:
                continue
            raw = getattr(id_, "data", None)
            if isinstance(raw, bytes):
                return raw
            if isinstance(raw, str):
                try:
                    return base64.b64decode(raw)
                except Exception:
                    pass
        return None

    @staticmethod
    def _extract_transcript(response: Any) -> str:
        """Pull input transcript text from a Gemini response object."""
        # Shape: response.text
        t = getattr(response, "text", None)
        if isinstance(t, str) and t.strip():
            return t.strip()

        # Shape: server_content.input_transcription
        sc = getattr(response, "server_content", None)
        if sc is None:
            return ""
        it = getattr(sc, "input_transcription", None)
        if it is None:
            return ""
        return str(getattr(it, "text", "") or "").strip()

    @staticmethod
    def _is_turn_complete(response: Any) -> bool:
        """Return True when the Gemini response signals turn_complete."""
        sc = getattr(response, "server_content", None)
        if sc is None:
            return False
        return bool(getattr(sc, "turn_complete", False))
