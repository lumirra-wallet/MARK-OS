---
name: MARK Brain Foundation
description: Architecture, design decisions, and wiring for the Brain Foundation layer (Tasks #5 and #6) — memory layers, emotional state, brain events, cognitive timeline, and SVG neural presence.
---

## What was built

### Backend (smartagent/)
- `server/brain_events.py` — async helpers that broadcast typed `BrainEvent` events over the existing `/ws` WebSocket. Every brain event the dashboard shows must come from here. Event names: `thinking_started`, `thinking_finished`, `memory_written`, `knowledge_created`, `emotion_changed`, `voice_started`, `voice_interrupted`, `voice_finished`, `cognitive_event`, `reflection_complete`.
- `memory/layers/episodic.py` — JSON on disk, `~/.cache/mark/memory/episodic/YYYY-MM-DD.json`. `store()`, `recent(n)`, `relevant(query, n)`, `count_today()`.
- `memory/layers/semantic.py` — single JSON file `~/.cache/mark/memory/semantic.json`. `store(fact)`, `relevant(query, n)`, `count()`.
- `memory/layers/owner.py` — single JSON file `~/.cache/mark/memory/owner.json`. `extract_and_update(text)` auto-extracts preference/habit signals using regex. `profile_summary()` for system prompt injection.
- `mind/emotion/emotional_state.py` — `EmotionalStateEngine` singleton `emotional_state_engine`. 5 states: neutral/curious/focused/satisfied/uncertain/frustrated. Context-derived (no timers). TTL of 120s decays back to neutral. `on_knowledge_created()`, `on_complex_task_started()`, `on_success()`, `on_needs_clarification()`, `on_failure()`.
- `server/learning_pipeline.py` — `run(goal, reply, succeeded, emotional_state, knowledge_manager)` — stores episodic memory, extracts owner signals, proposes concepts. Called as background asyncio task.
- `server/self_state.py` — `snapshot()` now includes `emotional_state`, `emotional_reason`, `memory_activity` (episodic_today, semantic_total, owner_attributes).
- `server/api.py` changes:
  - `_brain` and `_emotion` imported at module level (try/except for safety)
  - `_current_inference_task` module global — tracks the running chat inference `asyncio.Task` so `voice_websocket` can cancel it on `speech_start`
  - Chat path emits `thinking_started` before inference, `thinking_finished` after
  - `voice_websocket` on `speech_start`: cancels `_current_inference_task` + emits `voice_interrupted`
  - Post-run: `_post_learning()` background task stores episodic memory, proposes concepts
  - Finally block: `emotional_state_engine` updated from real run outcome, emits `emotion_changed`

### Frontend (artifacts/mark-dashboard/)
- `components/NeuralPresence.tsx` — pure SVG neural animation (no Three.js). Always works, no GPU needed. Driven by: `running`, `isMarkSpeaking`, `isListening`, `emotionalState`, `cognitiveEvents`. Core breathes, rings activate on inference/memory/speech, 6 orbiting nodes flash on cognitive events. Hue shifts per emotional state.
- `components/CognitiveTimeline.tsx` — shows last 8 cognitive events (newest first), with icon + label + detail + age. Each entry from a real `BrainEvent`, never fabricated.
- `components/MarkHome.tsx` — living presence text (changes based on actual state: "Listening.", "Reviewing recent memories.", "Something caught my attention." etc.). Emotional state badge (color-coded, only shown for non-neutral states). Cognitive Timeline panel on the right edge (collapsible).
- `components/PresenceEngine.tsx` — renders `NeuralPresence` when WebGL fails (catch block now calls `setWebGLAvailable(false)` instead of returning silently).
- `store/markStore.ts` — new types: `CognitiveEvent`, `MemoryActivityEntry`. New state: `cognitiveEvents[]`, `emotionalState`, `emotionalReason`, `memoryActivity[]`, `knowledgeGrowth`. New WS case `BrainEvent` handles all 10 brain event subtypes.

## Key design decisions

**Why:** Every visible state in the dashboard must originate from a real brain event. No counters increment speculatively.

**Zustand pattern:** Never use object selectors `useMarkStore(s => ({ ...fields }))` — they create a new object every render and cause infinite update loops. Use individual `useMarkStore(s => s.field)` calls.

**Vite Fast Refresh:** Don't mix component exports + hook exports in the same file. Causes HMR invalidation.

**Inference cancellation:** `_current_inference_task` is a module-level global. Inside `_run()` (a nested async function), `global _current_inference_task` declaration is required for assignment. `voice_websocket` can read it without `global`, but also uses `global` for clarity.

**Memory storage:** `~/.cache/mark/memory/` — persistent across workspace changes. Env var `MARK_MEMORY_DIR` overrides.

**Emotional state TTL:** 120s — states naturally decay to neutral if nothing re-triggers them.
