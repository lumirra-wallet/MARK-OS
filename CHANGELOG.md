# Changelog

All notable changes to SmartAgent are documented here. This project uses
[Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`), though
while the project is pre-1.0 every release may include breaking changes as
the architecture is still settling.

## [Unreleased]

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
