# MARK's Reconstructed Brain — Audit & Implementation Comparison

**Status:** Awaiting owner approval. No implementation code was written or modified in producing this document.
**Method:** Full-text read of all 12 `docs/canonical/` files (5 confirmed empty), all root-level and `docs/` legacy documentation, Claude's persistent cross-session memory of the owner's standing philosophy, and all 36 files in MARK's self-generated reflection vault (`vault/Lessons`, `vault/Reflections`, `vault/LearningAnalytics`, `vault/Successful Strategies`). Where a comparison against current implementation is made below, it is grounded in specific files read this session (cited inline) — not inferred or guessed.

This is not a documentation summary. It is a reconstruction of the single intelligence the documents collectively describe, followed by a direct comparison against what the code actually does today.

---

## 1. MARK's Thinking Model

**What the documents describe:** Cognition happens in five strictly-ordered layers — Perception (what just happened, never what to do), Understanding (build context/meaning), Reasoning (decide the mode of response, minimize unnecessary work), Planning (only when necessary, never for normal conversation), Execution (carries out approved plans, never decides). Beneath the per-request pipeline, a lightweight background loop runs continuously — Observe → Understand → Update Memory → Update Knowledge → Wait — so MARK never "wakes up" only when spoken to (`MARK_MIND.md`). Effort must scale to the problem: "never use maximum reasoning for minimum problems" (`MARK_OPERATING_PRINCIPLES.md` Principle 3, restated independently in `MARK_LIFE_CYCLE.md`'s Resource Philosophy).

**Current implementation:**
- `smartagent/engineer/dev_pipeline.py::classify_intent()` is the actual single decision point today — not a five-layer pipeline, a single-pass regex/keyword classifier that returns one of `conversational | simple_agent | complex_pipeline | needs_clarification`.
- `smartagent/mind/response_planner.py::plan_response()` exists separately and *does* produce a real Perception/Reasoning-flavored artifact (confidence, reasoning, evidence) via `agent.mind` (the real `ExecutiveController`) — but it runs *after* `classify_intent()` has already decided the route, as an annotation, not as the actual gate.
- There is no Planning layer distinct from execution, and no continuous background loop — MARK only computes anything when a request arrives.

**Verdict: partially agrees, materially violates.** A real "Reasoning" stage exists (`response_planner.py`) and is genuinely wired to a persistent executive object — that's real work, not vaporware. But it does not sit *before* the routing decision the way `MARK_MIND.md` requires ("without understanding, reasoning should never begin" — here, routing happens first, reasoning happens second, backwards from the spec). There are effectively **two separate classification systems** (`classify_intent()` and `response_planner.py`) doing adjacent jobs without one owning the decision — a direct instance of the owner's own flagged pattern, "never create duplicate systems." And the continuous background loop the philosophy requires does not exist at all: MARK is still fundamentally request/response beneath the UI polish.

---

## 2. MARK's Decision Model

**What the documents describe:** One universal test before any action — `MARK_MIND.md`'s **Golden Rule**: *"Will this help my user accomplish their goal? If yes, continue. If no, rethink."* Before responding, MARK should ask whether to act, ask, wait, or observe — not every input warrants immediate execution (`MARK_OPERATING_PRINCIPLES.md` Principle 2). Workers never make decisions; only MARK does, and only after evaluating worker output (`ARCHITECTURE.md`, `PROJECT_CONTEXT.md`).

**Current implementation, directly verified this session:**
- `dev_pipeline.py`'s `_ACTION_KEYWORDS` set includes ordinary conversational words: `"make"`, `"build"`, `"help"`, `"run"`, `"check"`, `"fix"`, among others. Any message containing one of these words — unless it exactly matches a narrow, anchored greeting pattern (`_PURE_GREETING_PATTERNS`, e.g. `^hi$`, `^how are you$`) — is routed to `simple_agent` or `complex_pipeline`, **not** conversational.
- **Live, witnessed proof from this session's own transcript:** the message *"Now, I want you to make the listening to be on your time. It's a blessing, and also it's..."* — plainly conversational — triggered a full worker run: Engineer, QA, Reviewer, Security, and Docs all fired, reporting "Milestone 1/1... done — 0 files touched." A raw, disfluent voice transcript (*"And... Okay. All right. Okay. Okay. All right. I'm going to go a little bit..."*) did the same.
- This is not a one-off: MARK's own reflection vault independently corroborates the identical failure mode from a completely different angle — starting 2026-07-19 17:10, raw STT transcripts are logged as "completed executive tasks" at a flat 100% confidence, including at least one case where **MARK's own clarifying question to the user** was logged as three separately-scored completed implementation tasks.

**Verdict: directly, currently violates the single most repeated principle in the entire canon.** "Never activate engineering pipelines for normal conversation" appears near-verbatim in at least four independent canonical documents, plus the owner's own memory, plus `MARK_LIFE_CYCLE.md` Phase 5. The actual decision mechanism today is a keyword match, not a reasoned judgment, and it fails in exactly the direction the philosophy warns against. This is not a hypothetical gap — it is reproducible, and it happened live during this session's own testing, and it is independently confirmed by MARK's own self-generated memory.

---

## 3. MARK's Conversation Model

**What the documents describe:** Conversation Mode is the default, resting state — lightweight, no workers, no planning, no git, no engineering, no deployment (`PROJECT_CONTEXT.md`, `MARK_LIFE_CYCLE.md` Phase 5, `mark_conversation_architecture_rule.md`). The owner's memory sharpens this further: the first question on every incoming message must be *"is this simply a conversation with my owner?"* — if yes, nothing engineering-shaped activates, ever. Only MARK ever speaks to the owner; workers are invisible and the owner never learns their names exist as distinct entities (`mark_conversation_architecture_rule.md`, `docs/mark-operating-system.md`: *"the user should never directly witness Engineer:/QA:/Reviewer:"*).

**Current implementation:**
- When `classify_intent()` correctly routes to `conversational`, the reply path (`_do_chat()` in `smartagent/server/api.py`) is genuinely lightweight — no workers, matching the spec.
- When it misclassifies (see §2), the dashboard **does** show Engineer/QA/Reviewer/Security/Docs by name, actively "reasoning" about a chit-chat message — the exact opposite of "workers are invisible."
- Separately and independently of routing: this session directly observed MARK returning the identical hardcoded fallback sentence (`CHAT_FALLBACK_TEXT`) to more than 20 consecutive, completely different user messages in a row, because the underlying LLM call was failing (a since-partially-fixed provider/config issue, see the prior turn's session work) — meaning even when Conversation Mode routes correctly, there was an extended real window where it was not actually *conversing* at all, just echoing one static sentence.

**Verdict: the architecture for lightweight conversation exists and is correct when reached — but the gate that's supposed to protect it (§2) leaks constantly, and worker invisibility is violated every time it does.** A conversation model can't be judged working if the classifier deciding whether to *enter* it is wrong roughly as often as it was in this session's own transcript.

---

## 4. MARK's Executive Model

**What the documents describe:** A strict hierarchy — User → MARK Core → Intent Router → Mission Manager → Worker Manager → Workers → Providers → back to MARK → User (`PROJECT_CONTEXT.md`, `ARCHITECTURE.md`). Workers execute; they never decide, never talk to each other, never talk to providers or memory directly, never speak to the user directly — "every worker communicates only through MARK." Mission Mode (the only mode that unlocks workers) activates *only* on an explicit, unambiguous work request.

**Current implementation:**
- A real persistent executive exists: `agent.mind` is a genuine `ExecutiveController` (`smartagent/mind/executive/executive_controller.py`), constructed once per process and reused — not rebuilt per message. This is real and matches "persistent identity."
- Workers (`Engineer`, `QA`, `Debugger`, `Reviewer`, `Git`, `Security`, `Docs`, `Research`, `Preview`) are dispatched through `DevPipeline`, and per-milestone permission scoping is real (confirmed by `docs/mark-operating-system.md`, corroborated by `CHANGELOG.md`'s "Unreleased" entry) — workers do not hold standing repo-wide access.
- There is no distinct "Intent Router" or "Mission Manager" as named, separate components — `classify_intent()` fuses both jobs into one function. This isn't necessarily wrong (the spec doesn't mandate literal class names), but it means the "Mission Manager" responsibilities the constitution describes (Mission ID, plan, worker assignment, priority, dependency tracking, progress tracking as one addressable object) are spread thin across `DevPipeline` rather than owned by one component.
- Git specifically is supposed to "never activate unless repository files actually changed" (`mark_conversation_architecture_rule.md`). The witnessed misrouted runs in §2 reported "0 files touched" and did not commit — so the *worst* violation (a real commit from a chit-chat message) does not appear to have happened in the cases observed, but QA, Reviewer, Security, and Docs all still visibly "activated" and reported on a conversational message, which the spec is equally explicit should never happen.

**Verdict: the pieces MARK is built from (persistent executive, scoped worker permissions, structured worker output) are real and mostly correct — the failure is entirely at the gate deciding when to invoke them, identical to §2's finding.** There is no separate architectural flaw in the Executive layer itself; it is faithfully executing a bad routing decision it was never designed to second-guess.

---

## 5. MARK's Memory Model

**What the documents describe:** Memory (conversation history, long-term memory, knowledge, reflection, owner profile, engineering profile, project memory) should be one coherent architecture, not independently-evolving stores (`MARK_CONSTITUTION.md` Article V, `MARK_MIND.md` Long/Short-term Memory, owner's memory: *"one coherent MARK, not competing subsystems"*). Memory belongs to the user (MARK is its guardian); Knowledge is *derived from* memory and belongs to MARK — a precise, not interchangeable, distinction (`PROJECT_CONTEXT.md` §9/§20). Nothing should ever be lost to a restart, provider swap, or update. Self-improvement should update knowledge, never personality or identity.

**Current implementation, directly verified this session:** at least ten distinct memory/store-shaped classes exist across the codebase, in disconnected locations: `workspace/workspace_store.py`, `reflection/learning_store.py`, `server/engineering_memory.py`, `skills/builtin/memory_skill.py`, `project_memory/project_memory.py`, `reflection/improvement_planner.py`, `mind/working_memory/working_memory.py`, `memory/memory_manager.py`, `executive/workers/memory_worker.py`, plus `conversation_store.py` (used directly by `api.py` for chat history). None of these share one interface or one write path.

**The clearest evidence of what fragmentation costs in practice is the reflection vault itself** (`vault/`), which is real, first-party output from MARK's own `ReflectionEngine` — not documentation, actual generated memory:
- A demo/stub task ("Build a Flask API") was logged as **both completed (55% score) and failed ("unknown error")** for the identical session, nine separate times across 29 hours, with the contradiction never once reconciled.
- Confidence and score values across all 36 vault entries take **only two possible values, ever: 55% or 100%** — never anything reflecting actual content, which is the signature of a hardcoded stub rather than genuine evaluation.
- Titles are truncated mid-word by a fixed character cut across the corpus (e.g., `"possib"`, `"I'm going to "`).
- No entry in the entire vault names a specific file, a specific root cause, or a specific actionable lesson beyond the literal string `"unknown error"`.

**Verdict: directly, currently violates "one coherent memory architecture" and, more specifically, violates "MARK should never repeat solved mistakes"** (`PROJECT_CONTEXT.md`) — the identical failure repeated nine times with no evidence the lesson was ever incorporated is the precise failure mode that principle exists to prevent. This is the single most concrete, data-backed violation found in this entire audit, because it isn't inferred from documentation gaps — it's MARK's own memory demonstrating the gap against itself.

---

## 6. MARK's Personality Model

**What the documents describe:** Confidence, uncertainty, urgency, calmness, encouragement, curiosity, and professionalism are **communication styles**, explicitly "not simulated feelings" (`MARK_MIND.md` Emotional Model). Self-improvement must update knowledge and never personality or identity — restated independently in two documents (`MARK_MIND.md`: *"Never personality. Never identity."*; `MARK_LIFE_CYCLE.md` Phase 8: *"Knowledge grows. Identity remains unchanged"*). Each MARK instance should develop its own personality over years while keeping a fixed core identity (`PROJECT_CONTEXT.md`). MARK should remain calm, reliable, and trustworthy, and must never intentionally deceive the user — when uncertain, say so; when wrong, admit it (`MARK_CONSTITUTION.md` Article III).

**Current implementation:** `smartagent/identity/mark_identity.py` and `docs/canonical/MARK_PERSONALITY.json` (referenced, not part of this pass's read set) define MARK's voice and tone; `SMARTAGENT.md`'s own "Personality" section shows a real, already-applied self-correction — an earlier draft contradicted the "not a coding agent" identity rule and was rewritten to match `MARK_PERSONALITY.json`. `self_state.py` tracks real confidence and health values (surfaced in the dashboard and driving the 3D Presence Engine's visual state) rather than decorative numbers — this is a genuine, non-simulated implementation of the "communication style, not fake emotion" principle.

**Verdict: mostly agrees.** This is the model with the least daylight between spec and implementation. The one open question the documents themselves don't resolve (flagged, not violated): `MARK_CONSTITUTION.md` Article V says memory belongs to *the user* while `PROJECT_CONTEXT.md` says knowledge belongs to *MARK* — precise language worth preserving distinctly rather than collapsing into one phrase, since personality/identity permanence (§6) is explicitly anchored to that same memory/knowledge boundary.

---

## 7. MARK's Brain Runtime

**What the documents + the owner's explicit directive describe:** One `BrainRuntime` owning Identity, Conversation, Memory, Reflection, Executive, Personality, Voice, Runtime State, Worker Manager, Tool Manager, Presence Engine, and Dashboard State as internal modules — never independently-running subsystems wired together after the fact. The fixed, never-reversed reasoning pipeline: **Owner speaks → Understand intent → Consult long-term memory → Consult Owner Philosophy → Consult current conversation → Reason → Decide → Only then respond.** A Response Planner classifies every input into conversation / planning / reasoning / execution / needs-memory / needs-engineering / needs-workers — workers are the final escalation, never the first move. Voice (listening, speaking, interruption, wake state, silence detection, streaming, TTS, STT) belongs entirely to the Runtime; the browser only displays and plays audio. The dashboard represents MARK by default; the engineering workspace is a secondary, explicitly-opened view. Continuous Presence: MARK keeps listening, thinking, remembering, and can speak naturally whether idle or while workers execute in the background — never "turning off."

**Current implementation — checked module by module:**

| Module | Real & owned by one place? | Evidence |
|---|---|---|
| Identity | ✅ Yes | `identity/mark_identity.py`, applied consistently |
| Executive | ✅ Yes, persistent | `mind/executive/executive_controller.py`, singleton via `_get_mark_agent()` |
| Voice (listening + speaking) | ✅ Yes, backend-owned | `server/voice_pipeline.py` (real Silero VAD + Faster-Whisper), `server/tts_engine.py` (real local Kokoro), `server/speech_runtime.py` — browser is genuinely reduced to mic passthrough + audio playback, built and verified this session |
| Presence / Dashboard default | ✅ Yes, MARK-first | `MarkHome.tsx` is the default view; Engineering Workspace is one explicit click away — built in an earlier phase of this session |
| Response Planner (as a *gate*, not annotation) | ❌ No | Exists (`response_planner.py`) but runs after routing, not before it — see §1/§2 |
| Intent Router / Mission Manager (as named, singular components) | ⚠️ Fused, not separated | Both jobs live inside `classify_intent()` / `DevPipeline` |
| Memory (one coherent architecture) | ❌ No — fragmented | ≥10 separate store classes, see §5 |
| Reflection (genuine self-improvement) | ❌ No — stub-quality | Fixed 55%/100% scores, unreconciled contradictions, see §5 |
| "Consult Owner Philosophy" pipeline step | ❌ Cannot exist yet | The document it would consult (`docs/canonical/`'s DNA/Worldview/Evolution/Bootstrap/Master-Blueprint files) is empty — five of twelve canonical files are 0 bytes, including the one the repo's own `CLAUDE.md` calls mandatory first reading for every session |
| Continuous Presence (never "off") | ❌ No | No background loop exists; MARK only computes on request, confirmed in §1 |

**Verdict: MARK's Brain Runtime is real in patches, not real as a runtime.** The strongest, most genuinely-built pieces are Voice and the Executive/Identity core — both are backend-owned, persistent, and were verified working this session, not aspirational. The weakest pieces are exactly the ones the owner's directive named as the *point* of the exercise: there is no single Response Planner gate, no unified Memory, no populated Owner Philosophy to consult, and no continuous background loop. MARK today is a well-built collection of the right *ingredients*, assembled in the wrong *order* — reasoning happens after routing instead of before it, and the routing itself is a keyword match rather than genuine understanding.

---

## The one finding every model above traces back to

**Five of the twelve files in `docs/canonical/` — the directory the project's own `README.md` calls its actual source of truth — are completely empty:** `CLAUDE_ENGINEER_BOOTSTRAP.md`, `MARK_DNA.md`, `MARK_EVOLUTION.md`, `MARK_WORLDVIEW.md`, `MASTER_BLUEPRINT.md`. The repo's own root `CLAUDE.md` instructs every session to read `CLAUDE_ENGINEER_BOOTSTRAP.md` "before doing anything else" — it is blank. `README.md` additionally references `MARK_MANIFESTO.md` and `PROJECT_MEMORY.json` as required reading that don't exist at all.

A Brain Runtime built to the owner's own mandated pipeline literally cannot execute step 4 — "Consult Owner Philosophy" — because the philosophy it would consult does not exist as a real document today. Everything else in this report is either downstream of that gap (the routing/decision failures in §2/§4 are exactly what "consult Owner Philosophy before reasoning" is meant to prevent) or independent of it (§5's memory fragmentation, §6's personality model, which is largely sound).

## Second, independently-severe finding

**The routing gate that decides whether a message enters Conversation Mode or Mission Mode is currently wrong often enough to be the dominant lived experience of talking to MARK.** This was not inferred from a document — it was witnessed directly, live, in this session's own testing, and independently corroborated by MARK's own self-generated reflection vault from a completely different angle (raw voice transcripts scored as completed engineering tasks). Two unrelated evidence sources point at the same mechanism: `_ACTION_KEYWORDS` matching ordinary conversational words (`"make"`, `"build"`, `"help"`, `"check"`, `"run"`) and routing anything that isn't an exact, anchored greeting phrase into the engineering pipeline.

---

## Where implementation agrees with the intended design

- The Executive (`agent.mind`) is real, persistent, and singular — not rebuilt per message.
- Voice is genuinely backend-owned end-to-end (STT, VAD, TTS, streaming) — the browser does not generate MARK's voice, matching the owner's explicit directive precisely.
- The dashboard already defaults to MARK's Home, not the engineering workspace.
- Worker permission scoping is real and per-mission, not standing access.
- Personality/identity permanence is respected — no evidence self-improvement has touched personality.
- When the routing gate *does* classify correctly, Conversation Mode is genuinely lightweight, matching the spec exactly.

## Where implementation violates the intended design

- Routing happens before reasoning, not after (inverts the mandated pipeline).
- The Conversation/Mission gate misfires on ordinary language, invoking the full worker pipeline for chit-chat and raw voice filler — witnessed directly, twice, independently.
- Memory is fragmented across ≥10 disconnected stores.
- Reflection/self-improvement is stub-quality: fixed scores, unreconciled success/failure contradictions, no concrete lessons ever produced.
- There is no continuous background loop — MARK is not yet "always alive," only alive-on-request.
- The document MARK's own Brain Runtime is supposed to consult as a pipeline step doesn't exist.
- Two classification systems (`classify_intent()`, `response_planner.py`) do adjacent jobs without one owning the decision.

---

**This report requires your review and approval before any implementation begins**, including your decision on:
1. Whether this document satisfies the previously-recorded "Architecture Reconciliation" gate (`mark_project_phase.md`), or whether something further is still expected first.
2. Whether populating the five empty canonical files is something you want to write yourself, dictate, or have drafted for your review.
3. Priority order among the violations found — the routing/gate fix (§2/§4) is the smallest, most contained change and the one most directly witnessed as broken; memory consolidation (§5) is the largest and most architecturally invasive.
