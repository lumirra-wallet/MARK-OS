# SmartAgent Roadmap

This is the master development plan for the SmartAgent Operating System —
for both MARK (the AI) and any future human developer. It tracks vision,
architecture, milestone status, and what's next. See `SMARTAGENT.md` for
MARK's identity/mission/principles, `CHANGELOG.md` for what shipped, and
`CONTRIBUTING.md` for how to add a new module.

---

## SmartAgent Vision

| | |
| --- | --- |
| **Project Name** | SmartAgent |
| **Owner** | Mr. Smart |
| **AI Name** | MARK |
| **Current Version** | v1.0 (Ollama Integration) |

**Mission:** MARK is an intelligent AI Operating System created
exclusively for Mr. Smart — a trusted executive assistant, engineer,
researcher, strategist, and teacher that helps build businesses, write
software, automate repetitive work, learn continuously, and organize
knowledge.

**Long-term vision:** every capability (memory, reasoning, research,
planning, voice, vision, automation, computer control) exists as an
independent, replaceable module behind a stable interface, coordinated by
a Brain that classifies requests, decides who should handle them, and
never depends on a single AI provider.

**Development philosophy:** build incrementally, one milestone at a time.
Each milestone must keep every previously shipped feature working, add
real tests, and document its design decisions — never "add random
features" beyond what a milestone explicitly asks for.

**Project goals:**
- A personal AI OS MARK and Mr. Smart both trust with real responsibility.
- A codebase modular enough that any single module (a model provider, a
  memory backend, a skill) can be swapped without touching the rest.
- Documentation good enough that a new contributor (human or AI) can
  onboard from `README.md` + this file alone.

---

## Development Stages

