# SmartAgent

SmartAgent is MARK — a personal AI assistant built incrementally for
Mr. Smart.  As of v1.0, MARK integrates with a locally-running Ollama
server for real language-model responses, while keeping all memory,
knowledge, skills, and tools fully operational offline.

## Project layout

```
smartagent/
├── main.py             # Process entry point — boots the agent and CLI
├── brain/              # Brain v2: BrainRouter, IntentAnalyzer, DecisionEngine,
│                       # ModuleRegistry, ActionResult, EventBus, agent.py
├── memory/             # Persistent Markdown memory vault (see below)
├── knowledge/          # Knowledge Engine v1: KnowledgeManager, KnowledgeGraph,
│                       # Concept/Relationship/Source/Evidence models,
│                       # ConfidenceEngine, KnowledgeInbox, OntologyEngine,
│                       # QueryEngine, KnowledgeSearch, KnowledgeStorage,
│                       # KnowledgeStats (see below)
├── models/             # Model Framework v1: ModelManager, ModelRegistry,
│                       # BaseModel providers, PromptBuilder, ConversationContext,
│                       # ResponseParser, ModelSettings (see below)
├── mind/               # MARK Mind OS v1: ExecutiveController, SelfModel,
│                       # IdentityEngine, WorkingMemory, AttentionManager,
│                       # ContextManager, ConfidenceEngine, StateMachine,
│                       # ReflectionEngine, Homeostasis (see below)
├── skills/             # Composed, user-facing capabilities
├── tools/              # Low-level, single-purpose capabilities
├── voice/              # Speech-to-text / text-to-speech interfaces
├── vision/             # Image/video understanding interfaces
├── automation/         # Scheduled/background tasks
├── config/             # Centralized settings
├── ui/                 # User-facing front-ends (CLI today)
├── logs/               # Centralized logging setup
├── research/           # Trusted-source research, summarized + owner-approved before storage
└── planning/           # Goal tracking and task decomposition
vault/                  # Persistent memories, one human-readable .md file per memory
knowledge/              # Structured knowledge graph: JSON files per concept, relationship,
│                       # source, evidence item, and inbox item. Separate from vault/.
│                       # knowledge/ontology.json — hierarchical category tree
│                       # knowledge/stats_history.json — growth-over-time snapshots
tests/                  # Test suite, mirrors the smartagent package structure
```

## Running MARK

```bash
python -m smartagent.main
```

MARK boots all subsystems and drops into a persistent interactive console:

```
============================================================
                    MARK AI OPERATING SYSTEM
============================================================

Owner        : Mr. Smart
Agent        : MARK
Version      : 0.9

Brain        : Online
Mind         : Online
Memory       : Online
Knowledge    : Online
Skills       : Loaded
Tools        : Loaded
Models       : Ready
Health       : Healthy

Type "help" to begin.

mark>
```

Type `help` to see all available commands, `status` for a full dashboard,
or `exit` / `quit` / Ctrl+C to leave.

---

See `SMARTAGENT.md` for MARK's identity, mission, principles, and
long-term architecture vision, and `ROADMAP.md` for the full development
plan, milestone status, and coding standards — this repository is the
implementation of that vision, built incrementally.

Additional project documents:

- [`ROADMAP.md`](ROADMAP.md) — vision, milestones, architecture, build order, coding standards, TODOs.
- [`SMARTAGENT.md`](SMARTAGENT.md) — MARK's identity, mission, principles, and safety rules.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — diagrams of the Brain, Model Framework, and Mind OS.
- [`CHANGELOG.md`](CHANGELOG.md) — version history.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to add new modules and code standards.

## Memory (v1): the Markdown vault

Memory is no longer a placeholder — `smartagent.memory.MemoryManager` now
persists every memory as a plain Markdown file inside a `vault/` directory,
organized into category folders:

```
vault/
├── Personal/
├── Business/
├── Projects/
├── Knowledge/
├── Research/
├── Journal/
└── Archive/
```

Each memory is one `.md` file with a small metadata header (auto-generated
id, timestamp, category, tags) followed by the memory's content, e.g.:

```
---
id: 20260714-153000-a1b2c3d4
category: Personal
tags: preference, color
created_at: 2026-07-14T15:30:00+00:00
updated_at: 2026-07-14T15:30:00+00:00
---

The user's favorite color is blue.
```

Design goals for Memory v1:

- **No database.** The vault is just files on disk — every memory can be
  opened, read, and hand-edited in any text editor.
- **No vector/semantic search yet.** `search()` does case-insensitive
  keyword matching over content and tags; a smarter ranking strategy can be
  added later behind the same method signature.
