---
name: Milestone 8 — MARK Console OS v1
description: Architecture decisions, API quirks, and test patterns for the interactive console layer.
---

## What was built

A full interactive REPL console under `smartagent/ui/`:
- `console.py` — top-level coordinator, wires all command modules
- `repl.py` — I/O loop (KeyboardInterrupt → resume, EOFError → break, ExitConsole → "Goodbye.")
- `renderer.py` — stateless formatters, no `print()` — testable in isolation
- `command_router.py` — `CommandRouter.register(name, handler, desc, group, order)` + `dispatch()` + `help_entries()`
- `commands/*.py` — 8 modules, each exposes `register(router)`

Handler contract: `Callable[[SmartAgent, list[str]], str]`. Exit via `raise ExitConsole()`.

## Key API quirks (avoid re-discovering)

- `KnowledgeManager.list_pending_inbox()` — not `list_pending()` or `inbox.pending()`
- `KnowledgeManager.reject_concept(item_id, notes="")` — param is `notes`, not `reason`
- `KnowledgeStatsReport` fields: `high_confidence_concepts`, `low_confidence_concepts`,
  `verified_concepts`, `unverified_concepts`, `contradicted_concepts` (NOT `_count` suffixes)
- `EventBus` already has `history()` — no extra recorder needed; agent init events inflate the count
- `agent.tool_engine` and `agent.skill_engine` — ToolEngine and SkillEngine respectively
- `agent.model_manager` — ModelManager

## Logging change

`configure_logging()` now accepts `log_file` and `log_to_console` params.
`get_logger()` no longer calls `configure_logging()` automatically — callers must configure
explicitly. `main.py` passes `log_file="logs/mark.log", log_to_console=False`.

**Why:** Module-level `logger = get_logger(__name__)` at import time was winning the
`_CONFIGURED` guard race before `main.py` could set up the file handler.

## Test patterns

- Driving the REPL: patch `builtins.input` with an iterator ending in `EOFError()`; capture
  `sys.stdout` with `io.StringIO()`. The REPL returns cleanly on EOFError.
- Agent init publishes its own events (count varies), so never assert "N of 30 total" —
  assert "showing 20 of" instead.
- ExitConsole tests: call handler directly or `console.router.dispatch(agent, "exit")` —
  assert `pytest.raises(ExitConsole)`.
- Resilience tests: mock `agent.mind.self_model` / `health_check` to raise; assert response
  is a non-empty string.
