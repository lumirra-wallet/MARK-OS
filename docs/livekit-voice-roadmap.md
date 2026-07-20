# LiveKit Voice Transport — Implementation Roadmap

> **Status: AWAITING APPROVAL — no code has been modified**
>
> This document is the complete plan for replacing MARK's browser WebSocket
> voice transport with LiveKit while keeping the Brain Runtime unchanged.
> Implementation begins only after explicit approval of this roadmap.

---

## What We're Doing and Why

MARK's current voice transport is a hand-rolled WebSocket system:

- **Inbound (mic → MARK):** The browser opens `/ws/voice`, streams raw PCM16
  binary frames, and the Python backend runs Silero VAD + Faster-Whisper on
  that stream.
- **Outbound (MARK → speaker):** `speech_runtime.py` synthesizes audio with
  Kokoro, then blasts raw PCM16 binary frames over the main `/ws` connection.
  `speechPlayer.ts` in the browser queues and plays them.

This works, but it has real limitations:

| Problem | Impact |
|---|---|
| Raw PCM over WebSocket is not a media protocol — no jitter buffer, no packet recovery | Audio glitches on any network hiccup |
| Reconnection is manual (exponential backoff in `use-voice.ts`) | Noticeable drop-outs when Replit's proxy bounces |
| Tab backgrounding suspends the AudioContext and the ScriptProcessorNode | Voice goes silent the moment the tab is hidden |
| No video path exists | Future face-to-face MARK requires a full rebuild |
| Echo cancellation requires careful three-layer coordination across browser + backend | Fragile; breaks when timing assumptions change |

**LiveKit replaces the transport only.** The VAD → STT → Brain → Memory → NVIDIA
→ Decision → Kokoro TTS pipeline remains 100% owned by MARK's Python runtime.
LiveKit is the road; MARK is the driver.

---

## Architecture: Before vs After

### Before

```
Browser
  ├─ ScriptProcessorNode → resample → PCM16 → WebSocket /ws/voice
  │                                              └─► VoiceSession (VAD+STT)
  │                                                       └─► Brain Runtime
  │                                                              └─► speech_runtime.py
  │                                                                     └─► Kokoro PCM
  └─ speechPlayer.ts ◄── binary frames ◄── broadcast_bytes ─────────────────┘
                         (over /ws)
```

### After

```
Browser (livekit-client)
  ├─ LocalAudioTrack (mic) ─────────────────► LiveKit Room ─► MARK Agent (Python livekit SDK)
  │                                                                  └─► AudioFrames
  │                                                                        └─► VoiceSession (VAD+STT) [UNCHANGED]
  │                                                                               └─► Brain Runtime   [UNCHANGED]
  │                                                                                      └─► speech_runtime.py [UNCHANGED]
  │                                                                                             └─► Kokoro PCM
  └─ RemoteAudioTrack (plays MARK's voice) ◄── LiveKit Room ◄── AudioSource.capture_frame(pcm)
     (browser WebAudio/LiveKit plays natively)
```

**MARK's Brain Runtime — zero changes.** `VoiceSession`, `speech_runtime.py`,
`tts_engine.py`, `SmartAgent`, and everything in `smartagent/brain/` are
untouched. Only the transport boundary changes.

---

## Pre-flight: LiveKit Account Required

LiveKit has a generous free tier (50 GB/month bandwidth, unlimited rooms).
Before implementation begins, the following secrets must exist:

| Secret | Where to get it |
|---|---|
| `LIVEKIT_URL` | `wss://your-project.livekit.cloud` from LiveKit Cloud dashboard |
| `LIVEKIT_API_KEY` | LiveKit Cloud project settings |
| `LIVEKIT_API_SECRET` | LiveKit Cloud project settings |

**Alternative:** LiveKit Server is open-source and can be self-hosted on Linux
(a single binary). This is viable on Replit but adds a workflow to manage.
Recommended to start with LiveKit Cloud and self-host later if cost ever
becomes a concern.