- **No AI model connected.** Memory storage/retrieval is fully
  deterministic and has no dependency on `smartagent.models`.

`MemoryManager` API:

| Method | Purpose |
| --- | --- |
| `remember(content, category=..., tags=...)` | Store a new memory; returns the created entry (with generated id/timestamps). |
| `recall(memory_id)` | Fetch one memory by its exact id, or `None`. |
| `search(query, category=None, limit=5)` | Keyword search across content/tags, most recent first. |
| `update(memory_id, content=None, tags=None)` | Edit an existing memory in place; bumps `updated_at`. |
| `delete(memory_id)` | Permanently remove a memory. |
| `list_categories()` | List every category folder currently in the vault. |

The vault location is configurable via `Settings.vault_path` (default:
`vault/` at the project root) — tests point it at an isolated temp
directory so they never touch real memories.

`SmartAgent.handle_message()` now checks memory (via `search()`) *before*
considering a model call — if MARK already has relevant, persisted
knowledge, it answers from that instead of asking a (still unimplemented)
language model to rediscover it. Every exchange is then written back into
the `Journal` category so future messages can find it.

## Brain v2: the Decision Engine

Milestone 2 replaced the hardcoded "check memory, then the model" logic in
`SmartAgent` with a general routing pipeline every message passes through:

```
                 ┌────────────────────┐
 User message -> │   BrainRouter      │
                 │  (router.py)       │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │  IntentAnalyzer     │  rule-based classification:
                 │ (intent_analyzer.py)│  MEMORY / RESEARCH / TOOL / SKILL /
                 └─────────┬──────────┘  VISION / VOICE / PLANNING / MODEL /
                           │             AUTOMATION / UNKNOWN
                           ▼
                 ┌────────────────────┐
                 │  DecisionEngine     │  orders candidate modules:
                 │ (decision_engine.py)│  Memory > Skills > Tools > Planning
                 └─────────┬──────────┘  > Research > Model > Unknown
                           │
                           ▼
                 ┌────────────────────┐
                 │  ModuleRegistry     │  looks modules up **by name only**
                 │ (module_registry.py)│  — the Brain never hardcodes them
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │  Execute            │  the registry's handler runs and
                 │ (module_bindings.py)│  returns a standardized ActionResult
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │  Return Response    │  first module to report success
                 │                     │  wins; EventBus is notified either
                 └────────────────────┘  way (see below)
```

Key pieces, each in its own module under `smartagent/brain/`:

| Module | Responsibility |
| --- | --- |
| `action_result.py` | `ActionResult` — the standard `{success, message, data, source, execution_time, confidence}` shape every module returns. |
| `intent_analyzer.py` | `IntentAnalyzer` / `Intent` — lightweight, rule-based (no AI yet) request classification. |
| `decision_engine.py` | `DecisionEngine` — orders registered modules by the fixed Milestone 2 priority (Memory > Skills > Tools > Planning > Research > Model > Unknown). |
| `module_registry.py` | `ModuleRegistry` — the only place modules are looked up by name; `BrainRouter` never hardcodes which module handles what. |
| `module_bindings.py` | Wires `SmartAgent`'s concrete subsystems (memory, skills, tools, planning, research, models, voice, vision, automation) into registry handlers. |
| `events.py` | `EventBus` / `Events` — synchronous publish/subscribe; the router publishes `RequestReceived` and `BrainDecisionMade`, and `MemoryManager` publishes `MemorySaved`/`MemoryUpdated`/`MemoryDeleted`. |
| `router.py` | `BrainRouter` — runs the pipeline above: tries each candidate module in priority order until one succeeds, logging every decision (intent, chosen module, execution time, result). |
| `agent.py` | `SmartAgent` — the composition root: builds every subsystem, registers them, and delegates `handle_message()` to the router. |

Design principle carried over from the spec: **the Brain never performs a
task itself** — `BrainRouter` only classifies, decides, and delegates.
Every module currently registered except `memory` and `model` is still an
honest placeholder (it reports `success=False` for arbitrary text) — no
new features were added while building this pipeline, only the routing
structure around the features that already existed.

## Running it

```bash
pip install -r requirements.txt
python -m smartagent.main
```

This currently prints a startup message and echoes messages back — there
is no real reasoning yet.

## Running tests

```bash
pytest
```

## Tool Engine v1: the execution layer

Milestone 4 added the layer between Skills and the system. The full pipeline is:

```
User message
  -> BrainRouter  (intent classification + module routing)
  -> SkillEngine  (which skill handles this? permission check)
  -> Skill.execute()
  -> ToolEngine.run(tool_id, context, **params)
  -> Tool.execute()
  -> ActionResult  (bubbles back up through each layer)
```

