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
| **Current Version** | v0.3 (Brain v2) |

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
----------------------------------------------------------------------
🚧 Milestone 4 — Model Layer
   - Pluggable `ModelClient` backends (multiple providers, no hardcoded
     vendor), used behind the Decision Engine's `model` module

Future milestones (order indicative — see Build Order below):
   - Research Engine (real trusted-source search + summarization)
   - Knowledge Inbox (structured review queue for research findings)
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
| `models` | Language model backend clients | Abstract over LLM providers | — | Real provider integrations (multi-provider, no hardcoded vendor) |
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
| 4 — Model Layer | 🚧 Not started | 0% | Needs a provider-agnostic backend design |
| Research Engine | ⏳ Planned | 0% | Blocked on Model Layer for summarization |
| Skills Engine | ⏳ Planned | 0% | Blocked on at least one real tool/model |
| Voice | ⏳ Planned | 0% | — |
| Vision | ⏳ Planned | 0% | — |
| Automation loop | ⏳ Planned | 0% | — |
| Desktop UI / Web Dashboard / API Server | ⏳ Planned | 0% | Later-stage per Build Order |

*Keep this table in sync with `CHANGELOG.md` — update the row when a
milestone's status changes rather than adding a new table.*

---

## TODO Tracker

**High Priority**
- Decide on the first real `ModelClient` backend (Milestone 3).
- Add tests for `module_bindings.py`'s handler wiring specifically (currently covered indirectly via `test_brain_router.py` and `test_agent.py`).

**Medium Priority**
- Give `DecisionEngine` intent-aware branching once `skills`/`tools` have real members worth disambiguating between.
- Add a `Settings` source beyond hardcoded defaults (env vars / config file).

**Low Priority**
- Consider a lightweight index for `Vault.find_path()` if the vault grows large enough that directory scanning becomes noticeable.

**Ideas**
- A `smartagent doctor` CLI command that reports module registry health using `ActionResult.confidence` trends.

**Research Topics**
- Trusted-source allowlist design for `ResearchManager.search()`.
- Local vs. hosted model tradeoffs for the Model Layer.

**Known Issues**
- None currently tracked. File one here (with a short repro) before fixing, so the roadmap stays the single source of truth for outstanding work.

**Technical Debt**
- `Vault.find_path()` scans every category directory per lookup — fine at personal scale, revisit if it becomes a bottleneck.
