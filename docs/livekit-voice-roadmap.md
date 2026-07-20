# LiveKit Voice Transport — Implementation Roadmap (v2)

> **Status: AWAITING APPROVAL — no code has been modified**
>
> Revision: Updated to target self-hosted LiveKit (open-source binary from
> github.com/livekit/livekit) as the **default**. LiveKit Cloud remains
> supported as an optional override. MARK OS stays independent of third-party
> hosted services.
>
> Implementation begins only after explicit approval.

---

## Guiding Principle

MARK should own every layer of his voice stack:

| Layer | Owner |
|---|---|
| Media transport (WebRTC/RTC) | LiveKit — **self-hosted, on the same machine** |
| Voice activity detection | Silero VAD — MARK's Python runtime (unchanged) |
| Speech-to-text | Faster-Whisper — MARK's Python runtime (unchanged) |
| Reasoning / memory / decisions | SmartAgent — MARK's Python runtime (unchanged) |
| Text-to-speech synthesis | Kokoro — MARK's Python runtime (unchanged) |

No cloud account. No third-party routing of MARK's voice. The LiveKit binary
is an open-source Go process that MARK runs locally, not a service MARK
depends on.

---

## Architecture: Before vs After

### Before (current)

```
Browser
  ├─ ScriptProcessorNode → resample → PCM16 binary → WebSocket /ws/voice
  │                                                       └─► VoiceSession (VAD+STT)
  │                                                              └─► Brain Runtime
  │                                                                     └─► speech_runtime
  │                                                                            └─► Kokoro PCM
  └─ speechPlayer.ts ◄── binary PCM16 frames ◄── broadcast_bytes() ─────────────┘
                         (over /ws WebSocket)
```

### After (self-hosted LiveKit)

```
[livekit-server binary — port 7880 — supervised by mark_supervisor.py]
                          │
        ┌─────────────────┼──────────────────────┐
        │                 │                       │
Browser (livekit-client)  │         MARK Agent (livekit Python SDK)
  │ LocalAudioTrack (mic) │──► Room ──► AudioFrames
  │                       │               └─► VoiceSession (VAD+STT) [UNCHANGED]
  │                       │                      └─► Brain Runtime   [UNCHANGED]
  │                       │                             └─► speech_runtime [UNCHANGED]
  │                       │                                    └─► Kokoro PCM
  └─ RemoteAudioTrack ◄───┘ ◄── AudioSource.capture_frame(pcm)
     (played natively by LiveKit SDK / browser WebAudio)
```

**Zero changes to MARK's Brain Runtime.** The transport boundary moves;
everything above it stays identical.

---

## Dual-Mode Configuration

One environment variable drives the mode:

```
LIVEKIT_URL=ws://localhost:7880          ← self-hosted (default, no account needed)
LIVEKIT_URL=wss://your-project.livekit.cloud  ← cloud override
```

When `LIVEKIT_URL` is absent or points to localhost, MARK downloads the
LiveKit binary and runs it as a local subprocess. When it points to a cloud
URL, MARK skips the binary entirely and connects to the external host. All
other code — token service, Python agent, frontend — is identical in both modes.

The two other required secrets are set once during Milestone 1 setup:

```
LIVEKIT_API_KEY=<locally generated random string>
LIVEKIT_API_SECRET=<locally generated random string>
```

These are just strings. In self-hosted mode, MARK generates them itself and
configures the local LiveKit server with the same values. No external authority
is involved.

---

## Milestones

---

### Milestone 0 — LiveKit Binary, Key Generation & Process Supervision

**Why are we doing this?**
The LiveKit open-source server is a single Go binary (~50MB). Before any code
can use LiveKit, the binary must be available, the local server must be
running, and MARK must have API credentials to sign tokens. This milestone
puts all of that in place, completely self-contained.

**What changes?**

#### Part A — Key generation script

A one-time setup script `smartagent/server/livekit_setup.py` is added. When
run, it:

1. Checks whether `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` secrets exist.
2. If absent, generates them using `secrets.token_urlsafe(32)` and prints
   instructions to store them as Replit Secrets (using the environment-secrets
   skill — we do not write secrets to files).
3. Sets `LIVEKIT_URL=ws://localhost:7880` as the default if absent.

This script runs once by the developer, not on every server start.

#### Part B — Binary download & caching

A new module `smartagent/server/livekit_process.py` handles everything needed
to run the local LiveKit server:

