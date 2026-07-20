---
name: Unified server and real-time greeting
description: Architecture decisions made when merging servers and adding streaming TTS to the MARK opening greeting.
---

# Unified server and real-time greeting

## What was already done (don't redo)
- `smartagent/server/app.py` already mounts the built dashboard via StaticFiles at `artifacts/mark-dashboard/dist/public`. Step 1 of server unification was complete before this task.
- `MarkOpening` and `MarkProactive` cases already existed in `markStore.ts` and created chat messages. They just lacked TTS.
- The `/ws` endpoint already sends a 30s keepalive ping (`asyncio.wait_for(receive_text, timeout=30)` → send `{type: "ping"}`).

## Key decisions

### Streaming TTS for the greeting
**Rule:** Feed the opening LLM's tokens through a temporary `EventBus` + `speech_runtime` from inside `asyncio.to_thread`, not after the full response is built.
**Why:** Generates per-sentence audio in parallel with the LLM so MARK starts speaking after the first sentence completes (~3-5s) rather than after the full response (~10-15s).
**How to apply:** Capture `asyncio.get_event_loop()` BEFORE entering `asyncio.to_thread`. Pass the loop to `speech_runtime.attach(connection_manager, loop)` inside the thread. Create a local `EventBus()`, subscribe `speech_runtime.on_token`, publish each chunk to it. Call `speech_runtime.flush()` in a `finally` block. Skip TTS if `_state.running` (another session takes priority) or `EventBus is None` (import failed).

### Event loop capture pattern
**Rule:** Always capture `loop = asyncio.get_event_loop()` in the coroutine scope before calling `asyncio.to_thread`. Inside the thread, `asyncio.get_event_loop()` returns a different/dead loop.
**Why:** `run_coroutine_threadsafe` (used by `speech_runtime._broadcast_bytes`) requires the running event loop, not a thread-local default.

### Reconnect: never give up
**Rule:** Remove `RECONNECT_MAX_ATTEMPTS` check entirely. Reconnect forever with exponential backoff (250ms → 30s).
**Why:** Users want MARK's stats/panels to persist across brief network blips. `api-server` watchdog already keeps the backend alive; the frontend should match that resilience.
**File:** `artifacts/mark-dashboard/src/store/markStore.ts` — `ws.onclose` handler.

### Voice socket backoff
**Rule:** Voice reconnect uses backoff (500ms → 8s) with a `voiceReconnectAttemptsRef` reset to 0 on `onopen`. Never gives up while `enabledRef.current` is true.
**File:** `artifacts/mark-dashboard/src/hooks/use-voice.ts`.

### /healthz alias
Added `GET /healthz` to FastAPI (`smartagent/server/api.py`) returning `{"status": "ok"}` — absorbs the only endpoint the retired Node.js `api-server` had. The api-server workflow can be stopped; nothing in the dashboard uses it.

### HMR artifact in use-voice.ts (consistent pattern)
Adding any new hook (`useRef`, `useMarkStore`, `useEffect`) to `useVoice` triggers a React hooks-order HMR error when the module hot-swaps. This is an **HMR-only artifact** — a hard refresh clears it. Seen every time hook count changes in that file. Do not treat as a real bug.

### Voice pipeline reliability fixes
- Rate limiter: raised from 10 to 30 requests/60s (`smartagent/server/rate_limiter.py`)
- `/run` 409 race condition: if `_current_inference_task` is done/cancelled, reset `_state.running = False` and proceed instead of raising 409 (`api.py` execute endpoint)
- Sentence splitter: require 8+ accumulated chars before committing a sentence boundary — filters "Mr.", "Dr." abbreviations that produce garbled TTS fragments (`speech_runtime.py` `_split_complete_sentences`)
- `_SOFT_FLUSH_LEN` lowered 220 → 160 for shorter, faster TTS chunks
- Voice message queue: `pendingVoiceMessageRef` in `use-voice.ts` holds messages that arrived while MARK was mid-run; flushed via `useEffect` watching `isRunning`
- `sendUserMessage` catch: 409 silently discarded; other errors log `.message` not the raw object
- `speechPlayer.ts`: reset `nextStartTime = 0` when AudioContext is suspended so audio starts immediately after resume