```
✅ Milestone 1 — Foundation
   - Modular package architecture (brain, memory, models, skills, tools,
     voice, vision, automation, config, ui, logs, research, planning)
   - Centralized logging & configuration
   - Working placeholder agent, tests

✅ Milestone 1.5 — Memory v1 (Markdown Vault)
   - Persistent Markdown memory vault (remember/recall/search/update/
     delete/list_categories)
   - No database, no vector search, no AI model connected

✅ Milestone 2 — Brain v2 (Decision Engine)
   - BrainRouter, IntentAnalyzer, DecisionEngine, ModuleRegistry,
     ActionResult, EventBus
   - Every request routed through a single, auditable pipeline

✅ Milestone 2.1 — Project Management & Development Roadmap
   - ROADMAP.md, CHANGELOG.md, CONTRIBUTING.md
   - Documented architecture, build order, coding standards, project rules

✅ Milestone 3 — Skills Engine v1
   - `BaseSkill` abstract contract, `SkillMetadata`, `SkillContext` (DI)
   - `SkillRegistry`: register/unregister/enable/disable/reload/list/find
   - `SkillEngine`: confidence-ordered dispatch, permission enforcement,
     chain-of-responsibility fallthrough (mirrors BrainRouter's design)
   - `SkillLoader`: auto-discovers `BaseSkill` subclasses via `pkgutil` —
     drop a file in `builtin/`, nothing else to edit
   - `PermissionManager` + `Permission` enum (7 permissions; READ_MEMORY
     and WRITE_MEMORY granted by default; everything else opt-in)
   - Six built-in skills: `MemorySkill`, `KnowledgeSkill`, `PlanningSkill`,
     `ResearchSkill`, `ConversationSkill`, `SystemInfoSkill`
   - `module_bindings` upgraded: `skills_handler` now delegates to
     `SkillEngine.execute()` instead of returning a placeholder
   - Fixed double-memory bug: `handle_message` checks EventBus for a
     `MemorySaved` event fired during routing; skips Journal auto-persist
     if a skill already wrote to memory
   - 74 new tests; full suite 128 passing, 0 regressions

✅ Milestone 4 — Tool Engine v1
   - Clear architectural boundary: Brain → Skill → ToolEngine → Tool → ActionResult
     (the Brain never calls tools directly; Skills call them by id)
   - `BaseTool` abstract contract: `id`, `name`, `description`, `version`,
     `author`, `category`, `permissions`, `required_os`,
     `required_dependencies`; lifecycle hooks `initialize()`, `shutdown()`,
     `health()`; `validate(params)`, `execute(params, context)`
   - `ToolMetadata` (frozen snapshot), `ToolContext` (DI bundle: settings,
     workspace_path, events — kept minimal so tools don't import the agent)
   - `ToolCategory` enum: FILESYSTEM / SYSTEM / UTILITIES / TEXT / FUTURE
   - `ToolRegistry`: register/unregister/find/list/reload/enable/disable/
     health_check/statistics + backward-compat `get()`/`list_available()`
   - `ToolEngine`: named tool dispatch, permission enforcement,
     param validation, execution timing, EventBus publishing of
     `ToolExecuted` and `ToolLoaded`; shares one `PermissionManager` with
     `SkillEngine` — one authority for both layers
   - `ToolLoader`: uses `pkgutil.walk_packages` (recursive) to discover
     `BaseTool` subclasses across sub-packages automatically
   - `PathValidator` + `SafetyError` (safety.py): sandboxes every filesystem
     tool to `ToolContext.workspace_path`; `check_not_protected_source()`
     blocks deletion of `smartagent/` or `tests/` regardless of location
   - Five new `Permission` enum values: READ_FILES, WRITE_FILES,
     DELETE_FILES, CREATE_DIRECTORIES, READ_SYSTEM_INFO (total: 12)
   - 15 built-in tools across 4 sub-packages (stdlib only, no new deps):
       filesystem/  FileReadTool, FileWriteTool, DirectoryCreateTool,
                    DirectoryListTool, CopyFileTool, MoveFileTool,
                    DeleteFileTool, SearchFilesTool
       text/        OpenTextFileTool, ReadMarkdownTool
       system/      SystemInfoTool, DateTimeTool, EnvironmentTool
       utilities/   UUIDTool, HashTool
   - `SkillContext.tool_engine` added so skills can call tools without
     importing `SmartAgent` (avoids circular imports)
   - `agent.tool_engine` shared with `agent.skill_engine` via same
     `PermissionManager`; `module_bindings.tools_handler` now reports
     available tools via `ToolEngine.describe()`
   - `Settings.workspace_path` added (default: `"."`)
   - 148 new tests; full suite 276 passing, 0 regressions

✅ Milestone 5 — Model Framework v1
   - New `smartagent.models` package (`base/`, `providers/`, `registry/`,
     `manager/`, `context/`, `prompts/`, `responses/`, `config/`) —
     decouples the Brain from any specific AI provider
   - `BaseModel` abstract contract: identity properties (`id`, `name`,
     `provider`, `version`), lifecycle/action methods (`initialize`,
     `load`, `generate`, `stream`, `embed`, `shutdown`), overridable
     capability properties (`context_window`, `supports_streaming`,
     `supports_tools`, `supports_images`, `supports_embeddings`,
     `supports_functions`), concrete `metadata()`/`status()`/`health()`
   - `MockModelProvider`: the one working provider — deterministic, no
     real AI, safe for tests/CI; `embed()` explicitly not implemented
   - `future_providers.py`: 12 design-only interface stubs (Ollama,
     OpenAI, Anthropic, Gemini, LM Studio, OpenRouter, Azure OpenAI,
     Bedrock, DeepSeek, Mistral, vLLM, llama.cpp) — each stays abstract
     (uninstantiable) on purpose, so discovery never wires one up by accident
   - `ModelRegistry` + `model_loader.discover_provider_classes()`:
     register/unregister/find/list/reload/enable/disable/discover/
     health_check/statistics, mirroring `ToolRegistry`/`SkillRegistry`
   - `ModelManager`: the only component allowed to talk to providers —
     load/unload/switch/select_default/generate/stream/health_check/
     statistics/describe; publishes `ModelLoaded`/`ModelUnloaded`/
     `ModelSwitched`/`ModelHealthChecked` onto the shared `EventBus`
   - `PromptBuilder`/`Prompt`: assembles a provider-agnostic prompt from a
     message, system prompt, `ConversationContext`, and skill context;
     `render()` (flat string) and `to_messages()` (chat turns)
   - `ConversationContext`: history, summaries, active goals/task, memory
     refs, tool outputs, timestamps, token estimate — no auto-compression yet
   - `ResponseParser`/`ParsedResponse`: normalizes any provider's raw
     response shape into text/tool_requests/confidence/metadata/timing/usage
   - `ModelSettings`: default model id, temperature/top_p/top_k/max_tokens,
     streaming flag, timeout, placeholder `api_keys`/`local_model_paths`
     (never hardcoded)
   - Brain integration: `module_bindings.model_handler` now calls
     `agent.model_manager.generate()`, never a provider directly.
     `Settings.default_model_id` defaults to `""` so no model auto-loads —
     behavior is unchanged from before this milestone unless a deployment
     opts in
   - Legacy `ModelClient`/`SkillContext.model` kept as-is for backward compatibility
   - 93 new tests; full suite 369 passing, 0 regressions

✅ Milestone 6 — MARK Mind OS v1
   - New `smartagent.mind` package: a persistent internal mind layered on
     top of Brain/Memory/Skills/Tools/Models — **computational
     self-awareness, not consciousness** (per `SMARTAGENT.md` Part 0 of
     the spec). The Mind observes and represents; it never drives Brain
     routing or changes any existing subsystem's behavior.
   - `executive/` — `ExecutiveController` (the sole coordinator, Part 1)
     + `MindProviders` (DI bag of read-only callables `SmartAgent` binds
     to its live goals/skills/tools/model state — avoids a circular
     import back into `smartagent.brain.agent`)
   - `identity/` — `Identity` dataclass + `IdentityEngine` (Part 3):
     round-trips `SMARTAGENT.md`'s existing Markdown headings
     (load/parse/update/save), falls back to a built-in
     `default_identity()` if the file is missing/unparseable
   - `self_model/` — `SelfModel` + `SelfModelEngine` (Part 2): answers
     "who am I / what can I do / what am I doing / how confident / how
     healthy", diff-tracked `recent_changes`, publishes `SelfModelUpdated`
   - `working_memory/` — `WorkingMemory` (Part 4): short-term, TTL-based
     scratch space, explicitly not a Memory-vault replacement
   - `attention/` — `AttentionManager` (Part 5): importance ranking, a
     bounded `max_concurrent` focus set with eviction, interrupt/resume
     stack, publishes `AttentionShifted`
   - `context/` — `ContextManager`/`ContextBundle` (Part 6): assembles a
     bounded context blob from conversation/working-memory/knowledge/
     goals/research/reflection/tool-output/identity sources
   - `confidence/` — `ConfidenceEngine` (Part 7): transparent heuristic
     scoring (evidence/conflicts/missing-info/unknowns), bounded history,
     publishes `ConfidenceChanged` — never a fabricated flat score
   - `state/` — `StateMachine`/`InternalState` (Part 9): 12 named
     internal states (idle, listening, thinking, planning, researching,
     executing, reflecting, learning, waiting, sleeping, error,
     recovering), bounded transition history, publishes `StateChanged`
   - `reflection/` — `ReflectionEngine` (Part 10): post-task
     self-assessment flags (`should_become_memory`,
     `could_improve_future_performance`) — never writes to the Memory
     vault itself, only flags what's worth remembering
   - `homeostasis/` — Parts 8, 12 & 13 together: `HealthMetrics` +
     `HomeostasisEngine` (score → healthy/degraded/critical band,
     `HealthChanged` only on band transitions), `DigitalSensorySystem` +
     `SensorySignal` (10 named computational signals, e.g.
     `high_cpu_load`, `low_confidence`, `tool_failure`), and
     `DigitalHomeostasisLoop.tick()` — a synchronous, explicitly-invoked
     self-check (not a background thread) answering "healthy? overloaded?
     making progress? do goals match mission? anything failing? should I
     notify the owner?"
   - 10 new `Events` constants added to `smartagent.brain.events`:
     `GoalChanged`, `AttentionShifted`, `ConfidenceChanged`,
     `HealthChanged`, `StateChanged`, `TaskStarted`, `ReflectionFinished`,
     `SelfModelUpdated`, `SensorySignalDetected`, `WorkingMemoryUpdated`
     — published onto the same shared `EventBus`, no separate Mind bus
   - `SmartAgent.__init__` now builds `self.mind = ExecutiveController(...)`
     last, wired via `MindProviders` into the agent's own goals/skills/
     tools/model_manager. `handle_message()` gained a guarded
     (try/except) observation hook that transitions Mind state and
     records a reflection around each request — wrapped so a Mind bug can
     never break message handling, and verified to leave
     `handle_message()`'s returned message byte-for-byte unchanged
   - Explicitly **not** implemented this milestone (design-only,
     future-compatible hooks per the spec): Knowledge/Learning/
     Curiosity/Discovery/Wisdom/Cybersecurity Engines, Voice, Vision,
     Browser, Automation integration into the Mind, Ollama/internet
     access, and any change to Memory/Brain routing/Skills/Tools/Model
     Framework behavior
   - New `ARCHITECTURE.md` with ASCII diagrams for the Mind overview,
     data flow, and each major engine
   - 86 new tests; full suite 455 passing, 0 regressions
----------------------------------------------------------------------

✅ Milestone 7 — Knowledge Engine v1
   - `smartagent.knowledge` package: directed knowledge graph (concepts as
     nodes, relationships as edges). 20-field Concept model (id, title,
     description, summary, category, tags, aliases, examples, difficulty,
     status, confidence, importance, created_at, updated_at, author, owner,
     source_ids, evidence_ids, relationship_ids, dependency_ids,
     contradiction_ids, verification_status, revision_history).
   - KnowledgeGraph: BFS/DFS traversal, shortest path, merge/split,
     dependency lookup, adjacency export for future visualization.
   - 15 typed RelationshipTypes: depends_on, part_of, related_to,
     contradicts, extends, implements, inherits, causes, uses, creates,
     requires, improves, replaces, supports, references.
   - Source + Evidence engines for provenance tracking.
   - ConfidenceEngine: transparent scoring (evidence quality 40%,
     source reliability 30%, corroboration bonus, verification bonus,
     age decay, contradiction penalty, manual adjustment).
   - KnowledgeInbox: approval gate (propose → validate → conflict detect
     → confidence score → Mr. Smart approve → graph). Nothing enters
     automatically. Contradiction detection flags conflicts without
     overwriting.
   - OntologyEngine: hierarchical category tree, path inheritance,
     `ensure_path()`, 7 default root categories.
   - QueryEngine: 12 structured query operations.
   - KnowledgeSearch: deterministic full-text search, no embeddings.
   - KnowledgeStorage: human-readable JSON in `knowledge/` (separate
     from memory `vault/`). KnowledgeStats + growth history.
   - Brain integration: `knowledge_handler` in ModuleRegistry (confidence
     0.6). Brain communicates only through KnowledgeManager.
   - `Settings.knowledge_path` added. No AI reasoning, no Ollama, no
     vector databases, no internet, no voice/vision/cybersecurity.
   - 119 new tests; all existing tests pass, 0 regressions.

✅ Milestone 8 — MARK Console OS v1
   - `python -m smartagent.main` now launches a persistent interactive console
     instead of exiting immediately.  MARK stays alive until the user types
     `exit`, `quit`, presses Ctrl+C, or sends EOF.
   - Professional startup banner (name, version, all subsystem status).
   - Command framework under `smartagent/ui/`: `console.py`,
     `repl.py`, `renderer.py`, `command_router.py` + 8 command modules
     under `commands/`.  No `if/elif` dispatch — each module has its own
     `register(router)` call; new milestones add a new file and one line.
   - Commands: `help`, `status`, `version`, `clear`, `exit`/`quit` (SYSTEM);
     `mind`, `identity`, `health`, `state`, `attention`, `context` (MIND);
     `remember`, `recall`, `search-memory` (MEMORY);
     `knowledge add/search/graph/stats`, `inbox`, `approve`, `reject` (KNOWLEDGE);
     `skills`, `tools`, `models`, `events`.
   - All handlers are presentation-only: every operation goes through the
     existing MemoryManager / KnowledgeManager / ExecutiveController /
     SkillEngine / ToolEngine / ModelManager / EventBus.  No logic duplicated.
   - Logging: `configure_logging()` gains `log_file` + `log_to_console` params.
     `main.py` now routes logs to `logs/mark.log` only (console is clean).
   - 78 new tests; full suite 652 passing, 0 regressions.

✅ Milestone 9 — Ollama Integration
   - Architecture enforced: Brain → ModelManager → BaseModel → OllamaProvider
     → Ollama Local API.  Nothing above ModelManager ever imports OllamaProvider.
   - `OllamaProvider` (smartagent/models/providers/ollama_provider.py):
     one instance per Ollama model name; `_exclude_from_discovery = True`
     prevents auto-registration with wrong settings.
   - `OllamaModelDiscovery.list_models()` — `GET /api/tags`; returns `[]`
     (never raises) when the server is offline.
   - `OllamaModelInfo` dataclass: name, size, family, modified_at, status.
   - `ModelManager.load_ollama_models()` — registers llama3.1:8b,
     qwen2.5-coder:7b, and any extras installed on the server.
   - New alias methods on `ModelManager`: `list_models()`, `load_model()`,
     `unload_model()`, `switch_model()`, `active_model()`.
   - `model_loader.discover_provider_classes()` respects
     `_exclude_from_discovery` on any provider class.
   - `ModelSettings` + `Settings` gain `ollama_base_url`,
     `ollama_default_model`, `ollama_coding_model` (all configurable).
   - `MARK_SYSTEM_PROMPT` constant in `mark_system_prompt.py`.
   - `Prompt` dataclass extended with `knowledge_context`, `mind_state`,
     `identity`, `goals` (all default-empty; fully backward-compatible).
   - `PromptBuilder.build()` accepts matching keyword-only args.
   - Console commands: `models`, `model use/current/info/list`, `chat`.
   - Coding auto-routing: programming keywords → qwen2.5-coder:7b.
   - `CommandRouter.set_fallback()` + free-text fallback in Console.
   - Fallback behaviour: Ollama offline → "Ollama server unavailable.",
     no crash, rest of MARK fully operational.
   - SmartAgent.init calls `load_ollama_models()` at startup.
   - 105 new tests; full suite 763 passing, 0 regressions.
   - Uses stdlib only (urllib) — no new dependencies.

Future milestones (order indicative — see Build Order below):
   - Research Engine (real trusted-source search + summarization)
   - Plugin System (third-party module registration)
   - Browser Automation
   - Computer Control
   - Voice (real speech-to-text / text-to-speech backend)
   - Vision (real image understanding backend)
   - Learning Engine (continuous learning with owner approval)
   - Planning Engine (real goal decomposition via TaskPlanner)
   - Task Scheduler (real automation loop)
   - Desktop UI
   - Web Dashboard
   - API Server
   - Security hardening
   - Performance tuning
   - Release Candidate
```