- **Download:** Fetches `livekit_linux_amd64.tar.gz` from the GitHub releases
  page the first time it is needed. The URL pattern is:
  `https://github.com/livekit/livekit/releases/download/vX.Y.Z/livekit_linux_amd64.tar.gz`
  The latest release tag is resolved via the GitHub releases redirect
  (`/releases/latest/download/`) — no GitHub token required, it is a public repo.
- **Cache:** Extracted binary stored at `.mark_storage/livekit/livekit-server`.
  If the file exists and is executable, the download is skipped entirely on
  subsequent starts.
- **Config generation:** At each startup, a minimal `config.yaml` is written
  to `.mark_storage/livekit/config.yaml` from the current env vars:

```yaml
# Generated by MARK — do not edit by hand
port: 7880
rtc:
  port_range_start: 50000
  port_range_end: 60000
  tcp_port: 7881
keys:
  <LIVEKIT_API_KEY>: <LIVEKIT_API_SECRET>
logging:
  level: warn
  json: false
```

#### Part C — Process supervision

The existing `watchdog.py` supervises `uvicorn`. Its pattern (Popen child,
poll loop, restart on exit) is extended into a new
`smartagent/server/mark_supervisor.py` that manages **two** child processes
in sequence:

1. **LiveKit server** — started first, health-polled on `http://localhost:7880`
   until ready (max 15s), then held open for the life of the supervisor.
2. **MARK server (uvicorn)** — started after LiveKit is confirmed healthy,
   supervised with the same restart logic as the current `watchdog.py`.

`mark_supervisor.py` replaces `watchdog.py` as the entry point. `watchdog.py`
is kept unchanged so existing tests and references are not broken — it simply
delegates to `mark_supervisor.py` if LiveKit is configured, or runs its
existing loop if `LIVEKIT_URL` is absent (graceful degradation, not a hard
break).

The `package.json` dev script gains one line:

```json
"dev": "cd ../.. && pip install -q -r requirements.minimal.txt 2>&1 | tail -3 && PYTHONUTF8=1 python -m smartagent.server.mark_supervisor"
```

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_setup.py` | **New.** One-time key generation helper |
| `smartagent/server/livekit_process.py` | **New.** Binary download, config generation, `LiveKitProcess` class |
| `smartagent/server/mark_supervisor.py` | **New.** Two-process supervisor (LiveKit + uvicorn) |
| `artifacts/mark-api/package.json` | **1-line change:** `mark_supervisor` instead of `watchdog` |
| `smartagent/server/watchdog.py` | **Unchanged** (kept for backward compatibility) |
| `.mark_storage/livekit/` | **New directory** at runtime (gitignored, not committed) |
| `.gitignore` | **+** `.mark_storage/livekit/` |

**Dependencies**
- None from other milestones
- `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL` Replit Secrets
  (created by the setup script in Part A)

**Risk: LOW**

The binary download is the only new network dependency, and it is cached after
the first run — subsequent starts are offline-capable. If LiveKit fails to
start (binary missing, port conflict, bad config), `mark_supervisor.py` logs a
clear error and falls back to starting uvicorn without LiveKit — voice will
show as unavailable in the dashboard but everything else continues working.

The current "Address already in use" watchdog restart loop will be fixed
naturally by this milestone: `mark_supervisor.py` uses `LIVEKIT_PORT` and
`MARK_PORT` as separate env vars, making port assignment explicit.

**Definition of Done**
- `python -m smartagent.server.livekit_setup` generates and prints valid keys
- `python -m smartagent.server.mark_supervisor` starts LiveKit on 7880 and
  uvicorn on 18949 in the correct order
- LiveKit health check `GET http://localhost:7880` returns 200
- Stopping the supervisor (Ctrl-C / SIGTERM) terminates both children cleanly
- Restarting the supervisor skips the binary download (cache hit confirmed in logs)
- Existing Python tests pass (watchdog.py unchanged)
- Cloud override: setting `LIVEKIT_URL=wss://cloud.example` skips the binary
  entirely and connects to the remote host

---

### Milestone 1 — Token Service

**Why are we doing this?**
Both the browser and the MARK Python agent need a signed JWT to join the
LiveKit room. The token format (VideoGrant claims) is specific to LiveKit.
This milestone adds the signing endpoint using libraries already in
`requirements.minimal.txt` (`pyjwt`, `cryptography`) — no new Python
dependency is needed.

