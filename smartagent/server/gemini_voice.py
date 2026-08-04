"""
gemini_voice.py — bridges the browser's continuous mic stream to Gemini Live
and back, with MARK as the brain behind Gemini's function calls.

Data flow (one bridge per browser voice connection):

    browser mic PCM16@16k  ──►  /ws/voice  ──►  GeminiLiveProvider ──► Gemini
    Gemini audio PCM16@24k ──►  main /ws (binary) ──► browser SpeechPlayer
    Gemini function_call   ──►  ElinaBridge ──► MARK (brain/memory/tools)
                                     └── result ──► Gemini (speaks the answer)

Division of labour (owner's decision, 2026-08-04):
    Gemini  = voice transport only: understanding, turn-taking, barge-in, TTS,
              and trivial conversational acknowledgements.
    MARK    = the mind: all reasoning, memory, knowledge, tools, personality,
              and persistent state — reached exclusively via function calls.

The provider is behind the VoiceProvider interface, so swapping Gemini for
OpenAI Realtime / Azure / a local provider later touches only which provider
class is constructed here.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("smartagent.server.gemini_voice")

# What Gemini is told it is. Keeps it firmly in the "voice, not brain" lane.
_SYSTEM_INSTRUCTION = (
    "You are the live voice of MARK, a persistent AI assistant who belongs to "
    "one owner. Your ONLY job is natural spoken conversation: listen closely, "
    "understand what the owner means even through pauses and restarts, and "
    "speak warmly, briefly, and with real expression.\n\n"
    "You do NOT have your own memory, knowledge, or opinions — MARK does. For "
    "ANYTHING beyond a trivial conversational acknowledgement (a greeting, "
    "'sure', 'one moment', 'got it'), you MUST call a function and never "
    "answer from your own guesses:\n"
    "  • ask_mark(request)      — for any question, request, task, reasoning, "
    "opinion, fact, or action. This is MARK thinking. Use it liberally.\n"
    "  • search_memory(query)   — to recall something about the owner.\n"
    "  • remember(content)      — to save something the owner wants kept.\n\n"
    "Never invent facts about the owner or the world. When a function returns, "
    "speak its answer naturally, as if the thought were your own. If the owner "
    "is unclear, ask one short clarifying question rather than guessing."
)

_TOOL_DECLARATIONS = [
    {
        "name": "ask_mark",
        "description": (
            "Delegate to MARK's brain. Use for ANY question, request, task, "
            "reasoning, opinion, fact lookup, planning, or action — anything "
            "beyond trivial small talk. Returns MARK's answer to speak."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "request": {
                    "type": "STRING",
                    "description": "The owner's request, in plain words.",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "search_memory",
        "description": "Recall facts, preferences, or past details about the owner from MARK's memory.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "What to recall."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "remember",
        "description": "Save an important fact, preference, or note into MARK's persistent memory.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "content": {"type": "STRING", "description": "The information to remember."},
                "category": {"type": "STRING", "description": "Optional category (Personal, Projects, Journal...)."},
            },
            "required": ["content"],
        },
    },
]


class GeminiVoiceBridge:
    """One live Gemini voice session bridged to the browser and to MARK."""

    def __init__(self, connection_manager: Any, loop: asyncio.AbstractEventLoop, agent: Any) -> None:
        self._cm = connection_manager
        self._loop = loop
        self._agent = agent
        self._provider: Any = None
        self._relay_task: "asyncio.Task[None] | None" = None
        self._elina: Any = None
        self._speaking = False

    async def start(self) -> None:
        from smartagent.voice.providers.gemini_live_provider import GeminiLiveProvider
        from smartagent.brain.elina_bridge import ElinaBridge

        # Reuse MARK's already-warmed agent as the brain behind the bridge.
        self._elina = ElinaBridge(agent=self._agent)

        self._provider = GeminiLiveProvider(
            system_instruction=_SYSTEM_INSTRUCTION,
            tool_declarations=_TOOL_DECLARATIONS,
        )
        await self._provider.connect()
        self._relay_task = asyncio.create_task(self._relay_events())
        logger.info("gemini_voice: bridge live")

    async def feed(self, pcm16_16k: bytes) -> None:
        """Forward one browser mic frame to Gemini."""
        if self._provider is not None:
            await self._provider.send_audio_chunk(pcm16_16k)

    async def stop(self) -> None:
        if self._relay_task is not None:
            self._relay_task.cancel()
            self._relay_task = None
        if self._provider is not None:
            await self._provider.disconnect()
            self._provider = None
        logger.info("gemini_voice: bridge stopped")

    # ── event relay: Gemini → browser + tool dispatch → MARK ─────────────────

    async def _relay_events(self) -> None:
        from smartagent.voice.providers.abstract_provider import (
            AudioOutputEvent, TextOutputEvent, InterruptionEvent,
            ToolCallEvent, TurnCompleteEvent, ErrorEvent,
        )
        try:
            async for ev in self._provider.receive_events():
                if isinstance(ev, AudioOutputEvent):
                    if not self._speaking:
                        self._speaking = True
                        await self._broadcast_event("SpeechStart", {})
                    # 24 kHz PCM16 — exactly what the browser SpeechPlayer expects.
                    await self._cm.broadcast_bytes(ev.data)

                elif isinstance(ev, InterruptionEvent):
                    self._speaking = False
                    await self._broadcast_event("SpeechInterrupted", {})

                elif isinstance(ev, TurnCompleteEvent):
                    if self._speaking:
                        self._speaking = False
                        await self._broadcast_event("SpeechEnd", {})

                elif isinstance(ev, TextOutputEvent):
                    # Transcript is for display/logging only, never the source
                    # of truth. is_final=True marks the user's own words.
                    name = "voice_final" if ev.is_final else "voice_partial"
                    await self._broadcast_event(name, {"text": ev.text})

                elif isinstance(ev, ToolCallEvent):
                    asyncio.create_task(self._dispatch_tool(ev))

                elif isinstance(ev, ErrorEvent):
                    logger.warning("gemini_voice: provider error: %s", ev.message)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("gemini_voice: relay ended: %s", exc)

    async def _dispatch_tool(self, ev: Any) -> None:
        """Run a Gemini function call against MARK, off the event loop."""
        name, args = ev.name, ev.args
        logger.info("gemini_voice: tool_call %s(%s)", name, args)
        try:
            if name == "search_memory":
                result = await asyncio.to_thread(
                    self._elina.memory.search, args.get("query", "")
                )
                payload = {"results": result}
            elif name == "remember":
                msg = await asyncio.to_thread(
                    self._elina.memory.store,
                    args.get("content", ""), args.get("category", "Journal"),
                )
                payload = {"status": msg}
            else:  # ask_mark (and any unknown → MARK's brain)
                request = args.get("request") or args.get("query") or str(args)
                answer = await asyncio.to_thread(self._elina.process, request)
                payload = {"answer": answer}
        except Exception as exc:  # noqa: BLE001
            logger.warning("gemini_voice: tool %s failed: %s", name, exc)
            payload = {"error": str(exc)}

        # Surface MARK's real decision to the dashboard (MARK is the mind).
        await self._broadcast_event("MarkToolResult", {"tool": name, "result": payload})
        if self._provider is not None:
            await self._provider.send_tool_response(ev.call_id, name, payload)

    async def _broadcast_event(self, name: str, payload: dict) -> None:
        try:
            await self._cm.broadcast({
                "type": "event",
                "name": name,
                "payload": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
        except Exception:
            pass
