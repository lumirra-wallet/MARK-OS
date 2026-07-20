---
name: MARK Web LLM Routing & Provider Bugs
description: Fixes for GitHub provider auth failures, self-message feedback loop, voice WebSocket crash, and single-server consolidation.
---

## GitHub provider auth failure → Ollama fallback

**Rule:** `_load_github()` in `factory.py` now registers Ollama as a silent fallback (via `model_manager.set_fallback(ollama_model, is_failure=is_llm_error_text)`). When GitHub returns Unauthorized, ModelManager automatically retries on Ollama — no user intervention needed.

**Why:** `ACTIVE_PROVIDER=github` was hardcoded in Replit Secrets. The token expired. The old `_load_github()` registered no fallback, so every chat call failed completely. Mirrored the same pattern that `_load_ollama()` uses for NVIDIA as a fallback.

**How to apply:** The fallback registers automatically on server startup whenever OLLAMA_HOST is set. To force a switch to GitHub-primary again, update the Replit Secret `ACTIVE_PROVIDER=github` AND ensure GITHUB_TOKEN is valid.

## Provider auto-detect priority order

Changed `_auto_default_provider()` to prefer Ollama when `OLLAMA_HOST` is set:
1. ACTIVE_PROVIDER env var (explicit override — still respected)
2. OLLAMA_HOST present → "ollama" (local-first, no auth to expire)
3. NVIDIA_API_KEY → "nvidia"
4. GITHUB_TOKEN → "github"
5. Fallback → "ollama"

**Why:** Cloud API tokens expire. Local Ollama never does.

## Self-message feedback loop guard

**Rule:** `_voice_chat_response()` in `api.py` has a `_LOOP_PHRASES` check at the top. Any incoming voice text that starts with or contains known fallback/self-intro phrases is dropped with a WARNING log.

**Why:** When LLM fails, `CHAT_FALLBACK_TEXT` ("I'm MARK — I plan engineering work...") was published via `STREAMING_TOKEN` → `speech_runtime` TTS'd it → mic picked it up → STT transcribed it → new voice message → infinite loop.

## Fallback messages don't go through TTS

**Rule:** In `_stream_llm_response()`, when the LLM call fails, the fallback is published as `"CHAT_MESSAGE"` event (not `"STREAMING_TOKEN"`). `speech_runtime` only subscribes to `STREAMING_TOKEN`, so the fallback is displayed as a chat bubble but never spoken.

**How to apply:** Frontend `markStore.ts` handles `'ChatMessage'` in the same switch case as `'MarkOpening'` and `'MarkProactive'` — adds it as a mark message with no TTS side effect.

## Voice WebSocket "send after close" crash

In `voice_websocket()`, `ws.send_json(event)` inside the STT event loop is now wrapped in try/except. If the client disconnects mid-frame, the exception is swallowed and the loop exits cleanly on the next `receive()` call (which raises `WebSocketDisconnect`).

**Why:** `voice_websocket: Unexpected ASGI message 'websocket.send', after sending 'websocket.close'` spammed the logs whenever a voice client disconnected while audio events were being processed.

## Single server consolidation

- Added `/api/healthz` compat route to the Python FastAPI server (`app.py`) — absorbs the only useful endpoint from the api-server skeleton (Node.js Express).
- The `artifacts/api-server` workflow is stopped and not needed. All health-check traffic is handled by the Python server.
- `app.py` already serves the built dashboard in combined-server mode (when `artifacts/mark-dashboard/dist/public` exists).

## Stale provider state file

Delete `.mark_provider_state.json` at the repo root if MARK is stuck on a wrong provider after a token update. The file persists the last-used provider across restarts and can override env vars on the second load cycle.
