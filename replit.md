# SmartAgent MARK

> **Superseded.** The canonical specification is
> [`docs/canonical/`](docs/canonical/README.md). **If you are Replit
> Agent, read [`docs/canonical/REPLIT_BOOTSTRAP.md`](docs/canonical/REPLIT_BOOTSTRAP.md)
> first**, then [`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md) for
> what's currently real and verified. The package map and milestone table
> below describe the `smartagent/brain/`-rooted CLI/REPL system, confirmed
> by audit to be disconnected from the live FastAPI+React product.
> Historical reference for that code path only.

MARK is an autonomous Python AI agent with a modular architecture covering memory, multi-agent orchestration, self-debugging, project awareness, and a full software-engineer pipeline.

## Run & Operate

```bash
# Run the REPL console
python -m smartagent

# Run the full test suite
pytest

# Run tests for a specific milestone
pytest tests/test_project_memory.py    # M22
pytest tests/test_long_running.py      # M23
pytest tests/test_dev_loop.py          # M24
pytest tests/test_engineer.py          # M25
```

## Stack

- Python 3.11, no external framework dependencies for core agent
- Ollama (optional) for local LLM inference
- pytest for all tests
- Modular packages under `smartagent/`

## Where Things Live

| Area | Package | Key files |
|---|---|---|
| Brain / wiring | `smartagent/brain/` | `agent.py` — composition root |
| Memory | `smartagent/memory/` | `memory_manager.py` |
| Tools | `smartagent/tools/` | `tool_engine.py` |
| Models | `smartagent/models/` | `model_manager.py`, `model_registry.py` |
| MARK Mind OS | `smartagent/mind/` | `mind_os.py`, `identity_engine.py` |
| Executive | `smartagent/executive/` | `executive_controller.py`, `orchestrator.py` |
| Multi-Agent | `smartagent/multi_agent/` | `ceo_agent.py`, `team_planner.py`, `team_runner.py` |
| Reflection | `smartagent/reflection/` | `reflection_engine.py` |
| Intelligence | `smartagent/intelligence/` | `project_scanner.py` |
| File Editing | `smartagent/editing/` | `file_editor.py` |
| Debugging | `smartagent/debug/` | `debug_loop.py`, `traceback_parser.py` |
| **Git Engine** | `smartagent/git/` | `git_client.py`, `pr_builder.py` |
| **Project Memory** | `smartagent/project_memory/` | `project_memory.py`, `project_profile.py` |
| **Long Running** | `smartagent/long_running/` | `long_running_engine.py`, `completion_report.py` |
| **Dev Loop** | `smartagent/dev_loop/` | `dev_loop.py`, `loop_result.py` |
| **Engineer** | `smartagent/engineer/` | `software_engineer.py`, `requirement_analyzer.py`, `clarification_engine.py` |
| Console UI | `smartagent/ui/` | `console.py`, `commands/` |

## Milestones

| # | Name | Status | Console command |
|---|---|---|---|
| 1–8 | Core agent + console | ✓ done | `help` |
| 9 | Ollama integration | ✓ done | `model list` |
| 10 | Streaming | ✓ done | — |
| 11 | Executive framework | ✓ done | `plan <goal>` |
| 15 | Workspace manager | ✓ done | `workspace list` |
| 17 | Multi-agent | ✓ done | `ceo <goal>` |
| 18 | Intelligence | ✓ done | `scan <path>` |
| 19 | File editing | ✓ done | — |
| 20 | Self-debugging | ✓ done | `debug <cmd>` |
| 21 | **Git Engine** | ✓ done | `git status / commit / push / pr …` |
| 22 | **Project Memory** | ✓ done | `project show / set / scan / list` |
| 23 | **Long Running Execution** | ✓ done | `long-run <goal>` |
| 24 | **Autonomous Dev Loop** | ✓ done | `dev-loop <goal>` |
| 25 | **Full Software Engineer** | ✓ done | `engineer <goal>` |

## Architecture Decisions

- **Composition root in `agent.py`**: every subsystem is wired in one place; subsystems never import each other directly — they receive dependencies via constructor.
- **`with_agent(agent)` factory pattern**: every engine class (CEOAgent, DevLoop, SoftwareEngineer, …) has a classmethod that extracts what it needs from a live `SmartAgent`. This keeps tests clean (inject mocks) and the agent.py wiring simple.
- **Best-effort subsystems**: each milestone wraps its imports in try/except so a missing optional dependency (Ollama, git binary) degrades gracefully instead of crashing on import.
- **JSON-on-disk for persistent state**: project profiles, memory entries, knowledge, and skills are all stored as JSON files — no database dependency required.
- **Console commands always return strings**: `handle_*` functions in `ui/commands/` return display strings (never print directly in library code) so they can be tested without capturing stdout.

## Key Agent Attributes

After `SmartAgent.__init__`, the following are always available:

```python
agent.memory            # MemoryManager
agent.executive         # ExecutiveController
agent.ceo               # CEOAgent
agent.reflection_engine # ReflectionEngine
agent.project_memory    # ProjectMemory      (M22)
agent.long_running_engine # LongRunningEngine (M23)
agent.dev_loop          # DevLoop            (M24)
agent.software_engineer # SoftwareEngineer   (M25)
```

## Console Quick Reference

```
project show                      # show active project profile
project set language Python        # remember a field
project scan /path/to/project      # auto-detect tech stack
long-run Build a SaaS backend      # CEO pipeline with completion report
dev-loop --commit Build login API  # autonomous code→test→debug loop
engineer Build me a Trello clone   # full software engineer pipeline
engineer analyze Build a chat app  # requirement analysis only
git status / git commit "msg"      # git operations
```

## Test Count by Milestone Area

```
pytest --co -q | grep "test session" → 1896 total tests
```

## Gotchas

- `DevLoop.with_agent()` imports `DebugLoop` lazily; there is **no** `debug_worker.py` — only `debug_loop.py` and `traceback_parser.py` in `smartagent/debug/`.
- `ProjectMemory.scan()` must NOT `break` after the first filename-pattern match: a single file (e.g. `conftest.py`) can satisfy multiple rules (Python language + pytest test runner).
- `GitWorker` keyword routing: the `commit` `elif` branch must exclude rollback/reset tasks because `"rollback 2 commits"` contains the substring `"commit"`.
- `PRBuilder._infer_title` branch-name priority: a descriptive slug (`feature/login-system` → "Login System") wins over the single-commit message; a trivial slug (`feature/x`) falls through to the commit message.

## User Preferences

_Populate as you build — explicit user instructions worth remembering across sessions._