---

## Architecture

Every package below is independently testable and, per
`SMARTAGENT.md`'s architecture philosophy, replaceable without rebuilding
the rest of the system.

| Package | Purpose | Responsibilities | Depends on | Future improvements |
| --- | --- | --- | --- | --- |
| `brain` | Central orchestrator (Brain v2) | Classify intent, decide which module handles a request, execute it, log the decision, publish events | `memory`, `models`, `skills`, `tools`, `planning`, `research`, `voice`, `vision`, `automation`, `config`, `logs` | Intent-aware module selection once skills/tools have real members; pluggable decision strategies |
| `memory` | Persistent knowledge store (Memory v1) | Store/retrieve/search/update/delete Markdown memory files, organized by category | `logs`, `brain.events` (optional) | Semantic/vector search; multiple backends behind the same API |
| `models` | Model Framework v1 | `ModelManager` loads/switches providers behind `BaseModel`; `ModelRegistry`, `PromptBuilder`, `ConversationContext`, `ResponseParser`, `ModelSettings` | `logs`, `brain.events` (optional) | Real cloud/local provider integrations (Ollama, OpenAI, Anthropic, etc. — currently design-only stubs) |
| `mind` | MARK Mind OS v1 — computational self-awareness | `ExecutiveController` coordinates self-model, identity, working memory, attention, context, confidence, state, reflection, and homeostasis; observes the rest of the system via read-only `MindProviders`, never drives routing | `brain.events` (optional), reads `SMARTAGENT.md` for identity | Knowledge/Learning/Curiosity/Discovery/Wisdom/Cybersecurity Engines, Voice/Vision/Browser/Automation integration — all design-only today |
| `skills` | Composed, user-facing capabilities | Register/execute higher-level tasks built from tools + memory + models | `tools`, `memory`, `models` | First concrete skills |
| `tools` | Low-level, single-purpose actions | Register/execute atomic capabilities (calculators, file access, etc.) | — | First concrete tools |
| `voice` | Speech I/O | Transcribe audio, synthesize speech | — | Real STT/TTS backend |
| `vision` | Image/video understanding | Describe/interpret visual input | — | Real vision backend |
| `automation` | Scheduled/background tasks | Register and (eventually) run recurring tasks | — | Real scheduling loop |
| `research` | Trusted-source research | Search, summarize, queue for owner approval, commit to memory | `memory` | Real search + summarization backend, enforced trusted-source allowlist |
| `planning` | Goal tracking & decomposition | Track goals, break them into tasks | — | Real decomposition algorithm (model- or skill-driven) |
| `config` | Centralized settings | Single `Settings` object the rest of the app depends on | — | Environment variables / config file / secrets sources |
| `logs` | Centralized logging | Consistent logger setup across the app | — | Log files, rotation, structured logging |
| `ui` | User-facing front-ends | Drive a `SmartAgent` from the CLI (and later others) | `brain` | Real input/output loop; additional front-ends |
| `tests` | Test suite | Mirrors the package structure above | everything | Keep 100% coverage on core modules (see Coding Standards) |

