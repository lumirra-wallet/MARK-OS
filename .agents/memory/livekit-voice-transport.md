---
name: LiveKit Voice Transport (M0–M6)
description: Full LiveKit self-hosted WebRTC voice transport implementation replacing the old /ws/voice WebSocket + ScriptProcessorNode path.
---

# LiveKit Voice Transport — M0 through M6 Complete

## What Was Built

Replaced MARK's browser WebSocket voice transport (`/ws/voice` + `ScriptProcessorNode`) with
self-hosted LiveKit (Go binary, open-source) for tab-background resilience, automatic
reconnection, and clean echo cancellation via `localTrack.mute()`.

## Architecture

```
Browser (livekit-client)
  ↔  /livekit-rtc WS proxy on MARK API (api.py)
  ↔  LiveKit binary :7880  (started by mark_supervisor.py)
  ↔  MarkLiveKitAgent (livekit_agent.py) — subscribes to room, bridges audio
  ↔  speech_runtime.py  (VAD→STT on inbound, TTS PCM on outbound)
```

## Files Written/Modified

**New backend files:**
- `smartagent/server/livekit_process.py` — downloads/caches binary (v1.13.4 default), generates config.yaml, `LiveKitProcess.start/stop/is_running`
- `smartagent/server/livekit_setup.py` — one-time key generation helper
- `smartagent/server/livekit_token.py` — JWT token creation (pyjwt HS256), `create_browser_token`, `create_agent_token`, `livekit_configured()`
- `smartagent/server/mark_supervisor.py` — two-process supervisor: kills stale port 18949, starts LiveKit, waits for healthcheck, starts uvicorn
- `smartagent/server/livekit_agent.py` — `MarkLiveKitAgent` class: per-participant VoiceSession, PCM queue→capture_frame, barge-in interrupt, echo gate
- `docs/livekit-voice-roadmap.md` — full 6-milestone roadmap

**Modified backend files:**
- `smartagent/server/speech_runtime.py` — added `_livekit_agent` field, `attach_livekit(agent)`, calls `livekit_agent.enqueue_audio(pcm)` after `_broadcast_bytes`
- `smartagent/server/app.py` — lifespan: `await livekit_agent.start()` + `speech_runtime.attach_livekit(livekit_agent)`
- `smartagent/server/api.py` — removed `voice_websocket`; added `GET /voice/token`, `GET /voice/config`, `WebSocket /livekit-rtc` (signaling proxy)
- `requirements.minimal.txt` — added `livekit`, `livekit-api`
- `artifacts/mark-api/package.json` — dev script now runs `mark_supervisor` (not `watchdog`)

**New/modified frontend files:**
- `artifacts/mark-dashboard/src/hooks/use-voice.ts` — full rewrite: Room SDK, `createLocalAudioTrack`, data channel for control messages, `localTrack.mute()` echo gate, AnalyserNode mic level, browser-TTS emergency fallback preserved
- `artifacts/mark-dashboard/src/hooks/use-livekit-config.ts` — new hook: fetches `/voice/config`, uses `serverUrl` from store
- `artifacts/mark-dashboard/src/store/markStore.ts` — removed binary-frame handler + `SpeechPlayer` import; `SpeechStart` → `set({ isMarkSpeaking: true })`; `SpeechEnd` → `set({ isMarkSpeaking: false })`; `stopMarkSpeech` simplified (no speechPlayer)
- `artifacts/mark-dashboard/package.json` — added `livekit-client: ^2.9.0`

## Key Decisions

**Why:**
- `mark_supervisor.py` kills stale port 18949 before starting — ends the watchdog restart loop
- LiveKit binary URL format: `livekit_{version}_linux_amd64.tar.gz` for v1.8+, no version prefix for older
- `/livekit-rtc` WebSocket proxy (not `/livekit/rtc` with slash) — avoids Vite path conflicts
- `localTrack.mute()` for echo gate — works in background tabs (ScriptProcessorNode stops)
- SpeechPlayer completely removed — with LiveKit, audio plays via WebRTC `<audio>` element, not PCM frames on /ws

**How to apply:**
- LiveKit runs only if `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` are set (run `python -m smartagent.server.livekit_setup` to generate)
- Self-hosted default: `LIVEKIT_URL=ws://localhost:7880`; cloud: `LIVEKIT_URL=wss://xxx.livekit.cloud`
- Set `LIVEKIT_BROWSER_URL` to override what the browser connects to (useful for custom domains)
- `API_BASE_URL` env var is used to auto-derive the browser-facing signaling URL: `wss://{API_BASE_URL}/livekit-rtc`