**What changes?**

New module `smartagent/server/livekit_token.py` implements the LiveKit JWT
format using `pyjwt`:

```
GET /voice/token?role=browser   → participant token (publish mic, subscribe audio)
GET /voice/token?role=agent     → agent token (publish audio, subscribe mic, data)
```

Both tokens grant access to the room `mark-presence` (a fixed, deterministic
name — not per-session). Token lifetime: 2 hours (refreshed automatically by
the client SDK before expiry).

The JWT payload follows the LiveKit spec exactly:
```json
{
  "iss": "<LIVEKIT_API_KEY>",
  "sub": "<identity>",
  "iat": <now>,
  "exp": <now + 7200>,
  "nbf": <now>,
  "video": {
    "room": "mark-presence",
    "roomJoin": true,
    "canPublish": true,
    "canSubscribe": true,
    "canPublishData": true
  }
}
```

Signed with `LIVEKIT_API_SECRET` using HS256 — standard JWT, no external
library beyond `pyjwt`.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_token.py` | **New.** Token generation (pure Python, no new deps) |
| `smartagent/server/api.py` | **+2 routes:** `GET /voice/token`, `GET /voice/config` |

`GET /voice/config` returns the LiveKit URL and room name so the frontend
never hardcodes them:
```json
{
  "url": "ws://localhost:7880",
  "room": "mark-presence",
  "mode": "self-hosted"
}
```

**Dependencies**
- Milestone 0 (secrets must exist for signing)

**Risk: LOW**
Purely additive. If `LIVEKIT_API_KEY` or `LIVEKIT_API_SECRET` is absent, the
endpoint returns 503 with a descriptive error. Existing voice still works.

**Definition of Done**
- `GET /voice/token?role=browser` returns a valid JWT
- Token can be used to join `mark-presence` room via LiveKit CLI or Playground
  (manual verification: `livekit-cli join-room --room mark-presence --token <jwt>`)
- Token is rejected when the secret is wrong (verified with curl)
- `GET /voice/config` returns correct mode and URL for both self-hosted and
  cloud configurations

---

### Milestone 2 — MARK's Backend LiveKit Agent

**Why are we doing this?**
MARK must join the LiveKit room as a persistent audio participant: receiving
mic audio from the browser and publishing synthesized speech back. This is
the backend half of the transport replacement.

**What changes?**

New module `smartagent/server/livekit_agent.py` containing `MarkLiveKitAgent`:

**Inbound (mic → VoiceSession):**
- Joins `mark-presence` room using the agent token from M1.
- Subscribes to the browser participant's audio track.
- LiveKit delivers decoded audio as `AudioFrame` objects (16kHz mono PCM16,
  matching `VoiceSession.feed()`'s expected input — no resampling needed;
  this sample rate is requested explicitly in the subscription options).
- Each `AudioFrame` is converted to raw bytes and passed to
  `VoiceSession.feed()` — exactly what `/ws/voice` did with the binary
  WebSocket frames. **`VoiceSession` is unchanged.**

**Outbound (Kokoro PCM → browser ears):**
- At startup, creates an `AudioSource` (24kHz mono, matching
  `tts_engine.SAMPLE_RATE`) and publishes it as a `LocalAudioTrack`.
- `speech_runtime.py` gains a new method `attach_livekit(audio_source)`.
  Inside `_speak_sentence`, after synthesizing a PCM chunk, it calls
  `audio_source.capture_frame(AudioFrame(data=pcm, ...))` alongside the
  existing `broadcast_bytes` call. **The old WebSocket audio path stays active
  during this transition** — both paths deliver audio until M5 removes the old one.

**Interruption (VAD speech_start → browser stops playback):**
When `VoiceSession.feed()` returns a `speech_start` event:
1. `speech_runtime.interrupt()` is called (same as today).
2. `_current_inference_task` is cancelled (same as today).
3. A LiveKit data channel message `{"type":"speech_start"}` is sent to all
   room participants. The browser receives it and calls `stopMarkSpeech()` —
   same as today, different carrier.

**Echo guard (tts_start / tts_end):**
When the browser's mic gate activates (MARK is speaking), it sends a LiveKit
data channel message `{"type":"tts_start"}` to the room. The agent receives
it and calls `VoiceSession.mute()`. On `tts_end`, calls `VoiceSession.unmute()`.
Logic is identical to today; the voice WebSocket control frames are replaced
by data channel messages.

**Lifecycle:**
- `MarkLiveKitAgent.start()` is called from `app.py` lifespan startup, after
  the existing `_warm_agent` task — the agent joins the room once and stays.
- If LiveKit is not configured (`LIVEKIT_URL` absent), `start()` is a no-op.
- Reconnect: if the room connection drops, the agent reconnects with
  exponential backoff (same pattern as `watchdog.py`'s restart logic).

**Python package added:**
- `livekit` — the LiveKit Python Room SDK. This is the only new Python
  dependency in the entire roadmap. It is a pure-Python package with no
  compiled extensions; it installs on any platform.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_agent.py` | **New.** `MarkLiveKitAgent` class |