---

## Milestones

---

### Milestone 1 — Token Service & Room Provisioning

**Why are we doing this?**
LiveKit is a JWT-secured system. Neither the browser nor the Python agent can
join a room without a short-lived signed token. This is the foundation that
every subsequent milestone builds on.

**What changes?**
- A new REST endpoint `GET /voice/token` is added to the MARK server.
- The endpoint uses `livekit-api` (Python) to sign a token granting the caller
  permission to join MARK's persistent room (`mark-presence`).
- Two token types: one for the human participant (publish mic, subscribe audio),
  one for the MARK agent (publish audio, subscribe mic, data channel).
- New module `smartagent/server/livekit_token.py` isolates this logic.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_token.py` | **New.** Token generation helper using `livekit-api`. |
| `smartagent/server/api.py` | **+1 route:** `GET /voice/token?participant=browser` |
| `requirements.minimal.txt` | **+** `livekit-api` |

**Dependencies**
- LiveKit Cloud credentials (pre-flight above)
- None from other milestones

**Risk: LOW**
Purely additive. No existing code is modified except a single `router.get`
registration in `api.py`. If LiveKit credentials are absent the endpoint
returns 503 with a clear error message — existing voice continues to work.

**Definition of Done**
- `GET /voice/token` returns a valid JWT
- The token can be used to join a LiveKit room from the browser console with
  the LiveKit Playground tool (manual verification, no code yet)
- Existing `/ws/voice` and `/ws` endpoints unaffected

---

### Milestone 2 — MARK's Backend LiveKit Agent

**Why are we doing this?**
MARK must join the LiveKit room as a persistent participant so he can receive
the browser's mic audio and publish his synthesized voice. This is the backend
half of the transport switch.

**What changes?**
A new `MarkLiveKitAgent` class joins the LiveKit room on server startup, stays
connected for the life of the process, and acts as the bridge between LiveKit
media and MARK's existing pipeline:

- **Inbound:** Subscribes to the browser participant's audio track. LiveKit
  delivers decoded PCM frames via callbacks. These frames are fed directly to
  `VoiceSession.feed()` — exactly as the old `/ws/voice` WebSocket did with
  raw binary data. **`VoiceSession` is unchanged.**
- **Outbound:** An `AudioSource` (24kHz mono, matching Kokoro's output rate) +
  `LocalAudioTrack` are pre-created. `speech_runtime.py` gains a new delivery
  path: when a PCM chunk is ready, it calls
  `audio_source.capture_frame(AudioFrame(...))` in addition to (temporarily)
  the existing `broadcast_bytes`. The old path stays active until Milestone 6.
- **Interruption signalling:** When `VoiceSession` fires `speech_start`, the
  agent sends a `speech_start` data channel message to all participants. The
  browser receives this and calls `stopMarkSpeech()` — same as today, just
  over LiveKit data channel instead of the voice WebSocket message.
- **Echo guard control:** `tts_start`/`tts_end` control signals are sent from
  the browser via the LiveKit data channel, received by the agent, and
  forwarded to `VoiceSession.mute()`/`unmute()` — same logic, new carrier.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_agent.py` | **New.** `MarkLiveKitAgent` class. |
| `smartagent/server/speech_runtime.py` | **+** `attach_livekit(audio_source)` method; `_speak_sentence` publishes to both paths during transition. |
| `smartagent/server/app.py` | **+** Start `MarkLiveKitAgent` as a background task on startup (alongside existing watchdog). |
| `requirements.minimal.txt` | **+** `livekit` (the Python room SDK, distinct from `livekit-api`) |

**Dependencies**
- Milestone 1 (token service, for the agent to obtain its own join token)

**Risk: MEDIUM**