---

## Build Order

Recommended dependency order for future work — each stage assumes the
ones above it are stable:

```
Foundation
   ↓
Brain
   ↓
Memory
   ↓
Models
   ↓
Skills
   ↓
Research
   ↓
Planning
   ↓
Tools
   ↓
Automation
   ↓
Voice
   ↓
Vision
   ↓
Desktop UI
```

---

## Coding Standards

- Small modules, one responsibility per class.
- Type hints everywhere (`from __future__ import annotations` + built-in
  generics).
- Google-style docstrings on every public class/function, explaining
  *why*, not just *what*, for non-obvious decisions.
- 100% test coverage target for core modules (`brain`, `memory`).
- No duplicated logic — extract a shared helper instead of copy-pasting.
- Loose coupling: modules communicate through stable interfaces
  (`ModuleHandler`, `ActionResult`, `EventBus`) rather than importing each
  other's internals.
- Dependency injection where appropriate (e.g. `BrainRouter` takes a
  `ModuleRegistry`/`EventBus` instead of constructing its own by default
  only as a convenience fallback).
- Configuration-driven architecture: behavior (vault location,
  categories, enabled tools) comes from `Settings`, not hardcoded values.

---

## Project Rules

- Never hardcode secrets, API keys, or credentials.
- Never hardcode a specific AI provider — `models` must stay swappable.
- Everything must be modular; a module should be removable/replaceable
  without rewriting unrelated packages.
