# Session Handoff — MARK-OS

**Purpose:** a shared, current account of what's actually been built and verified, for whichever AI (Claude or Replit Agent) picks up this project next, and for the owner to review at a glance. Written so neither AI has to guess what the other already did. Supersede this file with a newer one rather than letting it silently go stale — don't edit around it.

This is not a roadmap or a spec — those live in `docs/canonical/`. This is a record of real, verified work and real, disclosed gaps.

---

## What's real and verified right now

### Dashboard ownership
- **MARK's Home is the default view**, not the engineering dashboard. The Engineering Workspace (workers, timeline, git, terminal) is one explicit click away, not the boot screen. (`artifacts/mark-dashboard/src/components/MarkHome.tsx`, `Dashboard.tsx`)
- **MARK's real self-state drives the UI** — mode, confidence, health come from `agent.mind` (a real, persistent `ExecutiveController`), pushed over the WebSocket on real state transitions (`SelfStateChanged`), not polled or faked.

### Presence Engine (3D visualization) — ⚠️ read before touching this file
- **Current design (owner-approved, commit `17741ef`): a glass orb half-filled with glowing green liquid** — a rippling surface, rising bubbles, a bright glossy highlight, radial glow background. Built against a reference photo the owner supplied directly. (`artifacts/mark-dashboard/src/components/PresenceEngine.tsx`)
- **This file collided once already**: Replit Agent's commits `2b8a65c`→`06f388a` (2026-07-20) replaced a Claude-built version with a different cyan/blue neural-brain-with-lightning-core design while a newer glass-orb version was being tuned live against the dev server and hadn't been committed yet — so it silently disappeared and the owner had to ask twice before the mechanism was found. If you're about to redesign this component, **check with the owner first** (or at minimum check the latest commit message on this file) rather than assuming the last-authored version is stale — the owner explicitly chose the glass-orb direction after seeing both.
- Every visual signal (liquid color/glow, ripple amplitude, bubble rise speed) is driven by real data: `agent.mind`'s actual mode/confidence, real WebSocket timeline events (a real event sends one real ripple pulse + resets a few bubbles), real mic amplitude while listening. No `setInterval`/`setTimeout` anywhere in the file.
- Lesson learned the hard way: three.js `MeshPhysicalMaterial.transmission` (real GPU refraction) does NOT reliably composite with other alpha-blended objects behind it — the background-capture pass only grabs opaque geometry. The glass shell here uses plain alpha blending instead; don't reach for `transmission` on nested-transparency scenes without testing it renders what's behind it.

### Voice pipeline — backend-owned, not a browser feature
- **Listening**: the browser streams raw mic PCM continuously (including while MARK is talking — required for real interruption) to `/ws/voice`, which runs it through real local Silero VAD + Faster-Whisper (`smartagent/server/voice_pipeline.py`). No browser `SpeechRecognition` on the primary path.
- **Speaking**: MARK's replies are synthesized by a real local Kokoro-82M TTS engine (`smartagent/server/tts_engine.py`, via `kokoro-onnx` — the official `kokoro` package needs Python <3.13, this server runs 3.13, so the ONNX port was used instead, verified working) and streamed as binary PCM frames over the same `/ws` connection everything else uses. No browser `speechSynthesis` on the primary path — it's kept only as an explicit last-resort fallback if the backend engine fails to initialize (`SpeechEngineUnavailable` event).
- **Interruption**: the moment VAD detects the owner speaking, the frontend stops playback locally (no round-trip) and the backend independently stops generating further speech (`smartagent/server/speech_runtime.py`).
- **A real, measured performance fix**: synthesis on this CPU-only machine runs slower than real-time (RTF ~1.5–4x). Speech synthesis was moved off the LLM token-generation thread onto a dedicated background worker queue, so a slow TTS call never stalls MARK's text output — verified directly (`on_token()` returns in ~0.1ms regardless of synthesis time).
- 12 new backend tests, real model inference, no mocks, all passing. Full backend suite: 3756 passed, same 9 pre-existing unrelated failures, zero regressions from this work.
- **Disclosed gap**: full live voice-to-voice interruption (talking over MARK with a real microphone) has not been tested with an actual human voice in this environment — the pipeline is verified at the unit/integration level and via one real end-to-end text-triggered test (real audio chunks confirmed arriving and playing), not via a live conversation.

### Connection reliability
- WebSocket reconnect now backs off from 250ms instead of a flat 3s wait, and the app forces an immediate reconnect attempt when the tab regains focus or the network comes back online. Verified by killing and restarting the backend process live and watching the dashboard recover without a page reload.