The LiveKit Python SDK runs its own asyncio event loop internally. Care is
required to bridge it with FastAPI's existing loop. The approach: run the
agent in `asyncio.to_thread` or as a separate thread with its own loop,
communicating with the FastAPI loop via `asyncio.run_coroutine_threadsafe` —
the same pattern already used by `speech_runtime._broadcast_bytes`. This is
well-trodden ground in this codebase.

Audio frame format: LiveKit delivers audio as `AudioFrame` objects (signed
16-bit PCM, configurable sample rate). The agent will request 16kHz mono
(matching `VoiceSession`'s expected input) to avoid any resampling step.

The old WebSocket voice path stays fully operational during this milestone.
The backend simply gains a second delivery path — nothing breaks.

**Definition of Done**
- MARK agent appears as a participant in the LiveKit room (visible in LiveKit
  Cloud dashboard)
- Python logs confirm: audio frames arriving from browser → fed to VoiceSession
- VAD fires correctly on real speech (verified via backend logs)
- `speech_start` events appear in LiveKit data channel (verified via dashboard)
- Kokoro TTS audio publishes as a LiveKit audio track
- Existing WebSocket voice path still works in parallel

---

### Milestone 3 — Frontend LiveKit Client

**Why are we doing this?**
Replace `use-voice.ts`'s ScriptProcessorNode + WebSocket with the LiveKit
browser SDK. The browser publishes a mic track and subscribes to MARK's audio
track. LiveKit's SDK handles jitter buffering, WebRTC negotiation, tab
visibility, and reconnection automatically.

**What changes?**

**Frontend packages added:**
- `livekit-client` — the official LiveKit browser SDK (npm)

**`use-voice.ts` — full rewrite of the transport section:**

| Current | Replacement |
|---|---|
| `new WebSocket(wsUrl + '/ws/voice')` | `new Room()` → `room.connect(livekitUrl, token)` |
| `ScriptProcessorNode` → PCM16 → `socket.send()` | `room.localParticipant.publishTrack(LocalAudioTrack)` |
| `socket.onmessage` parsing `speech_start` / `partial` / `final` | `room.on(RoomEvent.DataReceived, ...)` |
| Manual exponential backoff reconnect | `Room` auto-reconnect (built into SDK) |
| `isMarkSpeakingRef` + `ws.send({type:'tts_start'})` | Same logic; signal sent via `room.localParticipant.publishData()` |

**`speechPlayer.ts` — decommissioned on the LiveKit path:**
LiveKit's SDK delivers MARK's audio track as a standard `MediaStreamTrack`,
which attaches to an `<audio>` element or `AudioContext` directly. No manual
PCM queuing needed. `speechPlayer.ts` is kept but bypassed; it remains as the
emergency fallback path (for `speechEngineUnavailable`) only.

**`markStore.ts` — minor:**
The store's binary audio handler (`case 'binary':` in the WebSocket message
loop) is gated behind a flag. When LiveKit is active, binary audio frames on
`/ws` are ignored (the LiveKit audio track plays instead).

**Which files?**

| File | Change |
|---|---|
| `artifacts/mark-dashboard/src/hooks/use-voice.ts` | **Rewrite** transport section; keep interruption + echo guard logic, replace WebSocket with LiveKit Room |
| `artifacts/mark-dashboard/src/store/markStore.ts` | **Minor:** gate binary audio handling on `!livekitActive` flag |
| `artifacts/mark-dashboard/src/lib/speechPlayer.ts` | **Kept** but bypassed on LiveKit path; still serves emergency fallback |
| `artifacts/mark-dashboard/package.json` | **+** `livekit-client` |

**Dependencies**
- Milestone 1 (token endpoint for browser to fetch before joining)
- Milestone 2 (MARK agent must be in the room to receive and respond)

**Risk: MEDIUM-HIGH**

Echo cancellation is the most delicate part. Currently, three layers protect
against MARK's voice feeding back into the VAD:
1. Browser AEC (`echoCancellation: true` on `getUserMedia`)
2. Frontend mic gate (`isMarkSpeakingRef` + `BARGE_IN_RMS`)
3. Backend energy threshold (`_BARGE_IN_ENERGY_THRESHOLD`)

