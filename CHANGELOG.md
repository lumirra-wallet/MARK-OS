# Changelog

All notable changes to SmartAgent are documented here. This project uses
[Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`), though
while the project is pre-1.0 every release may include breaking changes as
the architecture is still settling.

## [Unreleased]

## Milestone 11 Phase 1 — Executive Framework

### Overview
Gives MARK an "executive brain" — a goal-driven orchestration layer that
decomposes goals into task plans, manages a dependency-aware task graph,
queues tasks for execution, and runs them through a synchronous scheduler.
No AI is invoked in Phase 1.  All workers are stubs.

### New package: `smartagent/executive/`

| Module | Purpose |
| --- | --- |
| `task.py` | `Task` dataclass + `TaskStatus` / `TaskType` enums |
| `task_graph.py` | Directed acyclic task graph with topological sort |
| `task_queue.py` | FIFO queue for ready-to-execute tasks |
| `execution_state.py` | `ExecutionState` enum for full-run lifecycle |
| `execution_context.py` | Live state of one goal-execution run |
| `planner.py` | Rule-based goal decomposition (5 templates, keyword routing) |
| `worker_registry.py` | Registry mapping task types to worker classes |
| `scheduler.py` | Synchronous dependency-aware task scheduler |
| `orchestrator.py` | Wires Planner → TaskGraph → TaskQueue → Scheduler |
| `executive_controller.py` | Top-level API: `plan()`, `receive_goal()`, `run()` |

### Plan templates (rule-based, no AI)

| Template | Trigger keywords | Tasks |
| --- | --- | --- |
| `api` | api, rest, backend, service, endpoint … | Research → Architecture → Implementation → Testing → Documentation |
| `script` | script, cli, tool, utility, automation … | Research → Implementation → Testing |
| `research` | research, analysis, study, investigate … | Research → Analysis → Report |
| `algorithm` | algorithm, sort, data structure, optimize … | Research → Design → Implementation → Testing |
| `database` | database, schema, sql, migration, orm … | Research → Design → Implementation → Testing → Documentation |
| `default` | (everything else) | Research → Design → Implementation → Testing → Review |

### New console commands

| Command | Description |
| --- | --- |
| `plan <goal>` | Decompose a goal and display the task graph |
| `tasks` | Show task list from the most recent plan |

### `SmartAgent` change
`agent.executive` — new `ExecutiveController` (planning) instance.  Separate
from `agent.mind` (Mind OS executive controller).

### Tests
`tests/test_executive.py` — **142 new tests** covering every class and
all code paths.  All pre-Phase-1 tests continue to pass.

---

## v1.1 — Streaming Upgrade

### Overview
Real-time token streaming, latency optimisation, and console UX improvements for
the Ollama integration.  No architecture changes — the Brain → ModelManager →
Provider chain is preserved.  All pre-v1.1 behavior is 100% backward-compatible.

### New capabilities

- **Real-time streaming** — `OllamaProvider.generate_stream()` and
  `chat_stream()` send `POST /api/chat` with `stream: true` and yield tokens
  as newline-delimited JSON chunks arrive.  `stream()` now delegates to
  `generate_stream()` for backward compatibility.

- **BaseModel streaming interface** — `BaseModel` gains two concrete (non-abstract)
  default methods: `generate_stream(prompt)` and `chat_stream(messages)`.  Both
  delegate to the existing `stream()` so all prior providers gain the new interface
  for free without modification.

- **ModelManager streaming** — `ModelManager` exposes `generate_stream()` and
  `chat_stream()` mirroring the same interface as `generate()` / `stream()`.  No
  logic is duplicated between the streaming and non-streaming paths.

- **Console token streaming** — Free-text input and `chat` commands now write
  tokens directly to `stdout` as they arrive instead of blocking for the full
  response.  Returns `""` so the REPL does not double-print.

- **Spinner** — While waiting for the first token, a Unicode braille spinner
  (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) is displayed with "Thinking…".  The spinner is cleared
  the instant the first token arrives.

- **Performance metrics** — When `settings.show_generation_stats = True`, a
  stats block is printed after each streamed response:
  - Prompt build time (ms)
  - First token latency (ms)
  - Generation duration (sec)
  - Approximate token count
  - Tokens per second
  - Total response time (sec)

- **Prompt cache** — When `settings.cache_prompts = True`, the static context
  (identity, mind-state, goals) is cached between calls.  Only the dynamic parts
  (user message, memory snippets, knowledge hits) are rebuilt each turn.  Cache
  is bounded to 16 entries (LRU-eviction on insert).

- **Model warmup** — When `settings.warmup_enabled = True` (default `True`), a
  single one-token `POST /api/chat` is sent immediately after `load()` so the
  model is already resident in memory before the first user request.  Silently
  skipped if the server is unreachable.

- **Lazy model loading** — When `settings.lazy_model_loading = True` (default
  `False`), `ModelManager.switch()` unloads the previous model after the new one
  is ready, keeping only one provider in memory at a time.

### New settings (all on `ModelSettings`)

| Field | Type | Default | Purpose |
| --- | --- | --- | --- |
| `warmup_enabled` | bool | `True` | Warm-up generation on `load()` |
| `cache_prompts` | bool | `True` | Cache static prompt context |
| `show_generation_stats` | bool | `False` | Print metrics after each response |
| `lazy_model_loading` | bool | `False` | Unload previous model on switch |

(`streaming_enabled` already existed; all four above are new.)

### Tests
- **~60 new tests** in `tests/test_ollama.py` covering: stream token order,
  partial output, spinner frames, fallback to non-streaming, metrics display,
  prompt cache, warmup, lazy loading, and 100% backward compatibility.
- All pre-v1.1 tests continue to pass.

---

## v1.0 — Ollama Integration

- **OllamaProvider** (`smartagent/models/providers/ollama_provider.py`) — full
  `BaseModel` implementation that talks to a locally-running Ollama server.
  Uses Python's `urllib` standard library; no new dependencies required.
  - `load()` — verifies the model is available on the server (never crashes if
    Ollama is offline); always sets status `LOADED` so model switching works.
  - `generate()` / `chat()` — `POST /api/chat` with `stream: false`; returns
    provider-shaped dict compatible with `ResponseParser`.
  - `stream()` — `POST /api/chat` with `stream: true`; yields tokens as they
    arrive via newline-delimited JSON.
  - `health()` — probes `GET /api/tags` directly; distinguishes "server
    unreachable" from "server up but model not installed".
  - `model_info()` — returns an `OllamaModelInfo` snapshot (name, size,
    family, modified date, status).
  - `embed()` — raises `NotImplementedError` (embeddings are a future milestone).
  - `_exclude_from_discovery = True` — `model_loader` skips this class; all
    instances are registered explicitly by `ModelManager.load_ollama_models()`.

- **OllamaModelDiscovery** — queries `GET /api/tags` to list installed models.
  Never raises; returns an empty list when the server is unreachable.

- **OllamaModelInfo** — dataclass storing `name`, `size`, `family`,
  `modified_at`, `status` for one installed Ollama model.

- **ModelManager** new API (`smartagent/models/manager/model_manager.py`):
  - `list_models()` — all registered `BaseModel` instances.
  - `load_model(id)` / `unload_model(id)` / `switch_model(id)` — aliases for
    `load()`/`unload()`/`switch()` matching the spec-mandated public surface.
  - `active_model()` — returns the live `BaseModel` instance (not just the id).
  - `load_ollama_models(base_url, default_model, coding_model)` — creates and
    registers `OllamaProvider` instances for the default model
    (`llama3.1:8b`), the coding model (`qwen2.5-coder:7b`), and any
    additional models discovered on the running Ollama server.

- **Settings** (`smartagent/config/settings.py`) — three new fields:
  `ollama_base_url` (default `http://127.0.0.1:11434`),
  `ollama_default_model` (`llama3.1:8b`), `ollama_coding_model`
  (`qwen2.5-coder:7b`).  All configurable without code changes.

- **ModelSettings** (`smartagent/models/config/model_settings.py`) — mirrors
  the three new Ollama fields from `Settings`.

- **MARK System Prompt** (`smartagent/models/prompts/mark_system_prompt.py`) —
  permanent `MARK_SYSTEM_PROMPT` constant: owner `Mr. Smart`, identity `MARK`,
  mission (serve, protect, never fabricate, use Memory/Knowledge/Skills/Tools,
  think before responding, say so when uncertain).

- **PromptBuilder** (`smartagent/models/prompts/prompt_builder.py`) — four new
  context fields added to `Prompt` (all default to empty for backward
  compatibility): `knowledge_context`, `mind_state`, `identity`, `goals`.
  Both `render()` and `to_messages()` include them when non-empty.
  `PromptBuilder.build()` accepts matching keyword-only arguments.

- **Console commands** (`smartagent/ui/commands/models.py`):
  - `models` — lists all registered providers with status and active marker.
  - `model use <name>` — switches the active model; graceful error if unknown.
  - `model current` — shows id, name, provider, and status of the active model.
  - `model info` — detailed metadata including Ollama server info when available.
  - `model list` — alias for `models`.
  - `chat <message>` — sends a message with full MARK context (working memory,
    knowledge, mind state, identity, goals) to the active model.

- **Coding auto-routing** — `chat` (and free-text input) inspects the message
  for programming keywords and routes to `qwen2.5-coder:7b` automatically.
  A header `[Routing to qwen2.5-coder:7b — coding request detected]` is
  prepended when routing differs from the active model.

- **Free-text fallback** (`smartagent/ui/command_router.py`) — `CommandRouter`
  now supports an optional `set_fallback(handler)`.  `Console` wires it to
  `fallback_chat`: when no command matches AND a model is active, the raw input
  is routed to the model.  When no model is active the original "Unknown
  command" message is returned, preserving all pre-v1.0 behaviour.

- **Fallback behaviour** — Ollama unavailable? `generate()` returns a dict
  with `content = "Ollama server unavailable."`, which surfaces cleanly in the
  console without a crash.  The rest of MARK continues working normally.

- **SmartAgent init** (`smartagent/brain/agent.py`) — calls
  `model_manager.load_ollama_models()` after `discover_providers()` so Ollama
  providers are always registered at startup (even when Ollama is offline).

- **Tests** (`tests/test_ollama.py`) — 105 new tests; all 763 total pass.
  All HTTP calls are mocked via `unittest.mock.patch("urllib.request.urlopen")`.
  No network, no real Ollama server required.

## v0.9 — MARK Console OS v1

- `python -m smartagent.main` now launches a persistent interactive console
  instead of exiting immediately. MARK stays alive and accepts commands until
  the user types `exit`, `quit`, presses Ctrl+C, or sends EOF.

- Startup banner printed on launch and on `clear`:
  ```
  ============================================================
                      MARK AI OPERATING SYSTEM
  ============================================================
  Owner        : Mr. Smart        Version      : 0.9
  Brain        : Online           Mind         : Online
  Memory       : Online           Knowledge    : Online
  Skills       : Loaded (N)       Tools        : Loaded (N)
  Models       : Ready            Health       : Healthy
  Type "help" to begin.
  mark>
  ```

- New command framework under `smartagent/ui/` — no giant `if/elif` chain.
  Each command group is a self-contained module with a `register(router)`
  function. Adding new commands for future milestones requires only a new
  module file and one line in `Console._register_commands()`.

  ```
  smartagent/ui/
  ├── console.py          — Console coordinator (wires all pieces)
  ├── repl.py             — Read-eval-print I/O loop (KeyboardInterrupt,
  │                         EOF, ExitConsole handled here)
  ├── renderer.py         — Pure formatting helpers (no I/O, fully
  │                         testable in isolation)
  ├── command_router.py   — CommandRouter: register/dispatch/help
  │                         ExitConsole sentinel exception
  └── commands/
      ├── system.py       — help, status, version, clear, exit/quit
      ├── memory.py       — remember, recall, search-memory
      ├── knowledge.py    — knowledge (add/search/graph/stats),
      │                     inbox, approve, reject
      ├── mind.py         — mind, identity, health, state,
      │                     attention, context
      ├── skills.py       — skills
      ├── tools.py        — tools
      ├── models.py       — models
      └── events.py       — events
  ```

- **`help`** — groups all commands by category (SYSTEM / MIND / MEMORY /
  KNOWLEDGE / SKILLS / TOOLS / MODELS / EVENTS) with one-line descriptions.

- **`status`** — full dashboard: Brain / Mind (state, goal, confidence) /
  Memory (categories, recent count) / Knowledge (concepts, relationships,
  avg confidence, inbox pending) / Skills / Tools / Models / Health metrics.

- **Memory commands:**
  - `remember <content>` — saves via `MemoryManager.remember()`; echoes
    the truncated id.
  - `recall` — lists last 10 memories via `MemoryManager.search("")`.
  - `search-memory <query>` — searches via `MemoryManager.search()`.

- **Knowledge commands:**
  - `knowledge add <title>` — proposes a concept through the inbox.
  - `knowledge search <query>` — searches via `KnowledgeManager.search()`.
  - `knowledge graph <title>` — shows concept relationships as a text tree.
  - `knowledge stats` — full statistics from `KnowledgeManager.stats()`.
  - `inbox` — lists pending inbox items numbered 1-N.
  - `approve <number>` — approves item by 1-based index (or raw id).
  - `reject <number>` — rejects item by 1-based index.

- **Mind commands** (all read from `agent.mind` — no behavior change):
  - `mind` — full `ExecutiveController.describe()`.
  - `identity` — agent name, mission, goal, task, state, confidence.
  - `health` — runs `health_check()`, shows band / score / metrics / notes.
  - `state` — current `InternalState` from `SelfModel`.
  - `attention` — active processes and priority queue from the Mind.
  - `context` — renders `ContextBundle` from `build_context()`.

- **Listing commands:** `skills` (id / version / status / permissions),
  `tools` (name / description / availability), `models` (registered
  providers / loaded / active / health).

- **`events`** — reads `agent.events.history()` directly; shows the 20 most
  recent events with timestamps and payload previews.

- **`clear`** — `os.system("clear")` + redraws the banner.

- **Unknown commands** — never crash; print a friendly message with a
  pointer to `help`.

- **Logging:** `configure_logging()` now accepts `log_file` and
  `log_to_console` parameters. `main.py` passes
  `log_file="logs/mark.log", log_to_console=False` so log noise never
  appears on the REPL screen. Tests and other callers are unaffected
  (`get_logger()` no longer auto-triggers `configure_logging()`).

- **Architecture rules kept:** the console is presentation-only. Every
  handler goes through the existing `MemoryManager`, `KnowledgeManager`,
  `ExecutiveController`, `SkillEngine`, `ToolEngine`, `ModelManager`, and
  `EventBus`. No logic is duplicated.

- 78 new tests in `tests/test_console.py` covering startup, banner,
  renderer, CommandRouter unit tests, every command group, REPL I/O loop
  (driven via patched `builtins.input`), Ctrl+C / EOF handling, exit,
  unknown commands, and resilience when Mind subsystems raise exceptions.
  Full suite: 652 passing, 0 regressions.

## v0.8 — Knowledge Engine v1

- Added `smartagent.knowledge` as a full package — a structured knowledge
  graph that transforms MARK from a system that only *remembers* information
  into one that *understands* knowledge. This is **computational knowledge
  architecture, not AI reasoning**: the engine represents concepts, relationships,
  evidence, confidence, contradictions, dependencies, and understanding without
  any AI model, embeddings, or vector databases.

- Added `KnowledgeManager` (the single entry point): the Brain communicates
  only through this class — never by importing sub-engines directly.
  Satisfies Milestone 7's requirement: "Brain must not directly modify
  knowledge. Brain communicates only through KnowledgeManager."

- Added `smartagent.knowledge.concepts.Concept`: rich knowledge nodes with
  20 structured fields — id, title, description, summary, category, tags,
  aliases, examples, difficulty (`ConceptDifficulty` enum: beginner/
  intermediate/advanced/expert), status (`ConceptStatus`), confidence,
  importance, created_at, updated_at, author, owner, source_ids, evidence_ids,
  relationship_ids, dependency_ids, contradiction_ids, verification_status
  (`VerificationStatus`), and a full `revision_history` list of `RevisionEntry`
  diffs. Concepts are editable, versioned, and fully serializable to/from JSON.

- Added `smartagent.knowledge.graph.KnowledgeGraph`: in-memory directed
  graph with complete CRUD (add/remove nodes and edges), BFS/DFS traversal,
  shortest path (BFS), dependency lookup, relationship lookup, merge/split
  nodes, graph statistics, and an adjacency dict export hook for future
  visualization. Stores only IDs — actual objects live in storage.

- Added `smartagent.knowledge.relationships.Relationship`: typed, weighted,
  confidence-scored directed edges. 15 relationship types: `depends_on`,
  `part_of`, `related_to`, `contradicts`, `extends`, `implements`, `inherits`,
  `causes`, `uses`, `creates`, `requires`, `improves`, `replaces`, `supports`,
  `references`. Each stores direction (forward/backward/bidirectional),
  strength, confidence, source, and timestamp.

- Added `smartagent.knowledge.sources.Source`: provenance tracking for every
  piece of knowledge. 11 source types (`SourceType`): `manual_entry`, `memory`,
  `research`, `books`, `documentation`, `internet`, `videos`, `courses`,
  `personal_notes`, `future_obsidian`, `future_browser`. Each source stores
  author, URL placeholder, publication, date, reliability score, and citation.

- Added `smartagent.knowledge.evidence.Evidence`: factual support records
  for each concept. 5 evidence types: `direct`, `indirect`, `anecdotal`,
  `experimental`, `theoretical`. Each evidence item stores strength,
  confidence, verification status, and links to a source.

- Added `smartagent.knowledge.confidence.ConfidenceEngine`: transparent,
  fully auditable evidence-based scoring. Score = weighted function of:
  evidence quality (0.40), source reliability (0.30), source-count
  corroboration bonus (capped at 5 sources → +0.10), verification bonus
  (+0.10 for verified concepts), age penalty (linear decay after 365 days
  for unverified concepts, max -0.15), and contradiction penalty (-0.15
  per unresolved contradiction, capped at -0.60). Returns a `ConfidenceFactors`
  breakdown with human-readable notes so MARK can explain every score.

- Added `smartagent.knowledge.validation.ConceptValidator`: hard-error
  structural validation (id, title, confidence/importance in [0.0, 1.0])
  plus soft warnings (short description, no tags, no summary, default
  confidence unchanged). Runs in the inbox pipeline before any concept
  reaches the graph.

- Added `smartagent.knowledge.inbox.KnowledgeInbox`: the approval gate.
  Nothing enters permanent knowledge automatically. Workflow: propose →
  validation → conflict detection → confidence scoring → Mr. Smart approval →
  knowledge graph. Conflict detection checks existing concepts for
  `contradiction_ids` cross-references. Each inbox item is persisted to
  `knowledge/inbox/` immediately so the queue survives restarts.
  `InboxItemStatus`: pending / approved / rejected / conflict.

- Added `smartagent.knowledge.ontology.OntologyEngine`: hierarchical
  category tree. Supports add/remove, parent/ancestor/descendant traversal,
  `ensure_path()` (creates all missing path segments in one call), category
  inheritance, alias search, and persistence to `knowledge/ontology.json`.
  7 default root categories seeded on first run (Technology, Science,
  Business, Personal, Research, History, Philosophy).

- Added `smartagent.knowledge.queries.QueryEngine`: full structured query
  set from the Milestone 7 spec — `find_concept`, `find_related`,
  `find_dependencies`, `find_contradictions`, `find_missing_evidence`,
  `find_low_confidence`, `find_orphans`, `find_duplicates`, `find_by_category`,
  `find_by_tag`, `find_unverified`.

- Added `smartagent.knowledge.search.KnowledgeSearch`: deterministic, no-
  embeddings full-text search across title, aliases, tags, category,
  description, and summary. Relevance scoring: title/alias exact match (+3),
  partial match (+2), tag match (+1.5), category (+1), description/summary
  (+0.5). Supports category prefix filter (hierarchical) and tag multi-filter.

- Added `smartagent.knowledge.storage.KnowledgeStorage`: filesystem-based
  JSON persistence in `knowledge/` (separate from the memory `vault/`).
  One file per concept, relationship, source, evidence item, and inbox item.
  Human-readable, indented JSON — openable and editable in any text editor.

- Added `smartagent.knowledge.statistics.KnowledgeStats`: live + historical
  stats — total concepts, relationships, average confidence, conflicts,
  pending inbox items, verified/unverified/contradicted concept counts,
  categories, sources, evidence, low-confidence (<0.5) and high-confidence
  (≥0.8) buckets. Growth over time tracked by appending snapshots to
  `knowledge/stats_history.json`.

- Added `smartagent.knowledge.categories.Category`: simple value object for
  category tree nodes with path computation, depth, ancestor check, and
  round-trip serialization.

- Brain integration: `module_bindings.knowledge_handler` registers
  `agent.knowledge` (KnowledgeManager) as the "knowledge" module in the
  `ModuleRegistry`, with confidence 0.6 — between memory (0.8) and planning
  (0.5). Searches the graph and returns matching concept summaries. The
  handler follows the same Brain v2 module contract as all other handlers:
  returns `ActionResult`, publishes nothing directly.

- `SmartAgent.__init__` now constructs `self.knowledge = KnowledgeManager()`
  from `settings.knowledge_path` (new field in `Settings`, defaults to
  `"knowledge/"`). Constructed before the `ModuleRegistry` is built so the
  knowledge handler can close over the live instance.

- Storage: `knowledge/` directory is kept separate from `vault/` — Memory
  remains Markdown, Knowledge is JSON. No database, no embeddings, no vector
  store.

- Explicitly **not** implemented this milestone (per spec): AI reasoning,
  Ollama, vector databases, embeddings, browser access, internet research,
  voice, vision, cybersecurity. No modification to Memory, Mind, Brain
  routing, Skills, Tools, or Model Framework behavior.

- 120+ new tests in `tests/test_knowledge.py` covering all engines, storage,
  graph operations, inbox workflow, ontology, search, queries, confidence,
  statistics, and end-to-end manager operations including persistence across
  instances.

## v0.7 — MARK Mind OS v1

- Added `smartagent.mind` as a real package — a persistent internal mind
  layered on top of Brain/Memory/Skills/Tools/Models. Explicitly
  **computational self-awareness, not consciousness**: the Mind observes
  and represents MARK's own state; it never drives Brain routing and does
  not change the behavior of any existing subsystem.

- Added `smartagent.mind.executive.executive_controller.ExecutiveController`:
  the sole coordinator across every Mind engine (self model, identity,
  working memory, attention, context, confidence, state, reflection,
  homeostasis). Added `MindProviders`: a dataclass of optional,
  zero-argument callables (`active_goal`, `goals`, `skills`, `tools`,
  `active_model`, `running_processes`) that `SmartAgent` binds to its own
  live subsystems — keeps `smartagent.mind` free of any hard dependency
  on `smartagent.brain.agent.SmartAgent`, avoiding a circular import.
  Also provides goal/task lifecycle coordination (`set_current_goal`,
  `start_task`/`complete_task`), a ranked priority queue
  (`enqueue`/`next_in_queue`), interrupt/resume passthrough, confidence-
  scored decisions (`decide`), context assembly (`build_context`), and
  health checks (`health_check`).

- Added `smartagent.mind.self_model`: `SelfModel` dataclass (name, owner,
  mission, current activity/goal, known goals/skills/tools, active model,
  confidence, health score, bounded `recent_changes` diff log) and
  `SelfModelEngine` (`snapshot`, `update(**fields)`, `describe()`),
  publishing `SelfModelUpdated`.

- Added `smartagent.mind.identity`: `Identity` dataclass and
  `IdentityEngine`, which genuinely parses `SMARTAGENT.md`'s existing
  Markdown headings (`## Identity`, `## Core Principles`, `##
  Personality`, `## Long-Term Goals`, `## Architecture Philosophy`, `##
  Safety`) into a structured `Identity`, round-trips it back out via
  `to_markdown()`/`save()`, and falls back to a built-in
  `default_identity()` matching the current `SMARTAGENT.md` content if the
  file is missing or unparseable.

- Added `smartagent.mind.working_memory.WorkingMemory`: short-term,
  TTL-based scratch space (`put`/`get`/`all`/`forget`/`purge_expired`/
  `clear`) with an injectable clock for deterministic tests — explicitly
  distinct from, and not a replacement for, the persistent Memory vault.

- Added `smartagent.mind.attention.AttentionManager`: `FocusItem`
  dataclass, importance-based ranking, a bounded `max_concurrent` focus
  set with automatic lowest-importance eviction, and an interrupt/resume
  stack for handling higher-priority items mid-focus. Publishes
  `AttentionShifted`.

- Added `smartagent.mind.context.ContextManager`/`ContextBundle`:
  assembles a bounded context blob from up to 8 sources (conversation,
  working memory, knowledge, goals, research, reflection, tool outputs,
  identity), each capped to `max_items_per_source`; `ContextBundle.render()`
  flattens it into a single, optionally length-truncated text blob.

- Added `smartagent.mind.confidence.ConfidenceEngine`: transparent,
  non-fabricated confidence scoring — a base score from evidence count,
  with penalties for conflicts, missing information, and unknowns,
  clamped to `[0.0, 1.0]`. Bounded scoring `history()`/`latest()`.
  Publishes `ConfidenceChanged`.

- Added `smartagent.mind.state.StateMachine`/`InternalState`: 12 named
  internal states (idle, listening, thinking, planning, researching,
  executing, reflecting, learning, waiting, sleeping, error, recovering),
  deliberately permissive transitions (no forbidden-transition table —
  the spec doesn't define one and false rejections would be worse than
  permissive logging), bounded transition `history()`, `is_in()`.
  Publishes `StateChanged`.

- Added `smartagent.mind.reflection.ReflectionEngine`: post-task
  self-assessment producing a `Reflection` with heuristic
  `should_become_memory`/`could_improve_future_performance` flags.
  Deliberately never writes to the Memory vault itself — only flags what
  a Skill or future Learning Engine should decide to persist. Publishes
  `ReflectionFinished`.

- Added `smartagent.mind.homeostasis` (covers Parts 8, 12, and 13
  together): `HealthMetrics` (memory usage, task load, errors, queue
  length, latency, model/tool/skill availability) with a transparent
  `score()`; `HomeostasisEngine` mapping the score into a
  healthy/degraded/critical band and publishing `HealthChanged` only on
  band transitions (not every check); `DigitalSensorySystem` +
  `SensorySignal` enum (10 named computational signals — memory_changed,
  high_cpu_load, low_confidence, knowledge_conflict, new_goal,
  task_delay, module_failure, research_completed, tool_failure,
  permission_denied) publishing `SensorySignalDetected`; and
  `DigitalHomeostasisLoop.tick()`, a synchronous, explicitly-invoked
  self-check (not a background thread/timer, keeping it deterministic and
  testable) answering: is MARK healthy, overloaded, making progress, do
  its goals match its mission (best-effort keyword match), is anything
  failing, and should the owner be notified.

- Added 10 new `Events` constants to `smartagent.brain.events.Events`
  under a new "Mind" section: `GOAL_CHANGED`, `ATTENTION_SHIFTED`,
  `CONFIDENCE_CHANGED`, `HEALTH_CHANGED`, `STATE_CHANGED`, `TASK_STARTED`,
  `REFLECTION_FINISHED`, `SELF_MODEL_UPDATED`, `SENSORY_SIGNAL_DETECTED`,
  `WORKING_MEMORY_UPDATED`. The existing `MEMORY_UPDATED`/`TASK_COMPLETED`
  events are reused rather than duplicated. All Mind engines publish onto
  the same shared `EventBus` — there is no separate Mind event bus.

- `smartagent.brain.agent.SmartAgent.__init__` now constructs
  `self.mind = ExecutiveController(...)` last, wired via `MindProviders`
  into the agent's own `goals`/`skill_engine`/`tool_engine`/
  `model_manager`. `handle_message()` gained a guarded (`try/except`)
  observation hook: it transitions Mind state to `THINKING` before
  routing and to `IDLE` after, records a `Reflection` on the outcome, and
  re-syncs the `SelfModel` — all wrapped so a Mind bug can never break
  message handling. Verified byte-for-byte: `handle_message()`'s returned
  message is unchanged from before this milestone.

- Explicitly **not** implemented this milestone (future-compatible,
  design-only per the spec): Knowledge Engine, Learning Engine, Curiosity
  Engine, Discovery Engine, Wisdom Engine, Cybersecurity Engine, and any
  Voice/Vision/Browser/Automation integration into the Mind. No Ollama or
  internet access was added. No change was made to the behavior of
  Memory, Brain routing, Skills, Tools, or the Model Framework.

- Added `ARCHITECTURE.md` with ASCII diagrams: MARK Mind OS overview,
  data flow through `handle_message()`, and per-engine diagrams for the
  Executive Controller, Self Model, Working Memory, Attention, State
  Machine, and Homeostasis.

- 86 new tests; full suite 455 passing, 0 regressions.

## v0.6 — Model Framework v1

- Added `smartagent.models` as a real package (`base/`, `providers/`,
  `registry/`, `manager/`, `context/`, `prompts/`, `responses/`, `config/`),
  decoupling the Brain from any specific AI provider. The Milestone 1
  placeholder `smartagent.models.model_client.ModelClient` is kept as-is
  for backward compatibility (`SkillContext.model`, existing tests still
  construct it directly) — new code uses `ModelManager` instead.

- Added `smartagent.models.base.base_model.BaseModel`: abstract contract
  every provider implements. Required abstract identity properties (`id`,
  `name`, `provider`, `version`) and lifecycle/action methods
  (`initialize`, `load`, `generate`, `stream`, `embed`, `shutdown`);
  optional overridable capability properties (`context_window`,
  `supports_streaming`, `supports_tools`, `supports_images`,
  `supports_embeddings`, `supports_functions`), all defaulting to the most
  conservative value. `metadata()`/`status()` are concrete snapshot
  builders, mirroring `BaseTool`. `ModelMetadata`/`ModelHealth`/
  `ModelStatus` supporting types.

- Added `smartagent.models.providers.mock_provider.MockModelProvider`: the
  one working, fully deterministic provider Milestone 5 ships — no real
  AI backend, safe for tests/CI. `embed()` explicitly raises
  `NotImplementedError` (embeddings are out of scope for this milestone).

- Added `smartagent.models.providers.future_providers`: **design-only**
  interface stubs for Ollama, OpenAI, Anthropic, Gemini, LM Studio,
  OpenRouter, Azure OpenAI, Bedrock, DeepSeek, Mistral, vLLM, and
  llama.cpp. Each subclasses `BaseModel` but only overrides the four
  identity properties, so every stub stays abstract (`TypeError` on
  instantiation) and is automatically excluded from provider discovery —
  no accidental wiring of an unimplemented backend.

- Added `smartagent.models.registry.model_loader.discover_provider_classes()`
  (mirrors `skill_loader`'s single-level `pkgutil.iter_modules`) and
  `smartagent.models.registry.model_registry.ModelRegistry`: register,
  unregister, find, list, reload, enable, disable, discover, health_check,
  statistics, record_generation. Design mirrors `ToolRegistry`/`SkillRegistry`.

- Added `smartagent.models.manager.model_manager.ModelManager`: the *only*
  component allowed to talk to providers (mirrors `ToolEngine` being the
  only thing that calls a `BaseTool`). `load`/`unload`/`switch`/
  `select_default`/`generate`/`stream`/`health_check`/`health`/
  `statistics`/`describe`/`discover_providers`. Publishes `ModelLoaded`,
  `ModelUnloaded`, `ModelSwitched`, `ModelHealthChecked` onto the shared
  `EventBus`. `generate()`/`stream()` raise `NoActiveModelError` when no
  model has been loaded/switched to and no `default_model_id` is
  configured — the out-of-the-box state, so behavior is unchanged from
  before this milestone until a deployment opts in.

- Added `smartagent.models.prompts.prompt_builder`: `PromptBuilder.build()`
  assembles a provider-agnostic `Prompt` (system prompt, user message,
  history, memory context, skill context, tool results) from a message and
  an optional `ConversationContext`. `Prompt.render()` flattens to one
  string; `Prompt.to_messages()` renders chat-style `{role, content}` turns.
  `future_context` (research/knowledge-graph/vision) is a placeholder field,
  always empty in this milestone.

- Added `smartagent.models.context.conversation_context.ConversationContext`:
  history (`ConversationTurn` list), running summaries, active goals/task,
  memory references, tool outputs, timestamps, and a character-heuristic
  token estimate. No automatic compression yet — a future pass owns that.

- Added `smartagent.models.responses.response_parser.ResponseParser`:
  normalizes a provider's raw response (whatever shape `generate()`
  returned) into a `ParsedResponse` (text, `tool_requests`, confidence,
  metadata, `timing_ms`, usage stats), checking a small set of common key
  names per field so a new provider's slightly different JSON shape
  doesn't need a parser rewrite.

- Added `smartagent.models.config.model_settings.ModelSettings`: default
  model id, temperature, top_p, top_k, max_tokens, streaming flag, timeout,
  and placeholder `api_keys`/`local_model_paths` dicts for future providers
  (never populated with a hardcoded value).

- Updated `smartagent.config.settings.Settings`: added `default_model_id: str = ""`
  (empty by default — no Model Framework provider auto-loads).

- Updated `smartagent.brain.events.Events`: added `MODEL_LOADED`,
  `MODEL_UNLOADED`, `MODEL_SWITCHED`, `MODEL_HEALTH_CHECKED`.

- Updated `smartagent.brain.agent.SmartAgent`: constructs `self.model_manager`
  (a `ModelManager`) alongside the still-present legacy `self.model`
  (`ModelClient`), and calls `discover_providers()` on startup so
  `MockModelProvider` is registered and ready to load on demand.

- Updated `smartagent.brain.module_bindings`: `model_handler` now calls
  `agent.model_manager.generate()` instead of `agent.model.generate()` —
  the Brain never imports a provider directly. Behavior is unchanged by
  default (`success=False` via `NoActiveModelError`, exactly like the old
  `ModelClient.generate()`'s `NotImplementedError`); setting
  `Settings.default_model_id = "mock"` makes it succeed for real.

- Added 93 new tests in `tests/test_models.py` covering all of the above.
  Full suite: 369 passed, 0 failed.

## v0.5 — Tool Engine v1

- Established the execution-layer architectural boundary:
  **Brain → Skill → ToolEngine → Tool → ActionResult**.
  The Brain never calls a tool; Skills call `ToolEngine.run()` via
  `SkillContext.tool_engine`. The Brain's `tools` module handler is now a
  reporting endpoint (lists available tools; always returns `success=False`
  so the Brain chain-of-responsibility never stops there).

- Added `smartagent.tools.base_tool`: `BaseTool` abstract class (Milestone 4
  Part 2) with mandatory properties (`id`, `name`, `description`, `version`,
  `author`, `category`) and lifecycle hooks (`initialize`, `shutdown`, `health`);
  `ToolMetadata` (frozen snapshot dataclass); `ToolContext` (DI bundle:
  `settings`, `workspace_path`, `events`); `ToolCategory` enum (FILESYSTEM,
  SYSTEM, UTILITIES, TEXT, FUTURE); `ToolStatus` enum.

- Upgraded `smartagent.tools.tool_registry` from Milestone-1 placeholder to
  full production registry (Part 3): `register`, `unregister`, `find`, `list`,
  `reload`, `enable`, `disable`, `health_check`, `statistics`,
  `record_execution`. Old `Tool` ABC (with `run()`) and `get()` method
  preserved for backward compatibility.

- Added `smartagent.tools.tool_loader`: `discover_tool_classes()` uses
  `pkgutil.walk_packages` (recursive, unlike the skill loader's single-level
  `iter_modules`) to auto-discover `BaseTool` subclasses across sub-packages.
  Default package: `smartagent.tools.builtin`.

- Added `smartagent.tools.tool_engine`: `ToolEngine` (Part 1) — register,
  load, execute.  `run(tool_id, context, **params)` enforces: tool exists →
  tool enabled → permissions granted → params valid → execute → publish
  `ToolExecuted`.  Shares one `PermissionManager` with `SkillEngine`.

- Added `smartagent.tools.safety`: `PathValidator` resolves paths and verifies
  workspace containment; `check_not_protected_source()` additionally blocks
  paths containing `"smartagent"` or `"tests"` components; `SafetyError`
  (never a transient error — always a hard rejection).

- Added 5 new `Permission` enum values in `smartagent.skills.permissions`
  (total 12, up from 7): `READ_FILES`, `WRITE_FILES`, `DELETE_FILES`,
  `CREATE_DIRECTORIES`, `READ_SYSTEM_INFO`.

- Added 15 built-in tools (Python stdlib only, no new dependencies):
  - `smartagent.tools.builtin.filesystem`: `FileReadTool`, `FileWriteTool`,
    `DirectoryCreateTool`, `DirectoryListTool`, `CopyFileTool`, `MoveFileTool`,
    `DeleteFileTool` (protected-source guard), `SearchFilesTool`
  - `smartagent.tools.builtin.text`: `OpenTextFileTool`, `ReadMarkdownTool`
    (parses heading structure)
  - `smartagent.tools.builtin.system`: `SystemInfoTool`, `DateTimeTool`
    (6 formats), `EnvironmentTool` (auto-redacts sensitive names)
  - `smartagent.tools.builtin.utilities`: `UUIDTool` (v1/3/4/5),
    `HashTool` (any `hashlib.algorithms_guaranteed` algorithm)

- Updated `smartagent.skills.base_skill.SkillContext`: added optional
  `tool_engine: ToolEngine | None = None` field so skills can call tools
  via `context.tool_engine.run(...)` without importing `SmartAgent`.

- Updated `smartagent.brain.agent.SmartAgent`: constructs `ToolEngine` after
  `SkillEngine`, passing the *same* `PermissionManager`; stored as
  `self.permissions` (shared), `self.skill_engine`, and `self.tool_engine`.
  Auto-loads all built-in tools on startup.

- Updated `smartagent.config.settings`: added `workspace_path: str = "."`.

- Updated `smartagent.brain.events.Events`: added `TOOL_EXECUTED` and
  `TOOL_LOADED` event name constants.

- Updated `smartagent.brain.module_bindings`: `_build_skill_context` now
  passes `tool_engine=agent.tool_engine`; `tools_handler` delegates to
  `agent.tool_engine.describe()` instead of returning a hardcoded string.

- Added 148 new tests in `tests/test_tools.py` covering all of the above.
  Full suite: 276 passed, 0 failed.

## v0.4 — Skills Engine v1

- Added `smartagent.skills.permissions`: `Permission` enum (7 values:
  `READ_MEMORY`, `WRITE_MEMORY`, `RUN_TOOLS`, `ACCESS_FILES`,
  `NETWORK_ACCESS`, `AUTOMATION`, `SYSTEM_COMMANDS`) and
  `PermissionManager` — the single authority that decides whether a
  permission is currently granted. Nothing is granted automatically;
  defaults give only `READ_MEMORY`/`WRITE_MEMORY` (minimum for built-ins).
- Added `smartagent.skills.base_skill`: `BaseSkill` abstract class
  (`name`, `description`, `version`, `author`, `required_modules`,
  `validate()`, `execute()`, `status()`), plus `SkillMetadata` (frozen
  snapshot dataclass), `SkillContext` (dependency-injection container
  passed to `execute()` instead of the full agent — avoids circular
  imports), `SkillCategory`, and `SkillStatus`.
- Added `smartagent.skills.skill_registry`: upgraded placeholder
  registry into a production `SkillRegistry` with `register`,
  `unregister`, `enable`, `disable`, `reload`, `list`, `find`, and
  backward-compatible `list_available()`.
- Added `smartagent.skills.skill_engine`: `SkillEngine` — the only thing
  the Brain talks to for skills. Confidence-ordered dispatch with
  permission enforcement and chain-of-responsibility fallthrough (mirrors
  `BrainRouter`). Publishes `SKILL_EXECUTED` onto the shared `EventBus`.
- Added `smartagent.skills.skill_loader`: `discover_skill_classes()`
  auto-discovers `BaseSkill` subclasses in a package via `pkgutil` /
  `importlib` — no hardcoded imports needed.
- Added six built-in skills in `smartagent.skills.builtin`:
  - `MemorySkill` — remember/recall/forget backed by `MemoryManager`
  - `KnowledgeSkill` — notes/retrieves facts in the Knowledge category
  - `PlanningSkill` — adds/lists goals via `GoalManager`
  - `ResearchSkill` — queues research topics via `ResearchManager`
    (requires `NETWORK_ACCESS` which is denied by default — a live demo
    of permission enforcement)
  - `ConversationSkill` — deterministic replies for greetings/thanks/farewells
  - `SystemInfoSkill` — reports registered modules/skills (requires
    `SYSTEM_COMMANDS`, denied by default)
- Updated `smartagent.config.settings`: added `granted_permissions` list
  (default `["read_memory", "write_memory"]`) — keeps `config` free of a
  dependency on `skills` by storing permission names as plain strings.
- Updated `smartagent.brain.agent`:
  - Constructs `PermissionManager` from `settings.granted_permissions`.
  - Constructs `SkillEngine` with the registry, permission manager, and
    shared event bus, then auto-loads all built-in skills.
  - `handle_message()` fixed double-memory bug: checks EventBus history
    for a `MemorySaved` event fired during routing; skips the Journal
    auto-persist if a skill already wrote to memory, preventing a "search
    returns 2 results when 1 was expected" regression.
- Updated `smartagent.brain.module_bindings`: `skills_handler` now calls
  `agent.skill_engine.execute()` instead of returning a placeholder —
  the Brain truly delegates to the Skills Engine and knows nothing about
  which specific skill handles a request.
- Added 74 new tests in `tests/test_skills.py` covering all of the above.
  Full suite: 128 passed, 0 failed.

## v0.3 — Brain v2 (Decision Engine)

- Added `smartagent.brain.router.BrainRouter`: routes every request
  through Intent Analyzer -> Decision Engine -> Module Registry -> Execute
  -> Response, replacing the hardcoded "check memory, then the model"
  logic that lived directly in `SmartAgent`.
- Added `smartagent.brain.intent_analyzer.IntentAnalyzer`: rule-based
  classification into `MEMORY`, `RESEARCH`, `TOOL`, `SKILL`, `VISION`,
  `VOICE`, `PLANNING`, `MODEL`, `AUTOMATION`, `UNKNOWN`. No AI used.
- Added `smartagent.brain.decision_engine.DecisionEngine`: orders
  candidate modules by a fixed priority (Memory > Skills > Tools >
  Planning > Research > Model > Unknown).
- Added `smartagent.brain.module_registry.ModuleRegistry`: the only place
  modules are looked up by name, so the Brain never hardcodes them.
- Added `smartagent.brain.action_result.ActionResult`: the standard
  `{success, message, data, source, execution_time, confidence}` shape
  every module now returns.
- Added `smartagent.brain.events.EventBus` / `Events`: synchronous
  publish/subscribe. `MemoryManager` now publishes `MemorySaved`,
  `MemoryUpdated`, and `MemoryDeleted`; `BrainRouter` publishes
  `RequestReceived` and `BrainDecisionMade`.
- Added `smartagent.brain.module_bindings`: wires memory, skills, tools,
  planning, research, models, voice, vision, and automation into the
  `ModuleRegistry` as `SmartAgent` module handlers.
- `SmartAgent` now constructs and registers every subsystem (previously
  only memory, tools, skills, and the model client were wired up;
  planning, research, voice, vision, and automation now are too) and
  delegates all decision logic to `BrainRouter`.
- Fixed `ResearchManager.approve()`, which called `MemoryManager.remember()`
  with a `metadata=` keyword argument that no longer exists after Memory
  v1 (would have raised `TypeError` the first time a finding was
  approved) — updated to use `category`/`tags`.
- Added unit tests for `IntentAnalyzer`, `DecisionEngine`,
  `ModuleRegistry`, `ActionResult`, `EventBus`, and `BrainRouter`.
- Docs: added `ROADMAP.md`, `CHANGELOG.md`, `CONTRIBUTING.md`; updated
  `README.md` with a Brain v2 pipeline diagram and module table; updated
  `SMARTAGENT.md`'s implementation status.

## v0.2 — Memory v1 (Markdown Vault)

- Replaced the in-memory placeholder `MemoryManager` with a persistent
  Markdown vault (`smartagent.memory.vault.Vault` +
  `smartagent.memory.entry.MemoryEntry`).
- Implemented `remember()`, `recall()`, `search()`, `update()`,
  `delete()`, and `list_categories()` against real files on disk, one
  human-readable `.md` file per memory, organized into category folders
  (`Personal`, `Business`, `Projects`, `Knowledge`, `Research`, `Journal`,
  `Archive`).
- Auto-generated metadata per memory: unique id, `created_at`/`updated_at`
  timestamps, category, tags — written as Markdown frontmatter and parsed
  back by a small hand-written parser (no YAML dependency, no database).
- `SmartAgent.handle_message()` now checks memory before considering a
  model call.
- Added unit tests covering saving, searching, updating, deleting, and
  persistence across a fresh `MemoryManager` instance (simulating a
  restart).

## v0.1 — Foundation

- Project initialized as a modular Python package (`brain`, `memory`,
  `models`, `skills`, `tools`, `voice`, `vision`, `automation`, `config`,
  `ui`, `logs`, `research`, `planning`).
- Centralized logging (`smartagent.logs.logger`) and configuration
  (`smartagent.config.settings.Settings`).
- `SmartAgent` orchestrator scaffold with placeholder `handle_message()`
  and `run()`.
- Placeholder implementations for models, skills, tools, voice, vision,
  automation.
- `ResearchManager` with a working in-memory owner-approval queue
  (`queue_for_approval` / `list_pending` / `approve` / `reject`); search
  and summarization left as documented placeholders.
- `GoalManager` with working in-memory goal tracking; `TaskPlanner`
  decomposition left as a documented placeholder.
- `SMARTAGENT.md` added: MARK's identity, mission, principles, and safety
  rules.
- Initial test suite covering the agent, memory placeholder, and tool
  registry.
