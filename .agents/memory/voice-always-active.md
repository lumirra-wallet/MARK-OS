---
name: Voice Always-Active Rebuild
description: Root causes and fixes for background ghost messages + MARK requiring a chat trigger before voice worked.
---

## Root Causes Found

### Ghost messages in chat (background LLM calls)
`_idle_inspector_loop` in `api.py` called `_broadcast_idle_chat_message()` every 45 s of idle time.
This made unsolicited LLM calls → broadcast `MARK_PROACTIVE` → appeared as MARK messages in the chat thread.
User saw MARK "talking" without being prompted.

**Fix**: Removed the `_broadcast_idle_chat_message` call from `_idle_inspector_loop`.
Only `IDLE_SUGGESTION` events are now broadcast (these update a passive panel, not the conversation thread).

### Voice required a manual trigger
`voiceEnabled` started as `false` (`useState(false)`) in `use-voice.ts`.
User had to click the mic button to connect the voice WebSocket.

**Fix**: Changed to `useState(true)` + `enabledRef.current = true` default.
Added a mount-once `useEffect` that calls `connectVoiceSocket()` immediately on page load.
MARK now listens from the moment the tab opens — no button click required.

### Two simultaneous voice WebSocket sessions
Tab refresh, HMR reconnects, or opening a second tab caused two `/ws/voice` connections.
Both sessions ran VAD + Whisper → both sent `final` events → double `/voice/message` calls.

**Fix**: Added `_active_voice_ws: WebSocket | None = None` global in `api.py`.
On each new `/ws/voice` connect, the old WS is closed before the new session registers.
Single-session enforcement — only one tab streams audio at a time.

### Browser TTS fallback echo loop
When Kokoro TTS unavailable, `window.speechSynthesis.speak()` fired without muting the mic.
MARK's browser voice output could be picked up by the mic → Whisper → `/voice/message` → loop.

**Fix**: `micMutedRef.current = true` set before `speechSynthesis.speak()`.
Restored in `utterance.onend` with a 1200 ms delay to match server POST_SPEECH holdoff.

## Toggle semantics changed
Old: button enables/disables voice (WS connects/disconnects).
New: button mutes/unmutes mic (WS stays connected, PCM frames stop when muted).
Status text: "Listening…" / "Muted — click to unmute" / "Speaking…" / "Connecting…".

## Key constraint
`global <name>` in Python must appear at function scope before any use of the name.
Putting `global` inside a nested block (`async with`, `if`, etc.) causes SyntaxError
"name used prior to global declaration" if there are any references elsewhere in the function.
Always place `global` as the FIRST statement in the function body.

**Why**: Wasted a restart cycle on this. Python's scoping rules apply function-wide.
