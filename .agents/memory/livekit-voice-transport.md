---
name: LiveKit Voice Transport — current architecture
description: LiveKit runs for room presence/coordination only. Audio transport uses the original WebSocket + ScriptProcessorNode + binary-frame TTS pipeline. Voice chat uses a fast /voice/message endpoint instead of /execute.
---

# LiveKit + Voice Pipeline — Current Architecture

## Audio Transport (UNCHANGED from original)

```
Browser mic (getUserMedia + ScriptProcessorNode)
  → resampleTo16k + floatTo16BitPCM
  → binary WebSocket frames → /ws/voice (api.py)
  → VoiceSession: Silero VAD → faster-whisper STT
  → speech_start / partial / final JSON events back to browser

Final transcript
  → browser POSTs to POST /voice/message (fast path, returns 202)
  → server: _voice_chat_response() — direct LLM + speech_runtime TTS
  → Kokoro TTS PCM binary frames on /ws (main WebSocket)
  → SpeechPlayer (AudioContext, 24kHz) plays audio
```

## LiveKit (presence/coordination ONLY — no audio)

```
livekit_agent.py connects to 'mark-presence' room
  → tracks participant join/leave
  → data channel available for session state broadcast
  → does NOT publish audio tracks
  → does NOT subscribe to audio tracks
```

## Why LiveKit Was Repositioned

The LiveKit Python SDK (v1.x) has incompatible API changes: `RoomEvent` enum removed, `wait_until_disconnected()` removed, audio publish/subscribe API changed. More importantly, the original goal was correct: LiveKit coordinates real-time sessions; it should not replace the working VAD+STT+TTS WebSocket pipeline.

## Key Files

**Backend:**
- `smartagent/server/api.py` — `_voice_chat_response()` helper + `@router.websocket("/ws/voice")` restored + `@router.post("/voice/message")` new fast endpoint
- `smartagent/server/livekit_agent.py` — presence-only agent (no audio publish/subscribe), uses string event names (`"disconnected"` not `rtc.RoomEvent.Disconnected`)
- `smartagent/server/speech_runtime.py` — `attach_livekit` / `enqueue_audio` removed; audio goes via `_broadcast_bytes` (binary WS frames) only
- `smartagent/server/app.py` — lifespan calls `livekit_agent.start()` only (no `attach_livekit`)
- `smartagent/server/mark_supervisor.py` — entry point (not watchdog); kills stale port 18949, starts LiveKit, waits healthcheck, starts uvicorn

**Frontend:**
- `artifacts/mark-dashboard/src/hooks/use-voice.ts` — WebSocket + ScriptProcessorNode (restored); `final` transcript → `sendVoiceMessage` (not `sendUserMessage`)
- `artifacts/mark-dashboard/src/store/markStore.ts` — `SpeechPlayer` + binary-frame handler restored; `sendVoiceMessage` action added (POSTs to `/voice/message`)

## Key Decisions

**Fast voice path:** `POST /voice/message` → `_voice_chat_response()` forces the conversational LLM path (skips SmartAgent planning/workers). Returns 202 immediately; response streams back via /ws events. First audio in 1-3 s vs minutes for /execute.

**_voice_chat_response race handling:** waits up to 3 s for `_state.running` to clear (speech_start will have already cancelled the inference task).

**LiveKit SDK string event names:** `room.on("disconnected", ...)` not `room.on(rtc.RoomEvent.Disconnected, ...)` — the RoomEvent enum was removed in v1.x.

**SpeechPlayer at 24000Hz:** `new SpeechPlayer(24000, callback)` — Kokoro TTS native rate.

**livekit-client** still installed in the frontend package.json. The frontend uses it for `/voice/config` and `/voice/token` fetches but routes NO audio through LiveKit — all audio goes via the WebSocket. The LiveKit room join is currently not done from the frontend (use-voice.ts uses WebSocket only).

## How to Apply

- Voice works without LiveKit secrets — the /ws/voice + /ws pipeline is self-contained.
- LiveKit presence activates when LIVEKIT_API_KEY + LIVEKIT_API_SECRET are set.
- `mark_supervisor.py` is the entry point; do NOT use `watchdog` or `app.py` directly.
- Secrets: LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL (ws://localhost:7880 default).
