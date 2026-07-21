---
name: Voice Echo Loop / Double Processing
description: Root causes and fixes for MARK processing the same utterance twice in voice mode.
---

# Voice Double-Processing — Root Causes & Fixes

## Symptom
Cognitive timeline showed "interrupted ×2, decision made ×2, listening ×2" for a single user utterance.

## Root Causes Found (via live server testing)

### 1. `isRunningRef` stale-ref race (frontend)
`isRunningRef.current` was synced via `useEffect`, which runs **after** the render paint.
Between calling `sendVoiceMessage` and React painting the render that updates the ref, a second
`final` event could arrive, see `isRunningRef.current = false`, and also fire `sendVoiceMessage`.

**Fix:** Set `isRunningRef.current = true` synchronously immediately before calling
`sendVoiceMessage` — in both the direct path (`final` handler) and the flush-after-run `useEffect`.

### 2. Server TOCTOU race on `_state.running`
Two concurrent `_voice_chat_response` coroutines both saw `_state.running = False` before either
set it to `True`. The gap between the wait-loop and the `_state.running = True` assignment was
unprotected.

**Fix:** Added `_voice_chat_lock = asyncio.Lock()` to make the check+set atomic.
File: `smartagent/server/api.py`, function `_get_voice_chat_lock()`.

### 3. Room echo triggering false barge-in (primary echo cause)
`_BARGE_IN_THRESHOLD` was `0.045` RMS. Room echo from desktop speakers measured in the 0.02–0.05
range. Any echo burst above 0.045 triggered `barge_in()` which immediately transitioned the VAD
to LISTENING state — causing the subsequent echo tail to be transcribed by Whisper and POSTed as a
new "user message" with different text (bypassing the exact-match dedup guard).

**Fix:** Raised threshold to `0.065` (requires genuine voice energy ≥0.08 RMS).
After barge-in, now applies a 200ms `POST_SPEECH` holdoff (`_BARGE_IN_ECHO_HOLDOFF_SAMPLES`)
to absorb the echo tail before VAD opens. File: `smartagent/server/voice_pipeline.py`.

### 4. `tts_end` holdoff started from server's last byte, not browser's playback end
The server calls `_unmute_mic()` when the speech worker sends the **last byte** — not when the
browser finishes playing. Live test showed server sends 5.12s of audio in 2.37s (2×+ real-time).
The 900ms holdoff started 2.75s before the browser finished playing, meaning the holdoff expired
while the browser's AudioContext was still rendering the tail of MARK's response.

**Fix:** When `tts_end` is received from the browser voice WS (fired when `isMarkSpeaking = false`,
i.e. AudioBufferSourceNode `.onended` fires), restart the POST_SPEECH holdoff countdown from now.
File: `smartagent/server/api.py`, `voice_websocket` `tts_end` handler.

### 5. VAD utterance splitting at short pauses
`min_silence_duration_ms = 650` caused the VAD to fire a `final` event after 650ms of silence.
Natural mid-sentence pauses (~700ms) split one utterance into two separate finals → two POSTs.

**Fix:** Raised to `1000ms`. File: `smartagent/server/voice_pipeline.py`, `VoiceSession.__init__`.

## Key Measurements (from live test)
- POST → RunStarted: ~23ms
- RunStarted → RunCompleted: ~2.3s
- RunCompleted → SpeechStart: ~2.6s (TTS model load latency)
- SpeechStart → SpeechEnd (last byte sent): ~2.4s
- TTS audio duration (PCM bytes): ~5.1s
- Browser plays until: SpeechEnd + (audio_duration - send_window) ≈ SpeechEnd + 2.7s
- Old holdoff expiry: SpeechEnd + 0.9s (expired 1.8s before browser finished playing!)
- New holdoff expiry: tts_end received (= browser done) + 0.9s ✓

## `tts_end` Browser → Server Flow
`SpeechPlayer.ts`: `source.onended` fires when AudioBufferSourceNode finishes playing.
When `activeSources.size === 0` → `onStateChange(false)` → `isMarkSpeaking = false` in store.
`use-voice.ts` Zustand subscribe fires synchronously → sends `{"type": "tts_end"}` on voice WS.
`api.py voice_websocket`: if `session._state == _STATE_POST_SPEECH` → restart holdoff countdown.

## How to Diagnose Future Voice Loops
The server now logs at INFO level:
- `voice_chat: received transcript "..."` — every incoming POST
- `voice_chat: duplicate transcript within 5s — dropping "..."` — dedup fired
- `voice_chat: run still active after 3s — skipping "..."` — lock fired
- `voice_chat: starting response for "..."` — run actually proceeding
- `voice_pipeline: barge-in → 200ms echo holdoff → LISTENING` — false barge-in
- `voice_pipeline: tts_end — restarting holdoff from actual playback completion`

**Why:** Tracking these entries makes it immediately visible if a transcript arrives that shouldn't,
and which guard caught it (or failed to catch it).