LiveKit publishes mic audio using its own internal `getUserMedia` call.
`echoCancellation: true` must be explicitly passed in `CreateLocalTracksOptions`
to preserve layer 1. Layers 2 and 3 remain unchanged — the mic gate logic moves
from the ScriptProcessorNode callback into a LiveKit audio processor or the
data channel `tts_start` signal flow.

The `ScriptProcessorNode` (currently deprecated but reliable) is replaced by
LiveKit's own audio capture. If mic level visualization is needed
(the `micLevel` state), we add an `AnalyserNode` on the track's `MediaStream`.

Tab backgrounding: LiveKit's SDK keeps the audio track publishing even when
the tab is hidden, solving this problem automatically.

**Definition of Done**
- Voice works end-to-end through LiveKit (mic → room → MARK → room → speaker)
- Half-duplex interruption works: speaking over MARK stops him immediately
- Mic level meter still animates correctly
- Interim transcripts still show in the UI
- Tab backgrounding no longer silences voice
- Network disconnect → LiveKit auto-reconnects without user action

---

### Milestone 4 — Half-Duplex, Echo Guard & Interruption Hardening

**Why are we doing this?**
The interruption and echo guard behaviour must be verified to be as tight as
the current implementation — or tighter. This milestone is a dedicated
hardening pass, not an afterthought.

**What changes?**

**Interruption timing:**
The current path: VAD fires `speech_start` → `voice_websocket` calls
`speech_runtime.interrupt()` AND `_current_inference_task.cancel()` → sends
`speech_start` back to the browser over the voice WebSocket → browser calls
`stopMarkSpeech()`.

On LiveKit: VAD fires `speech_start` inside `MarkLiveKitAgent` → same two
backend calls (`interrupt()` + `cancel()`) → data channel message to browser
→ browser calls `stopMarkSpeech()` + mutes its own audio element.

The front-end stop is still local (no round-trip wait) because the data
channel message arrives in the same tick as the browser's own VAD-level audio
detection (LiveKit does VAD client-side too as an optimization, but MARK's
authoritative VAD remains Silero on the backend).

**Echo guard via LiveKit mute:**
When MARK starts speaking, instead of the old `tts_start` frame on `/ws/voice`,
the browser sends a data channel message `{type:"tts_start"}`. The MARK agent
receives it and calls `VoiceSession.mute()`. When MARK finishes speaking
(post-350ms holdoff), the browser sends `{type:"tts_end"}` → `unmute()`.

Additionally: LiveKit supports publishing a track as "muted" — when the
frontend's mic gate decides to suppress frames, it can toggle
`localTrack.muted = true` for zero-cost silence rather than sending silent
frames to the room.

