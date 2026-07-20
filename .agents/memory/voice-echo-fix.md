---
name: Voice Echo / Self-Talk Fix
description: Root cause and architecture of the fix for MARK hearing his own TTS output and sending it as a new message.
---

## The Problem
MARK was transcribing his own speaker output via the open microphone, then posting it to /voice/message — creating a conversation loop with himself.

## Root Cause
The old mute sequence was reactive and too slow:
1. speech_runtime emits SPEECH_START event → travels over main /ws
2. Frontend Zustand store updates isMarkSpeaking → triggers useEffect
3. useEffect send tts_start over /ws/voice → server receives → calls session.mute()

By step 3, MARK's TTS audio had been playing for 200-500ms and the mic had already captured it. The VAD processed that audio before the mute arrived.

## The Fix: Proactive Server-Side Mute

### voice_pipeline.py
- Added module-level session registry: `register_session()`, `unregister_session()`, `mute_active_session()`, `unmute_active_session()`
- VoiceSession now has a 3-state machine: LISTENING → TTS_ACTIVE → POST_SPEECH → LISTENING
- `mute()` hard-resets VAD state + clears all pending/utterance buffers (no stale audio)
- `unmute()` starts POST_SPEECH holdoff (900ms, sample-accurate) instead of sleeping
- During TTS_ACTIVE: ALL audio discarded (no VAD, no transcription)
- Barge-in: energy threshold check (RMS ≥ 0.045) during TTS_ACTIVE — only genuine voice triggers speech_start + immediate LISTENING transition
- During POST_SPEECH: audio consumed but not processed — absorbs room reverb + AEC settling

### speech_runtime.py
- Before first audio byte of a reply: calls `_mute_mic()` → `mute_active_session()` (proactive, no round-trip)
- After `_END_OF_REPLY` processed: calls `_unmute_mic()` → `unmute_active_session()` (starts VoiceSession holdoff)
- No sleep in worker thread — holdoff is sample-accurate inside VoiceSession.feed()

### api.py (voice_websocket)
- Calls `register_session(session)` on connect, `unregister_session(session)` + `session.reset()` on disconnect
- tts_start/tts_end from browser now labeled as secondary/safety-net signals
- Removed `asyncio.sleep(0.35)` on tts_end (holdoff handled by VoiceSession)

### use-voice.ts
- micMutedRef updated via synchronous Zustand subscribe() (not useEffect) — fires same tick as store change, no render-cycle delay
- tts_start/tts_end still sent to server as belt-and-suspenders secondary signal
- On speech_start: immediately clears interimTranscript and calls stopMarkSpeech()
- Removed separate holdoffTimerRef — server handles holdoff

## Key Invariant
`mute_active_session()` is ALWAYS called before `broadcast_bytes()` for any sentence. VoiceSession.feed() discards all audio during TTS_ACTIVE. The mic gate on the client is a secondary layer only.

**Why:** The round-trip (server event → client → client sends tts_start → server) took 200-500ms. In that window, audio played, got captured, got transcribed. Moving the mute to happen inside speech_runtime — same process, same thread, before any audio is sent — eliminates that window entirely.