- Every new module must ship with tests.
- Every feature must be documented (README, this roadmap, or both).
- Every important class must have a docstring.
- Keep backwards compatibility — a milestone must not break a previous
  one's tests or public API without an explicit, documented reason.

---

## Future Intelligence

Planned systems, once their prerequisite milestones land:

- **Decision Engine** — ✅ v1 shipped in Brain v2 (rule-based); future
  versions may add confidence-weighted or learned ranking.
- **Reasoning Engine** — multi-step reasoning on top of the model layer.
- **Knowledge Engine** — structured, queryable knowledge beyond flat
  memory search.
- **Research Engine** — real trusted-source search + summarization.
- **Learning Engine** — continuous learning, always owner-approved before
  becoming permanent memory (see `SMARTAGENT.md` Safety section).
- **Conversation Engine** — multi-turn dialogue state, not just
  single-message routing.
- **Memory Engine** — smarter retrieval (semantic/vector) behind the
  existing `MemoryManager` API.
- **Plugin Marketplace** — third-party modules registered into
  `ModuleRegistry`.
- **Multi-Agent Collaboration** — multiple specialized MARK instances
  coordinating.
- **Self Diagnostics** — MARK monitoring its own module health.
- **Performance Monitor** — tracking `ActionResult.execution_time` trends
  over time.