**15 built-in tools** across 4 categories — all Python stdlib, no new deps:

| Category | Tools |
| --- | --- |
| `filesystem/` | `FileReadTool`, `FileWriteTool`, `DirectoryCreateTool`, `DirectoryListTool`, `CopyFileTool`, `MoveFileTool`, `DeleteFileTool`, `SearchFilesTool` |
| `text/` | `OpenTextFileTool`, `ReadMarkdownTool` |
| `system/` | `SystemInfoTool`, `DateTimeTool`, `EnvironmentTool` |
| `utilities/` | `UUIDTool`, `HashTool` |

**Adding a new tool** is just dropping a `.py` file with a `BaseTool` subclass into the right sub-package — `ToolLoader` auto-discovers it on the next startup.

**Safety** is enforced at two levels:
1. `PathValidator` — every filesystem tool resolves paths and rejects anything that escapes `Settings.workspace_path`.
2. `DeleteFileTool` additionally checks `check_not_protected_source()` — any path component matching `"smartagent"` or `"tests"` is blocked, regardless of where the workspace is configured.

**Permissions** — the same `PermissionManager` governs both Skills and Tools. New tool-specific permissions: `READ_FILES`, `WRITE_FILES`, `DELETE_FILES`, `CREATE_DIRECTORIES`, `READ_SYSTEM_INFO`. Total: 12 permissions.

## Model Framework v1: decoupling the Brain from any AI provider

Milestone 5 added `smartagent/models/` as a real package. The flow:

```
Brain (module_bindings.model_handler)
  -> ModelManager.generate(prompt, model_id=None, context=None)
       -> select_default()            # active model, else Settings.default_model_id, else None
       -> ModelRegistry.find/load()   # never imports a provider class directly
       -> BaseModel.generate()        # e.g. MockModelProvider — raw, provider-shaped output
       -> ResponseParser.parse()      # normalizes into ParsedResponse (text, tool_requests, usage, ...)
  <- ParsedResponse
```

- **`BaseModel`** — the abstract contract every provider implements:
  identity (`id`, `name`, `provider`, `version`), lifecycle/action methods
  (`initialize`, `load`, `generate`, `stream`, `embed`, `shutdown`), and
  overridable capability properties (`supports_streaming`, `supports_tools`,
  `context_window`, ...) that default to the most conservative value.
- **`MockModelProvider`** — the one working provider Milestone 5 ships:
  fully deterministic (SHA-256 digest of the prompt), no real AI, safe for
  tests/CI. `embed()` explicitly raises `NotImplementedError`.
- **`future_providers.py`** — 12 design-only stubs (Ollama, OpenAI,
  Anthropic, Gemini, LM Studio, OpenRouter, Azure OpenAI, Bedrock,
  DeepSeek, Mistral, vLLM, llama.cpp). Each only overrides the identity
  properties, so it stays abstract and is automatically skipped by
  provider discovery — implementing one for real is a future milestone.
- **`ModelRegistry`** — register/unregister/find/list/reload/enable/
  disable/discover/health_check/statistics, mirroring `ToolRegistry`.
  `discover()` auto-finds provider classes via `pkgutil` — no hardcoded imports.
- **`ModelManager`** — the *only* component allowed to talk to a provider
  (mirrors `ToolEngine`). Handles load/unload/switch/select-default,
  health, statistics, and publishes `ModelLoaded`/`ModelUnloaded`/
  `ModelSwitched`/`ModelHealthChecked` events.
- **`PromptBuilder`/`Prompt`** — assembles a provider-agnostic prompt from
  a message, system prompt, and an optional `ConversationContext`;
  `render()` for a flat string, `to_messages()` for chat-style turns.
- **`ConversationContext`** — history, running summaries, active goals/
  task, memory refs, tool outputs, token estimate.
- **`ResponseParser`/`ParsedResponse`** — normalizes any provider's raw
  response shape into one common structure.

**No model auto-loads by default** — `Settings.default_model_id` is `""`,
so `ModelManager.generate()` raises `NoActiveModelError` and the Brain's
`model` handler reports `success=False`, exactly like before this
milestone. Set `Settings.default_model_id = "mock"` to exercise the real
(deterministic) `MockModelProvider` end-to-end. The Milestone 1 placeholder
`ModelClient` (used by `SkillContext.model`) is unchanged.

## MARK Mind OS v1: computational self-awareness