| `smartagent/server/speech_runtime.py` | **+1 method:** `attach_livekit(audio_source)` and one `capture_frame` call in `_speak_sentence`. Nothing removed. |
| `smartagent/server/app.py` | **+5 lines** in lifespan: import agent, call `agent.start()` if configured |
| `requirements.minimal.txt` | **+** `livekit` |

**Dependencies**
- Milestone 0 (LiveKit server running)
- Milestone 1 (token endpoint, to generate the agent's join token)

**Risk: MEDIUM**

The `livekit` Python SDK runs its own asyncio event loop in a background
thread. Bridging it to FastAPI's loop uses `asyncio.run_coroutine_threadsafe`
— the same pattern already proven in `speech_runtime._broadcast_bytes`.

Audio frame format: the LiveKit Python SDK delivers `AudioFrame(data: bytes,
sample_rate: int, num_channels: int, samples_per_channel: int)`. Converting
`data` to a numpy array for `VoiceSession.feed()` is a one-line `np.frombuffer`
call — identical to what `pcm16_to_float32` does today.

The old WebSocket voice path remains fully live throughout this milestone.
Nothing breaks if the agent fails to start — it logs a warning and the
dashboard shows voice as unavailable on the LiveKit path.

**Definition of Done**
- LiveKit dashboard (or `livekit-cli room list`) shows two participants in
  `mark-presence`: browser and MARK agent
- Backend logs confirm audio frames arriving from browser → VoiceSession
- Silero VAD fires correctly on real speech (logs: `speech_start`)
- Kokoro TTS audio publishes as a LiveKit track (confirmed via LiveKit
  Egress or CLI subscriber)
- Existing `/ws/voice` WebSocket path still works in parallel
- Zero regressions in Python test suite

---

### Milestone 3 — Frontend LiveKit Client

**Why are we doing this?**
Replace `use-voice.ts`'s `ScriptProcessorNode` + WebSocket with the LiveKit
browser SDK. This is the frontend half of the transport switch.

**What changes?**

**npm package added:** `livekit-client`

**`use-voice.ts` — transport section rewritten:**

| Current | Replacement |
|---|---|
| `new WebSocket(serverUrl + '/ws/voice')` | `new Room()` → `room.connect(livekitUrl, token)` where URL+token come from `GET /voice/config` and `GET /voice/token?role=browser` |
| `ScriptProcessorNode` → PCM16 → `socket.send(binary)` | `room.localParticipant.publishTrack(localAudioTrack)` with `echoCancellation:true` |
| `socket.onmessage` parsing `speech_start/partial/final` | `room.on(RoomEvent.DataReceived, handler)` |
| Manual exponential backoff reconnect timer | `Room` reconnect built into SDK |
| `ws.send({type:'tts_start'})` from isMarkSpeaking subscription | `room.localParticipant.publishData(...)` |

**Key preservation: echo cancellation.**
The `livekit-client` SDK's `createLocalAudioTrack` accepts constraints:
```ts
createLocalAudioTrack({ echoCancellation: true, noiseSuppression: true, autoGainControl: true })
```
This preserves Layer 1 (browser AEC). Layers 2 (`BARGE_IN_RMS` gate via
`localTrack.muted = true`) and 3 (backend energy threshold) are unchanged.

**Mic level meter.**
The `micLevel` state (used by the PresenceEngine brain animation) is
maintained by attaching an `AnalyserNode` to the track's underlying
`MediaStream`:
```ts
const stream = new MediaStream([localAudioTrack.mediaStreamTrack]);
audioCtx.createMediaStreamSource(stream).connect(analyser);
```
Identical to the current implementation.

**`speechPlayer.ts` — bypassed on LiveKit path.**
LiveKit delivers MARK's audio as a standard `RemoteAudioTrack`, which the
SDK attaches to an `<audio>` element automatically. The manual PCM queue in
`speechPlayer.ts` is no longer needed on this path. It is kept but only
activated when `speechEngineUnavailable` is true (emergency browser-TTS
fallback — unchanged behaviour).

**`markStore.ts` — minimal gating.**
The binary audio frame handler (`case 'binary':` in the WebSocket message
loop) is guarded with `if (!livekitActive)` — when LiveKit is running, binary
PCM frames on `/ws` are ignored because the LiveKit track plays instead.

**Which files?**

| File | Change |
|---|---|
| `artifacts/mark-dashboard/src/hooks/use-voice.ts` | **Rewrite** transport section; keep all interruption + echo guard logic, replace WebSocket with LiveKit Room |
| `artifacts/mark-dashboard/src/hooks/use-livekit-config.ts` | **New.** Small hook to fetch `/voice/config` on mount |
| `artifacts/mark-dashboard/src/store/markStore.ts` | **+1 guard:** `if (!livekitActive)` around binary audio handler |
| `artifacts/mark-dashboard/src/lib/speechPlayer.ts` | **Kept** unchanged; bypassed on LiveKit path |
| `artifacts/mark-dashboard/package.json` | **+** `livekit-client` |

**Dependencies**
- Milestone 1 (token + config endpoints)
- Milestone 2 (MARK agent must be in the room)

**Risk: MEDIUM-HIGH** (highest risk in the roadmap — echo cancellation)

This is where the three-layer echo guard is most likely to regress if not
careful. The mitigation:
- `echoCancellation: true` explicitly in `createLocalAudioTrack` constraints
- `localTrack.muted = true` during MARK speaking (replaces `isMarkSpeakingRef`
  suppression in the ScriptProcessorNode callback)
- The backend energy threshold (Layer 3) is unchanged
- A 350ms post-speech holdoff before unmuting the local track (same as today)

Tab backgrounding: LiveKit's SDK continues publishing the audio track even
when the tab is hidden — this problem is eliminated without any extra code.

**Definition of Done**
- End-to-end voice works through LiveKit (mic → room → MARK → room → speaker)
- Barge-in stops MARK immediately (<150ms perceived latency)
- No echo loop at comfortable speaker volume
- `micLevel` animation still responds to real mic input
- Interim transcript still appears in the UI while speaking
- Tab background: voice does not drop when tab is hidden
- Network drop: SDK reconnects without user action
- Zero TypeScript errors

---

### Milestone 4 — Interruption & Half-Duplex Hardening

**Why are we doing this?**
Interruption and echo guard correctness are MARK's most important voice
properties. This is a dedicated verification and hardening pass — not a new
feature, but a commitment that the LiveKit path is at least as tight as the
WebSocket path.

**What changes?**

**Interruption timing analysis:**
Current path latency: VAD fires → `voice_websocket` (Python) → `interrupt()`
+ `task.cancel()` → sends `speech_start` JSON over `/ws/voice` → browser
→ `stopMarkSpeech()`. Total: ~1 network round-trip.

LiveKit path: VAD fires inside `MarkLiveKitAgent` (Python) → `interrupt()` +
`task.cancel()` → LiveKit data channel `speech_start` → browser → `stopMarkSpeech()`.
Total: ~1 network round-trip (same). LiveKit's data channel uses the same
WebRTC connection as the audio track, so no extra latency is introduced.

**Verify and document measured latency** (done during this milestone via
browser DevTools trace — no code change, just measurement and confirmation
that the LiveKit path meets the <150ms target).

**`localTrack.muted` gate timing:**
The 350ms post-speech holdoff before `localTrack.muted = false` is
implemented identically to the current `speakingHoldoffRef` pattern in
`use-voice.ts`. Verified to prevent room-reverb false-positives.

**One hardening code change:**
The MARK agent's `capture_frame` call checks the interrupt flag before
enqueuing each frame, matching the existing `_spoke_anything` guard in
`speech_runtime._speak_sentence`. This prevents a partial audio frame
published after interruption from being heard as a stutter.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_agent.py` | **+1 guard:** interrupt check before `capture_frame` |
| `artifacts/mark-dashboard/src/hooks/use-voice.ts` | **+1 comment + timing measurement** in data channel handler |

**Dependencies**
- Milestone 3

**Risk: LOW**
Logic is identical to today. The only code change is one guard in the agent.

**Definition of Done**
- Measured end-to-end interruption latency documented in code comment
- Speaking over MARK at normal volume stops him within 150ms (confirmed via
  manual testing)
- Speaking at very low volume (below barge-in threshold) while MARK speaks
  does NOT interrupt him (echo guard working)
- `localTrack.muted` toggling visible in LiveKit debug panel

---

### Milestone 5 — Persistent Sessions & Automatic Reconnection

**Why are we doing this?**
MARK is always alive. Opening the dashboard connects to him — it does not
create him. The room `mark-presence` exists before the browser arrives.

**What changes?**

**Persistent room identity:**
The room name `mark-presence` is a constant. The MARK agent joins it on
server startup and never voluntarily leaves. If the agent's connection drops
(network blip, LiveKit restart), it reconnects with backoff — independent
of whether any browser is connected.

**Per-participant VoiceSession:**
Rather than one shared `VoiceSession`, the agent maintains a map:
`{participant_identity → VoiceSession}`. When a participant joins, their
session is created. When they leave and rejoin, their session is reset
(matching the current behaviour where closing the tab and reopening resets
the VAD buffer). This supports a future where multiple browser tabs connect
simultaneously without their audio colliding.

**Browser reconnect:**
`Room.connect()` in `use-voice.ts` is called once. The `livekit-client` SDK
handles reconnection internally. On `RoomEvent.Reconnected`, the UI flashes
the mic indicator briefly (cosmetic only — voice resumes automatically).
The manual `voiceReconnectAttemptsRef` exponential backoff from `use-voice.ts`
is removed; the SDK's built-in reconnect replaces it.

**`mark_supervisor.py` restart interaction:**
If the LiveKit binary crashes and restarts (supervised by `mark_supervisor.py`),
the MARK Python agent will detect the connection drop and reconnect once
LiveKit is healthy again. The browser will also reconnect. This is the "MARK
is always alive" guarantee at the infrastructure level.

**Which files?**

| File | Change |
|---|---|
| `smartagent/server/livekit_agent.py` | **+** per-participant `VoiceSession` map; agent reconnect loop |
| `artifacts/mark-dashboard/src/hooks/use-voice.ts` | **Remove** manual reconnect backoff; handle `RoomEvent.Reconnected` |

**Dependencies**
- Milestone 4

**Risk: LOW**
LiveKit's reconnect is a first-class SDK feature. The per-participant session
map is a straightforward `dict` keyed by participant identity (a string).

**Definition of Done**
- Browser tab reload: voice resumes in <2s without any user action
- Network drop (simulated): SDK reconnects without page refresh
- MARK agent log shows exactly one `"Joined mark-presence"` line per server
  process (not one per browser connect)
- LiveKit binary restart: both agent and browser recover automatically

---

### Milestone 6 — Remove Old WebSocket Voice Transport

**Why are we doing this?**
Once LiveKit is confirmed working across multiple real sessions, the old
WebSocket voice path is dead weight. Dual-maintenance of two voice transports
adds risk and confusion.

**What changes?**

| What is removed | Where |
|---|---|
| `voice_websocket()` handler and its `@router.websocket("/ws/voice")` route | `smartagent/server/api.py` |
| `broadcast_bytes()` calls in `_speak_sentence` | `smartagent/server/speech_runtime.py` |
| `broadcast_bytes()` method itself (if no other callers) | `smartagent/server/websocket.py` |
| Binary audio frame handler (`case 'binary':`) | `artifacts/mark-dashboard/src/store/markStore.ts` |
| `voiceWsRef`, `voiceReconnectAttemptsRef`, WebSocket reconnect logic | `artifacts/mark-dashboard/src/hooks/use-voice.ts` |
| PCM queue logic in `SpeechPlayer` | `artifacts/mark-dashboard/src/lib/speechPlayer.ts` (file kept as emergency TTS wrapper stub) |

**What is kept:**
- `VoiceSession` and `voice_pipeline.py` — untouched throughout; still used
  by the LiveKit agent
- `tts_engine.py` — untouched throughout
- `speech_runtime.py` sentence buffering — only the delivery method changes
- `speechPlayer.ts` shell — kept as the emergency browser-TTS fallback wrapper

**Dependencies**
- Milestone 5 fully verified
- At least 48 hours of real-world usage on the LiveKit path with no reported
  voice regressions

**Risk: HIGH (by design — this is the irreversible step)**
Scheduled last for this reason. If a regression surfaces after removal, the
checkpoint rollback system is the recovery path, not manual re-implementation.

**Definition of Done**
- No `/ws/voice` route in the server
- No `ScriptProcessorNode` or manual PCM WebSocket code in the frontend
- Voice works exclusively through LiveKit
- All voice behaviours confirmed: interruption, echo guard, reconnect, mic
  level, interim transcripts, tab backgrounding
- Zero TypeScript errors
- Zero Python test regressions

---

## Dependency Graph

```
Milestone 0 — Binary, Keys, Supervision
      │  (no dependencies — starts here)
      │
      ▼
Milestone 1 — Token Service
      │
      ▼
Milestone 2 — MARK Backend LiveKit Agent
      │
      ▼
Milestone 3 — Frontend LiveKit Client
      │
      ▼
Milestone 4 — Interruption & Echo Guard Hardening
      │
      ▼
Milestone 5 — Persistent Sessions & Reconnection
      │
      ▼
Milestone 6 — Remove Old WebSocket Transport (irreversible)
```

Each milestone is reviewable and approvable independently.
Milestones 0–5 are fully reversible (old path stays live in parallel).
Milestone 6 is the commit point.

---

## New Files Summary

| File | Type | Purpose |
|---|---|---|
| `smartagent/server/livekit_setup.py` | Python | One-time key generation script |
| `smartagent/server/livekit_process.py` | Python | Binary download, config gen, `LiveKitProcess` class |
| `smartagent/server/mark_supervisor.py` | Python | Two-process supervisor (LiveKit + uvicorn) |
| `smartagent/server/livekit_token.py` | Python | JWT token generation (HS256, VideoGrant) |
| `smartagent/server/livekit_agent.py` | Python | `MarkLiveKitAgent` — room join, audio I/O |
| `artifacts/mark-dashboard/src/hooks/use-livekit-config.ts` | TS | Fetch `/voice/config` on mount |

---

## New Dependencies Summary

| Package | Where | Why |
|---|---|---|
| `livekit` | `requirements.minimal.txt` | Python Room SDK — audio track I/O |
| `livekit-client` | `artifacts/mark-dashboard/package.json` | Browser SDK — room connect, track pub/sub |

No new Python dependency for token generation — `pyjwt` is already in
`requirements.minimal.txt` and covers the HS256 VideoGrant format.

---

## Files Explicitly Not Changed by This Roadmap

```
smartagent/brain/          — zero changes
smartagent/mind/           — zero changes
smartagent/memory/         — zero changes
smartagent/llm/            — zero changes
smartagent/identity/       — zero changes
smartagent/server/voice_pipeline.py   — zero changes (VoiceSession used by LiveKit agent)
smartagent/server/tts_engine.py       — zero changes (Kokoro unchanged)
smartagent/server/watchdog.py         — zero changes (kept, not replaced)
```

---

## Estimated Effort

| Milestone | Estimate |
|---|---|
| M0 Binary, Keys, Supervision | ~4h |
| M1 Token Service | ~1h |
| M2 MARK Backend LiveKit Agent | ~5h |
| M3 Frontend LiveKit Client | ~5h |
| M4 Interruption Hardening | ~2h |
| M5 Persistent Sessions | ~2h |
| M6 Remove Old Transport | ~2h |
| **Total** | **~21h** |

---

## Risk Summary

| Risk | Likelihood | Mitigation |
|---|---|---|
| Binary download fails (no internet / GitHub rate limit) | Low | Cached after first download; manual install path documented |
| Port 7880 already in use on Replit | Low | `mark_supervisor.py` checks port before starting; configurable via `LIVEKIT_PORT` |
| LiveKit Python SDK asyncio loop conflict | Low | Isolated thread + `run_coroutine_threadsafe` (proven pattern in this codebase) |
| Echo loop through LiveKit AEC | Medium | `echoCancellation:true` in track constraints; all three backend guard layers unchanged |
| Regression on removal (M6) | Low | M6 follows 48h verified operation; checkpoint rollback available |
| Future LiveKit binary version incompatibility | Low | Pin binary version in `livekit_process.py`; upgrade is deliberate |

---

*Awaiting approval. No code has been modified. Implementation begins with
Milestone 0 only, then pauses for review before proceeding to M1.*