- **Goal Tracking** — ✅ basic version shipped (`GoalManager`); needs
  persistence + prioritization.
- **Long-Term Planning** — real `TaskPlanner` decomposition.
- **Knowledge Inbox** — a reviewable queue distinct from the research
  approval queue, for anything MARK learns passively.

---

## Project Status

| Milestone | Status | Progress | Notes |
| --- | --- | --- | --- |
| 1 — Foundation | ✅ Done | 100% | Architecture, logging, config, tests |
| 1.5 — Memory v1 | ✅ Done | 100% | Markdown vault; no DB, no vector search |
| 2 — Brain v2 | ✅ Done | 100% | Router, Intent Analyzer, Decision Engine, Registry, ActionResult, EventBus |
| 2.1 — Roadmap & PM docs | ✅ Done | 100% | This file, CHANGELOG.md, CONTRIBUTING.md |
| 3 — Skills Engine v1 | ✅ Done | 100% | PermissionManager, SkillEngine, 6 built-in skills, 128 tests |
| 4 — Tool Engine v1 | ✅ Done | 100% | ToolEngine, 15 built-in tools, PathValidator safety, 276 tests |
| 5 — Model Framework v1 | ✅ Done | 100% | ModelManager, ModelRegistry, MockModelProvider, PromptBuilder, ConversationContext, ResponseParser, 369 tests |
| 6 — MARK Mind OS v1 | ✅ Done | 100% | ExecutiveController, SelfModel, IdentityEngine, WorkingMemory, AttentionManager, ContextManager, ConfidenceEngine, StateMachine, ReflectionEngine, Homeostasis + Sensory + Loop, 455 tests |
| 8 — Console OS v1 | ✅ Done | 100% | REPL, CommandRouter, console commands for all subsystems |
| 9 — Ollama Integration | ✅ Done | 100% | OllamaProvider, ModelDiscovery, coding auto-routing, fallback chat, 763 tests |
| 10 — Streaming Upgrade | ✅ Done | 100% | generate_stream/chat_stream, spinner, metrics, prompt cache, warmup, lazy loading, ~60 new tests |
| 11 Phase 1 — Executive Framework | ✅ Done | 100% | ExecutiveController, Planner (5 templates), TaskGraph, TaskQueue, Scheduler (stub), Orchestrator, plan/tasks commands, 142 new tests |
| 11 Phase 2 — Worker Agents | ✅ Done | 100% | BaseWorker + 9 specialists (Research/Planning/Design/Coding/Testing/Review/Docs/Report/Knowledge/Memory), real WorkerRegistry, workers/worker info commands |
| 11 Phase 3 — Scheduler v2 | ✅ Done | 100% | Cancellation, queue/run/cancel commands, is_cancelled guard in Scheduler |
| 11 Phase 4 — Ollama Workers | ⏳ Planned | 0% | Workers connected to Ollama; each with specialist system prompt |
| 11 Phase 5 — Executive Loop | ⏳ Planned | 0% | User → Executive → Workers → Merge → Response; trace/history commands |
| Research Engine | ⏳ Planned | 0% | Blocked on a real Model Framework provider for summarization |
| Voice | ⏳ Planned | 0% | — |
| Vision | ⏳ Planned | 0% | — |
| Automation loop | ⏳ Planned | 0% | — |
| Desktop UI / Web Dashboard / API Server | ⏳ Planned | 0% | Later-stage per Build Order |