### Two real, confirmed backend bugs found and fixed
1. **Wrong model name.** `.mark_provider_state.json` had Ollama configured to use a model (`"my-model"`) that was never actually pulled — only `llama3.2:3b` exists on this machine. Every chat call was failing and falling back to a hardcoded canned sentence every single time — this was the direct cause of MARK repeating the identical response to dozens of different messages, visible in the owner's own testing transcript. Fixed by pointing the config at the model that actually exists.
2. **Unbounded context window.** With no `num_ctx` specified, Ollama was loading the model at its max advertised context (131,072 tokens) — ~17GB RAM, 100% CPU, over a minute with zero output for an ordinary "say hello." Capped at 8192 in `smartagent/models/providers/ollama_provider.py::_build_options()`. Verified directly against the Ollama API: unfixed, 100+s with no output; fixed, ~3.25s for a real, coherent reply.
3. Not fixed, disclosed: GitHub Models provider is failing with `Unauthorized` — the token is likely expired. Separate credentials issue, needs the owner to provide a working token or accept the Ollama→NVIDIA fallback chain as-is.

---

## What's broken or not yet built (disclosed, not hidden)

This list is grounded in **`docs/BRAIN_RECONSTRUCTION_AUDIT.md`** — a full comparison of MARK's intended architecture (reconstructed from every canonical document) against the current implementation. Read that file for full detail and evidence; summary here:

- **The Conversation/Mission routing gate misfires on ordinary language.** `dev_pipeline.py::classify_intent()` routes any message containing common words like "make," "build," "help," "run" into the full engineering worker pipeline (Engineer/QA/Reviewer/Security/Docs) unless the message is an exact greeting match — witnessed directly this session (a plainly conversational message triggered a full "Milestone 1/1... 0 files touched" worker run), and independently confirmed by MARK's own reflection vault logging raw voice filler as "completed executive tasks."
- **Memory is fragmented across at least 10 separate, disconnected store classes** (`workspace/`, `reflection/`, `server/engineering_memory.py`, `project_memory/`, `mind/working_memory/`, `memory/`, `executive/workers/memory_worker.py`, `conversation_store.py`) rather than one coherent architecture.
- **The reflection/self-improvement system is stub-quality.** MARK's own generated reflection vault (`vault/`) shows a repeated task logged as both "completed, 55%" and "failed: unknown error" for the same event, nine times, never reconciled; confidence/score values take only two possible values (55% or 100%) across the entire corpus regardless of actual content.
- **The Owner Philosophy documents (`MARK_DNA.md`, `MARK_EVOLUTION.md`, `MARK_WORLDVIEW.md`, `MASTER_BLUEPRINT.md`, `CLAUDE_ENGINEER_BOOTSTRAP.md`) are real and substantive** — an earlier pass in this same session wrongly reported them as empty (a `wc -l` line-count check gave a false negative on files with no line breaks). They exist and are consistent with the rest of the canon. What's actually missing is narrower: no code queries them at any pipeline stage, and all five are formatted as one unreadable giant line each with no line breaks — a real but much smaller gap than "the philosophy doesn't exist."
- **No continuous background loop exists.** MARK only computes anything when a request arrives — the "always alive, never turns off" continuous-presence philosophy is not yet real at the runtime level, even though the Presence Engine visually looks alive.
- **This entire list is currently gated on owner approval** — `docs/BRAIN_RECONSTRUCTION_AUDIT.md` is awaiting review before any structural implementation against these findings begins. Frontend/UX work is not blocked by this gate unless it touches these specific systems.

---

## For Replit Agent specifically

Your lane per `docs/canonical/PROJECT_CONTEXT.md` §42 and `docs/canonical/REPLIT_BOOTSTRAP.md` is landing page, dashboard visual design, UX, frontend implementation, animations. Things worth knowing before touching the frontend:

- The dashboard is served two ways: a pre-built static bundle (`artifacts/mark-dashboard/dist/public`, what the FastAPI backend actually serves) and live Vite source (`pnpm run dev` in `artifacts/mark-dashboard/`). Changes to source don't appear until rebuilt — `pnpm run build:watch` keeps the served bundle current during active work.
- The WebSocket contract (`/ws` for events + audio, `/ws/voice` for mic streaming) is real and tested — see `markStore.ts` for the full event vocabulary before changing how the frontend consumes it.
- `PresenceEngine.tsx`'s real-data-only rule is a hard constraint from the owner, repeated multiple times this session: every visual must trace back to genuine backend state or a real WebSocket event. No decorative timers.
