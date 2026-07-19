# MARK — AI Operating System

> The canonical specification for MARK AIOS is
> [`docs/canonical/`](docs/canonical/README.md) — start with
> `docs/canonical/CLAUDE_ENGINEER_BOOTSTRAP.md`. The `Quick Start` and
> `Commands Reference` sections below describe the `python -m smartagent`
> CLI/REPL path, confirmed by audit to be disconnected from the live
> FastAPI+React dashboard — useful if you're running that specific code path,
> not a description of MARK AIOS as a whole.

MARK is not a coding agent — it's the operating system a team of specialist
engineering workers (Engineer, QA, Debugger, Reviewer, Git, and others) runs
inside of. You talk to MARK; MARK plans the work, delegates it, supervises
execution, reviews the result, and reports back — the same way an engineering
manager runs a team, not the way a single coding assistant works alone. See
[`docs/mark-operating-system.md`](docs/mark-operating-system.md) for
implementation status against that vision.

```
mark> engineer Build a FastAPI Todo API with JWT authentication

  ► Scanning workspace...
  ► Analyzing requirements... [backend, auth]  complexity=medium
  ► Planning with multi-agent teams...
  ► CodingWorker: writing app/main.py, app/auth.py, tests/test_api.py
  ► TestRunner: pytest — 12 passed
  ► QualityRunner: ruff ✓  black ✓  mypy ✓
  ✓ All tests passed after 1 cycle.
  ✓ Committed: a3f9c12
```

---

## Quick Start

```bash
# Start the interactive console
python -m smartagent

# Common commands
mark> engineer Build a REST API with CRUD endpoints
mark> engineer --interactive Build a SaaS billing system
mark> engineer --commit --test "pytest tests/" Build a login system
mark> ceo Build a full-stack application with React and FastAPI
mark> long-run Build a SaaS product
mark> dev-loop --commit Fix the authentication module
mark> git status
mark> project scan /path/to/project
mark> validate           # Run Phase 9 validation suite
mark> help
```

---

## Architecture

MARK is built as a layered system:

```
┌─────────────────────────────────────────────────────────┐
│                    Console / REPL (UI)                   │
├─────────────────────────────────────────────────────────┤
│  Software Engineer  │  DevLoop  │  Long Running Engine   │
├─────────────────────────────────────────────────────────┤
│  CEO Agent  │  Team Planner  │  Team Runner              │
├──────────────┬──────────────────────────────────────────┤
│  Executive   │  Workers: Coding, Testing, Debug, Git...  │
├──────────────┼──────────────────────────────────────────┤
│  Debug Loop  │  Quality Runner  │  File Editor v2        │
├──────────────┼──────────────────────────────────────────┤
│  Brain       │  Mind OS  │  Memory  │  Knowledge         │
├──────────────┼──────────────────────────────────────────┤
│  Model Manager (Ollama)  │  Tool Engine  │  Skill Engine │
└─────────────────────────────────────────────────────────┘
```

Full architecture details: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Commands Reference

| Command | Description |
|---|---|
| `engineer <goal>` | Full pipeline: analyze → clarify → code → test → debug → commit |
| `engineer --interactive <goal>` | Ask clarification questions before starting |
| `engineer --commit <goal>` | Auto-commit to git on success |
| `engineer --test <cmd> <goal>` | Custom test command |
| `engineer analyze <goal>` | Requirement analysis only |
| `engineer clarify <goal>` | Show clarification questions without executing |
| `ceo <goal>` | Multi-agent CEO pipeline |
| `long-run <goal>` | Long-running execution with CompletionReport |
| `dev-loop <goal>` | Autonomous code→test→debug loop |
| `git status / commit / push / pr` | Git operations |
| `project show / set / scan / list` | Project memory |
| `validate` | Phase 9 validation suite (5 scenarios) |
| `workspace scan <path>` | Workspace intelligence scan |
| `plan <goal>` | Executive planning |
| `model list / use / health` | Model management |
| `debug <cmd>` | Self-debugging loop |
| `memory list / search` | Memory management |
| `help` | Full command reference |

---

## Installation

```bash
# Clone the repository
git clone <repo>
cd smartagent

# Install dependencies
pip install -r requirements.txt

# Optional: install Ollama for local AI
# https://ollama.ai
ollama pull llama3

# Run MARK
python -m smartagent
```

---

## Running Tests

```bash
# Full test suite (1900+ tests)
pytest

# Specific milestone areas
pytest tests/test_engineer.py         # M25 — Full Software Engineer
pytest tests/test_dev_loop.py         # M24 — Dev Loop
pytest tests/test_long_running.py     # M23 — Long Running
pytest tests/test_project_memory.py   # M22 — Project Memory
pytest tests/test_git.py              # M21 — Git Engine
pytest tests/test_quality_runner.py   # v2.0 — Quality Runner
pytest tests/test_dashboard.py        # v2.0 — Dashboard
pytest tests/test_file_editor_v2.py   # v2.0 — FileEditor v2
```

---

## Milestones

| Phase | Milestones | Description |
|---|---|---|
| Foundation | 1–10 | Brain, Mind, Memory, Knowledge, Models, Ollama, Streaming |
| Intelligence | 11–17 | Executive, Workers, CEO, Multi-Agent, Workspace |
| Execution OS | 18–21 | Scanner, FileEditor, DebugLoop, Git Engine |
| Production | 22–25 | Project Memory, Long Running, Dev Loop, Software Engineer |
| v2.0 | — | Quality Runner, Dashboard, Reliability, Validation |

---

## License

MIT
