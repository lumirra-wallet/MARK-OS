# Changelog

All notable changes to SmartAgent are documented here. This project uses
[Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`), though
while the project is pre-1.0 every release may include breaking changes as
the architecture is still settling.

## [Unreleased]

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