**Audio level detection for `micLevel`:**
`use-voice.ts` currently polls an `AnalyserNode` for the mic amplitude
visualization. With LiveKit, we attach an `AnalyserNode` to the track's
underlying `MediaStream` via:
```ts
const stream = new MediaStream([localTrack.mediaStreamTrack]);
const source = ctx.createMediaStreamSource(stream);
source.connect(analyser);
```
This preserves the mic level meter without any behavioural changes to the UI.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_agent.py` | Refine data channel message handlers; add `_current_inference_task` cancel on `speech_start` |
| `artifacts/mark-dashboard/src/hooks/use-voice.ts` | Mic gate via `localTrack.muted`, AnalyserNode for level, data channel for `tts_start/end` |

**Dependencies**
- Milestone 3

**Risk: LOW-MEDIUM**
The logic is identical to today — only the carrier changes (data channel
instead of WebSocket message). The echo guard thresholds (`BARGE_IN_RMS`,
`_BARGE_IN_ENERGY_THRESHOLD`) are unchanged.

**Definition of Done**
- Speaking over MARK stops him in <150ms (matching current behaviour)
- No echo loop observed with speakers at comfortable volume
- Mic muting during MARK speech reflected in the LiveKit room (track shows
  muted in dashboard)
- Barge-in at loud volume works even while MARK is mid-sentence

---

### Milestone 5 — Persistent Sessions & Automatic Reconnection

**Why are we doing this?**
MARK is always alive. The room exists before you open the dashboard. Reconnecting
should be seamless — not a fresh start.

**What changes?**

**Room naming:** The room name is `mark-presence` (deterministic, not
per-session). The MARK agent joins this room on server startup and never leaves.
If it gets disconnected, it reconnects automatically.

**Browser reconnect:** LiveKit's `Room` object has built-in reconnect logic.
On network drop, it transparently attempts to rejoin. The `RoomEvent.Reconnected`
event is used to update UI state (flash the mic indicator briefly).

**Session persistence:** The backend agent maintains a `VoiceSession` per
connected human participant (keyed by participant identity). When the same
browser reconnects, it gets the same `VoiceSession` state — the VAD buffer is
not reset, so a reconnect mid-sentence doesn't lose that sentence.

**Startup behaviour:** `MarkLiveKitAgent.start()` is called from `app.py`
lifespan startup — the agent joins the room before the first HTTP request
is served. If LiveKit credentials are absent, this is a no-op (warning logged)
and the existing WebSocket voice path remains active.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_agent.py` | Persistent room join on startup; per-participant VoiceSession map; auto-reconnect loop |
| `smartagent/server/app.py` | Call `agent.start()` in lifespan startup |
| `artifacts/mark-dashboard/src/hooks/use-voice.ts` | Handle `RoomEvent.Reconnected`; no manual backoff needed |

**Dependencies**
- Milestone 4

**Risk: LOW**
LiveKit's SDK handles reconnection at the protocol level. The main risk is the
backend agent disconnect — handled by a simple reconnect loop in `livekit_agent.py`
with exponential backoff matching the existing voice WebSocket reconnect logic.

**Definition of Done**
- Reloading the browser tab reconnects voice in <2 seconds
- Network simulator drop-reconnect works without user action
- MARK agent remains in the LiveKit room across all browser reconnects
- Server log confirms "MARK agent joined mark-presence" exactly once per server
  process startup

---

### Milestone 6 — Remove Old WebSocket Voice Transport

**Why are we doing this?**
Once LiveKit is verified end-to-end, the old transport is dead weight. Keeping
it creates a dual-maintenance burden and the temptation to fall back on it
when debugging.

**What changes?**

- `voice_websocket()` handler removed from `api.py` (`/ws/voice` route deleted)
- Binary audio broadcast removed from `speech_runtime.py`
  (`_broadcast_bytes` call in `_speak_sentence` removed; `broadcast_bytes` on
  `ConnectionManager` kept for potential future use but no longer called)
- `speechPlayer.ts` deleted (or reduced to the emergency browser-TTS fallback
  wrapper only — the PCM queue logic is no longer needed)
- `use-voice.ts` voiceWsRef and reconnect logic removed (replaced by LiveKit
  Room in Milestone 3)
