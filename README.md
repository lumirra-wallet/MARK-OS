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
├── brain/              # The agent orchestrator (agent.py)
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
long-term architecture vision — this repository is the implementation of
that vision, built incrementally.

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

Mostly scaffold, with one real feature implemented: **memory** now
persists to a Markdown vault (see above). Every other module under
`smartagent/` still contains a documented, working placeholder (not empty
stubs) so the project is importable and testable end-to-end. Features will
continue to be implemented module by module next.
