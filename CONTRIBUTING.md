# Contributing to SmartAgent

SmartAgent is built incrementally, one milestone at a time (see
`ROADMAP.md`). This file explains how to work in this codebase — folder
structure, coding standards, testing, commit conventions, and how to add
a new module.

## Folder structure

```
smartagent/
├── main.py         # Process entry point
├── brain/          # Brain v2: router, intent analyzer, decision engine,
│                   # module registry, action result, event bus, agent.py
├── memory/         # Persistent Markdown memory vault
├── models/         # Language model backend clients
├── skills/         # Composed, user-facing capabilities
├── tools/          # Low-level, single-purpose capabilities
├── voice/          # Speech-to-text / text-to-speech
├── vision/         # Image/video understanding
├── automation/     # Scheduled/background tasks
├── config/         # Centralized settings
├── ui/             # User-facing front-ends
├── logs/           # Centralized logging setup
├── research/       # Trusted-source research + owner-approval queue
└── planning/       # Goal tracking and task decomposition
vault/              # Runtime data: persisted memories (gitignored per-file)
tests/              # Test suite, one file per module/class under test
```

Each package should be understandable on its own — read its `__init__.py`
docstring first, then the module you need.

## Coding standards

See `ROADMAP.md`'s "Coding Standards" section for the full list. In short:

- Small modules, one responsibility per class.
- Type hints everywhere (`from __future__ import annotations`).
- Google-style docstrings on every public class/function — explain *why*
  a non-obvious decision was made, not just what the code does.
- No duplicated logic; extract a shared helper instead.
- Loose coupling: depend on stable interfaces (`ModuleHandler`,
  `ActionResult`, `EventBus`, registries) instead of another module's
  internals.
- Configuration-driven: new behavior should read from `Settings`, not be
  hardcoded, whenever it's something a deployment might reasonably want
  to change.

## Testing

```bash
pip install -r requirements.txt
pytest
```

- Every new module needs tests in `tests/`, named `test_<module>.py`.
- Tests must never touch the project's real `vault/` directory — always
  point `MemoryManager`/`Settings.vault_path` at pytest's `tmp_path`
  fixture.
- Keep every existing test passing. If a milestone's spec requires an API
  change (like Memory v1 replacing the old placeholder `MemoryManager`),
  update the existing tests to match the new, real behavior rather than
  deleting them — the goal is that the suite always reflects current,
  intended behavior.

## Commit message conventions

Use short, imperative-mood summaries that name the milestone or module
when relevant, e.g.:

```
Add BrainRouter chain-of-responsibility routing (Milestone 2)
Fix ResearchManager.approve() memory.remember() call signature
Document Brain v2 pipeline in README
```

## Branch strategy

This project currently develops on a single main line, milestone by
milestone — keep each unit of work (one milestone or one clearly-scoped
fix) as a self-contained set of changes with passing tests before moving
to the next.

## How to add a new module

1. **Decide where it lives.** If it's a new capability category, give it
   its own top-level package (mirroring `brain`, `memory`, `skills`, etc.,
   per `ROADMAP.md`'s Architecture table). If it extends an existing
   category (e.g. a new `Tool` subclass), it belongs inside that package.
2. **Define the interface first.** Follow the existing pattern: an
   abstract base (like `Tool`/`Skill`) if there will be multiple
   implementations, or a small class with a clear public API otherwise.
3. **Wire it into the Brain, if applicable.** If the new module should be
   selectable by `BrainRouter`, add a handler for it in
   `smartagent/brain/module_bindings.py` and register it under a stable
   name via `ModuleRegistry.register()`. Never make `BrainRouter` or
   `DecisionEngine` reference the module by name directly — they only
   know registry names.
4. **Return an `ActionResult`.** Any handler registered with the Brain
   must return `smartagent.brain.action_result.ActionResult`, with
   `success` reflecting whether it could genuinely help — `BrainRouter`
   relies on this to fall through to the next candidate module.
5. **Publish events where it helps.** If other modules would reasonably
   want to react to what yours just did, publish onto the shared
   `EventBus` (see how `MemoryManager` publishes `MemorySaved`) instead of
   calling into other modules directly.
6. **Write tests.** Cover the module in isolation, and if it's registered
   with the Brain, add/extend a `BrainRouter` test exercising the full
   chain through your new module.
7. **Document it.** Add a row to `ROADMAP.md`'s Architecture table, and
   update `README.md` if it changes user-facing behavior. Add an entry to
   `CHANGELOG.md` under `[Unreleased]`.
8. **Keep it a real placeholder if the behavior isn't ready yet.** Per
   project rules, don't fake functionality — raise `NotImplementedError`
   or return `success=False` with an honest message, exactly like the
   existing voice/vision/automation modules do.