- `markStore.ts` binary frame handler removed

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/api.py` | Remove `voice_websocket()` function and its route |
| `smartagent/server/speech_runtime.py` | Remove `_broadcast_bytes` call; keep `attach_livekit()` path only |
| `artifacts/mark-dashboard/src/lib/speechPlayer.ts` | Delete or strip to emergency-only fallback |
| `artifacts/mark-dashboard/src/store/markStore.ts` | Remove binary frame handler |
| `artifacts/mark-dashboard/src/hooks/use-voice.ts` | Remove WebSocket refs and reconnect logic |

**Dependencies**
- Milestone 5 fully verified end-to-end
- At least 48h of real-world usage on the LiveKit path with no regressions

**Risk: HIGH (by design — this is the irreversible step)**
This is the only high-risk milestone, and it comes last for exactly that
reason. At this point LiveKit has been running in production for multiple
sessions. The old code is removed in one clean commit. If a regression is
found after removal, the checkpoint/rollback system is the recovery path.

**Definition of Done**
- No `/ws/voice` route in the server
- No `ScriptProcessorNode` or manual PCM WebSocket code in the frontend
- Voice works exclusively through LiveKit
- All existing voice behaviours (interruption, echo guard, reconnect, mic
  level, interim transcripts) confirmed working
- Zero TypeScript errors, zero Python test regressions

---

## Dependency Graph

```
[Pre-flight: LiveKit Cloud account + secrets]
        │
        ▼
  Milestone 1            ← purely additive, no risk
  Token Service
        │
        ▼
  Milestone 2            ← backend agent, old path stays live
  MARK LiveKit Agent
        │
        ▼
  Milestone 3            ← frontend switch, dual-path active
  Frontend LiveKit Client
        │
        ▼
  Milestone 4            ← hardening, no new surfaces
  Interruption & Echo Guard
        │
        ▼
  Milestone 5            ← persistence, reconnect
  Persistent Sessions
        │
        ▼
  Milestone 6            ← removal (irreversible — do last)
  Remove Old WS Transport
```

---

## What LiveKit Never Touches

| Concern | Owner |
|---|---|
| VAD (Silero) | `smartagent/server/voice_pipeline.py` — unchanged |
| STT (Faster-Whisper) | `smartagent/server/voice_pipeline.py` — unchanged |
| Brain Runtime (SmartAgent) | `smartagent/brain/` — unchanged |
| Memory retrieval | `smartagent/memory/` — unchanged |
| NVIDIA reasoning | `smartagent/llm/` — unchanged |
| Decision making | `smartagent/mind/` — unchanged |
| TTS synthesis (Kokoro) | `smartagent/server/tts_engine.py` — unchanged |
| Sentence buffering | `smartagent/server/speech_runtime.py` — method added, none removed |

LiveKit is the road. The freight — VAD, STT, brain, Kokoro — never moves.

---

## Estimated Effort

| Milestone | Estimate |
|---|---|
| M1 Token Service | ~2h |
| M2 MARK LiveKit Agent | ~6h |
| M3 Frontend LiveKit Client | ~5h |
| M4 Interruption Hardening | ~3h |
| M5 Persistent Sessions | ~2h |
| M6 Remove Old Transport | ~2h |
| **Total** | **~20h** |

---

## Risk Summary

| Risk | Likelihood | Mitigation |
|---|---|---|
| LiveKit Cloud latency adds perceptible delay | Medium | LiveKit's median p99 latency is ~60ms; current WS path has similar tail latency on Replit's proxy |
| Echo loop via LiveKit AEC | Medium | Pass `echoCancellation:true` in `CreateLocalTracksOptions`; all three backend guard layers unchanged |
| Python async loop conflict | Low | Use isolated thread + `run_coroutine_threadsafe` (same pattern already in `speech_runtime.py`) |
| LiveKit Cloud free tier exhausted | Low | 50GB/month is ~5,000 hours of voice; monitor in dashboard |
| Regression on removal (M6) | Low | M6 comes after 48h of verified LiveKit-only operation |

---

## Files NOT Changed by This Roadmap

The following files are **explicitly excluded** from this roadmap and will not
be modified at any point:

- `smartagent/brain/` (entire directory)
- `smartagent/mind/` (entire directory)
- `smartagent/memory/` (entire directory)
- `smartagent/llm/` (entire directory)
- `smartagent/identity/` (entire directory)
- `smartagent/server/voice_pipeline.py` (VoiceSession is unchanged)
- `smartagent/server/tts_engine.py` (Kokoro is unchanged)
- Any dashboard panel that is not `use-voice.ts` or `markStore.ts`'s audio handler

---

*Awaiting approval. Implementation starts with Milestone 1 only.*
