# SmartAgent

SmartAgent is a personal AI assistant, built incrementally. This repository
currently contains a clean, modular project scaffold — placeholder
implementations only. Real functionality (language model reasoning,
persistent memory, skills, tools, voice, vision, and automations) will be
layered in one feature at a time, inside the package structure below.

## Project layout

```
smartagent/
├── main.py             # Process entry point — boots the agent and CLI
├── brain/              # Brain v2: BrainRouter, IntentAnalyzer, DecisionEngine,
│                       # ModuleRegistry, ActionResult, EventBus, agent.py
├── memory/             # Persistent Markdown memory vault (see below)
├── models/             # Language model backend clients
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
tests/                  # Test suite, mirrors the smartagent package structure
```

See `SMARTAGENT.md` for MARK's identity, mission, principles, and
long-term architecture vision, and `ROADMAP.md` for the full development
plan, milestone status, and coding standards — this repository is the
implementation of that vision, built incrementally.

Additional project documents:

- [`ROADMAP.md`](ROADMAP.md) — vision, milestones, architecture, build order, coding standards, TODOs.
- [`SMARTAGENT.md`](SMARTAGENT.md) — MARK's identity, mission, principles, and safety rules.
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

## Status

Two real subsystems now exist: **memory** (Markdown vault) and **Brain
v2** (the routing pipeline above). Every capability module underneath the
Brain — skills, tools, planning, research, models, voice, vision,
automation — is still a documented, working placeholder (not empty
stubs), so the whole pipeline is importable and testable end-to-end even
though most modules currently report "not available yet." See
`ROADMAP.md` for the full milestone plan and what's next.