Milestone 6 added `smartagent/mind/` — a persistent internal mind layered
on top of everything above. This is **not** consciousness; it's a
structured, inspectable representation of MARK's own state, kept honest by
one rule: **the Mind observes and represents, it never drives Brain
routing or changes any other subsystem's behavior.**

```
SmartAgent.__init__()
  -> builds memory, skills, tools, models, planning, research, ... (as before)
  -> builds self.mind = ExecutiveController(providers=MindProviders(...), event_bus=self.events)
       -> SelfModelEngine     (who am I, what am I doing, how confident/healthy)
       -> IdentityEngine      (round-trips SMARTAGENT.md's Markdown identity)
       -> WorkingMemory       (short-term, TTL-based scratch space)
       -> AttentionManager    (ranked focus + interrupt/resume stack)
       -> ContextManager      (assembles a bounded context bundle)
       -> ConfidenceEngine    (transparent, evidence-based scoring)
       -> StateMachine        (idle/thinking/planning/.../error/recovering)
       -> ReflectionEngine    (post-task self-assessment; flags, doesn't persist)
       -> HomeostasisEngine + DigitalSensorySystem + DigitalHomeostasisLoop
            (health scoring, computational "sensations", a synchronous tick())

SmartAgent.handle_message(message)
  -> (unchanged) BrainRouter.route(message) -> memory persist
  -> (new, guarded) self.mind observes: state transition + reflection + self-model sync
  -> returns result.message  # byte-for-byte identical to before this milestone
```

Key pieces, each in its own subpackage under `smartagent/mind/`:

| Subpackage | Responsibility |
| --- | --- |
| `executive/` | `ExecutiveController` — the sole coordinator; `MindProviders`, a DI bag of read-only callables into live `SmartAgent` state (goals/skills/tools/active model), so the Mind never imports `SmartAgent` directly. |
| `self_model/` | `SelfModel`/`SelfModelEngine` — MARK's answer to "who am I, what can I do, what am I doing, how confident, how healthy," diff-tracked. |
| `identity/` | `Identity`/`IdentityEngine` — loads/parses/updates/saves `SMARTAGENT.md`'s existing Markdown structure; falls back to a built-in default if the file is missing. |
| `working_memory/` | `WorkingMemory` — TTL-based short-term scratch space, explicitly distinct from the persistent Memory vault. |
| `attention/` | `AttentionManager` — importance ranking, bounded concurrent focus with eviction, interrupt/resume stack. |
| `context/` | `ContextManager`/`ContextBundle` — assembles a bounded context blob from conversation, working memory, knowledge, goals, research, reflections, tool outputs, and identity. |
| `confidence/` | `ConfidenceEngine` — transparent heuristic scoring from evidence/conflicts/missing-information/unknowns; never a fabricated flat score. |
| `state/` | `StateMachine`/`InternalState` — 12 named internal states with bounded transition history. |
| `reflection/` | `ReflectionEngine` — post-task self-assessment; flags what's memory-worthy, never writes to the vault itself. |
| `homeostasis/` | `HealthMetrics`/`HomeostasisEngine` (health scoring + band-change events), `DigitalSensorySystem` (10 named computational signals), `DigitalHomeostasisLoop` (a synchronous, explicitly-invoked `tick()` — not a background thread). |
| `events/` | `mind_events.py` — thin re-export of the shared `Events` plus a null-safe `publish_mind_event()` helper; the Mind has no bus of its own. |

`SmartAgent.handle_message()`'s Mind observation hook is wrapped in a
`try/except` — a bug in the Mind can never break message handling, and
`agent.mind.describe()` always gives a one-line summary of MARK's current
internal state for debugging. See `ARCHITECTURE.md` for diagrams and
`ROADMAP.md` for what's explicitly still design-only (Knowledge, Learning,
Curiosity, Discovery, Wisdom, and Cybersecurity Engines; Voice/Vision/
Browser/Automation integration into the Mind).

## Status

Six real subsystems now exist: **memory** (Markdown vault), **Brain v2**
(routing pipeline), **Skills Engine v1** (6 built-in skills), **Tool
Engine v1** (15 built-in tools, safety sandbox), **Model Framework v1**
(`ModelManager` + one deterministic `MockModelProvider`, 12 design-only
future provider stubs), and **MARK Mind OS v1** (`ExecutiveController` +
9 supporting engines — self-model, identity, working memory, attention,
context, confidence, state, reflection, homeostasis). Planning and
research have working goal/queue managers. Voice, vision, and automation
are documented, honest placeholders — each reports `success=False` for
arbitrary free text rather than silently doing nothing. See `ROADMAP.md`
for the full milestone plan and what's next.