*Keep this table in sync with `CHANGELOG.md` — update the row when a
milestone's status changes rather than adding a new table.*

---

## TODO Tracker

**High Priority**
- Implement a first real Model Framework provider (Ollama is the natural
  first choice — local, no API key) by fleshing out its `future_providers.py`
  stub into a real `BaseModel` subclass and wiring `ModelSettings`.
- Refactor existing skills (e.g. `MemorySkill`) to call `ToolEngine` for any filesystem work, now that `FileReadTool`/`FileWriteTool` exist (Skills must never manipulate the filesystem directly per the spec).
- Add tests for `module_bindings.py`'s handler wiring specifically (currently covered indirectly via `test_brain_router.py` and `test_agent.py`).
- Wire a real periodic scheduler (via `smartagent.automation`) to call `agent.mind.homeostasis_loop.tick()` on an interval, instead of only ever being invoked manually/in tests.
- Decide where `ReflectionEngine`'s `memory_worthy()` output should actually be persisted (a new Skill, or the future Learning Engine) — currently flagged but never written to the vault.

**Medium Priority**
- Give `DecisionEngine` intent-aware branching once `skills`/`tools` have real members worth disambiguating between.
- Add a `Settings` source beyond hardcoded defaults (env vars / config file).

**Low Priority**
- Consider a lightweight index for `Vault.find_path()` if the vault grows large enough that directory scanning becomes noticeable.

**Ideas**
- A `smartagent doctor` CLI command that reports module registry health using `ActionResult.confidence` trends.

**Research Topics**
- Trusted-source allowlist design for `ResearchManager.search()`.
- Local vs. hosted model tradeoffs for the first real Model Framework provider.

**Known Issues**
- None currently tracked. File one here (with a short repro) before fixing, so the roadmap stays the single source of truth for outstanding work.

**Technical Debt**
- `Vault.find_path()` scans every category directory per lookup — fine at personal scale, revisit if it becomes a bottleneck.
