# MARK Architecture

> **Superseded.** The canonical specification is
> [`docs/canonical/`](docs/canonical/README.md) — read
> `docs/canonical/CLAUDE_ENGINEER_BOOTSTRAP.md` first, then
> `docs/canonical/ARCHITECTURE.md` for the current technical architecture.
> Everything below describes the `smartagent/brain/`-rooted CLI/REPL system
> (`SmartAgent`, `smartagent/executive/`, `smartagent/multi_agent/`) —
> confirmed by audit to be disconnected from the live FastAPI+React product
> and constructed but unused on every request. Kept for historical reference,
> not as a build target.

## Overview

MARK is structured as a layered monolith — all subsystems live in the same Python package and communicate through direct method calls rather than message passing. This keeps the codebase simple while still maintaining clear boundaries.

**Core principle:** Every subsystem is optional. If Ollama is not running, MARK degrades gracefully. If git is not installed, the git engine is skipped. No uncaught exception terminates the process.

---

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     User Interface Layer                         │
│  Console → Repl → CommandRouter → command modules               │
│  ExecutionDashboard (live progress display)                      │
├─────────────────────────────────────────────────────────────────┤
│                   Engineer Pipeline Layer                        │
│                                                                  │
│  SoftwareEngineer                                               │
│    ├── RequirementAnalyzer   (keyword + complexity detection)   │
│    ├── ClarificationEngine   (Q&A with defaults)                │
│    ├── DevLoop               (plan→code→test→quality→debug)     │
│    │     ├── ExecutiveController  (planning + workers)          │
│    │     ├── QualityRunner        (ruff, black, mypy)           │
│    │     ├── DebugLoop            (run→parse→fix→retry)         │
│    │     └── ReflectionEngine     (post-cycle learning)         │
│    └── GitClient             (auto-commit)                      │
│                                                                  │
│  LongRunningEngine → CEOAgent → TeamPlanner → TeamRunner        │
│  CompletionReport  (✓/✗ per phase, remaining list)              │
├─────────────────────────────────────────────────────────────────┤
│                  Multi-Agent Orchestration Layer                 │
│  CEOAgent → TeamPlanner → WorkerRegistry → Workers              │
│  Workers: Coding, Testing, Debug, Research, Design, Git, ...    │
│  FileEditMixin  (extracts code blocks → writes real files)      │
├─────────────────────────────────────────────────────────────────┤
│                    Workspace & File Layer                        │
│  FileEditor v2   (create, edit, patch, delete, move, rename)    │
│                  (preview, diff, snapshot, restore, audit log)  │
│  WorkspaceScanner (file graph, import graph, project summary)   │
│  WorkspaceManager (project isolation, scoped services)          │
│  ProjectMemory    (per-project tech-stack profiles)             │
├─────────────────────────────────────────────────────────────────┤
│                     Intelligence Layer                          │
│  Git Engine  (status, branch, commit, push, merge, PR)          │
│  DebugLoop   (subprocess → TracebackParser → fix → retry)      │
│  QualityRunner (pytest, ruff, black --check, mypy)              │
├─────────────────────────────────────────────────────────────────┤
│                       Brain Layer                               │
│  SmartAgent (composition root — all subsystems wired here)      │
│  ExecutiveController, BrainRouter, ModuleRegistry               │
├─────────────────────────────────────────────────────────────────┤
│                       Mind OS Layer                             │
│  MindOS, IdentityEngine, HomeostasisEngine, AttentionManager    │
│  ReflectionEngine, LearningStore                                │
├─────────────────────────────────────────────────────────────────┤
│                     Foundation Layer                            │
│  MemoryManager, KnowledgeManager, SkillEngine, ToolEngine       │
│  ModelManager → OllamaProvider (streaming, caching)             │
│  EventBus, Logger, Settings, PermissionManager                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Subsystems

### SmartAgent (`smartagent/brain/agent.py`)
The composition root. Instantiates every subsystem in `__init__` and exposes them as attributes. No subsystem imports another directly — they receive dependencies via constructor injection.

### FileEditor v2 (`smartagent/workspace/file_editor.py`)
Scoped file operations within a base directory. All paths are security-validated to prevent directory traversal. v2.0 adds:
- `preview(path, content)` — unified diff without writing
- `snapshot()` / `restore(snap)` — full rollback support
- `move()` / `rename()` — move files within base dir
- `export_audit_log()` — JSON export of all operations

### DebugLoop (`smartagent/debug/debug_loop.py`)
Production debugging loop:
1. Run command via `subprocess.run` (real process, real stdout/stderr)
2. Parse tracebacks with `TracebackParser` (regex-based)
3. Identify root-cause file (skip `site-packages`, stdlib)
4. Call `debug_worker.fix(traceback, filepath, content)` → fixed content
5. Write fixed content via `FileEditor` or direct write
6. Repeat until pass or max attempts exhausted

### QualityRunner (`smartagent/quality/quality_runner.py`)
Runs code quality tools in sequence. Each tool is optional — if not installed, marked `skipped` instead of `failed`. Supports: pytest, ruff, black (check mode), mypy.

### ExecutionDashboard (`smartagent/ui/dashboard.py`)
Text-based live dashboard. No ANSI cursor tricks — renders a full snapshot string on each `render()` call. Works in piped output and CI. Tracks: goal, current worker, completed/running/queued tasks, files modified, test counts, retries, model, tool calls, memory updates.

### SoftwareEngineer (`smartagent/engineer/software_engineer.py`)
Full pipeline:
1. Workspace scan (WorkspaceScanner)
2. Requirement analysis (RequirementAnalyzer — keyword + complexity)
3. Clarification (ClarificationEngine — Q&A or defaults)
4. Goal enrichment (workspace context + analysis + clarifications)
5. DevLoop execution
6. Git auto-commit
7. Summary generation

### DevLoop (`smartagent/dev_loop/dev_loop.py`)
Autonomous cycle (up to N iterations):
1. Planning via ExecutiveController
2. Testing via subprocess
3. Quality check via QualityRunner (ruff, black, mypy)
4. Debugging via DebugLoop
5. Reflection via ReflectionEngine
Exits on first all-green test run.

---

## Key Design Decisions

### `with_agent(agent)` factory pattern
Every engine class has a `classmethod` factory that extracts what it needs from a live `SmartAgent`. This keeps tests clean (inject mocks) and `agent.py` wiring minimal.

### Best-effort subsystems
Every `with_agent()` wraps imports in `try/except`. A missing dependency (Ollama, git binary, ruff) degrades gracefully instead of crashing on import.

### Console commands always return strings
Command handlers in `ui/commands/` return display strings and never print directly. This makes testing trivial (compare strings) and keeps I/O in the REPL only.

### FileEditMixin for code extraction
Workers return text responses with fenced code blocks (```` ```python filename: auth.py ````). `FileEditMixin` (used by `CodingWorker`) parses these and writes the files automatically. Workers therefore produce real files as a side-effect of generating their text response.

### Global exception handler in REPL
`repl.py` wraps `router.dispatch()` in a broad `except Exception` so that any uncaught error is logged, shown to the user as a friendly message, and the REPL continues. MARK never crashes due to a command error.

---

## Package Map

```
smartagent/
  brain/             SmartAgent composition root, routing
  mind/              Mind OS, identity, homeostasis, attention
  memory/            MemoryManager, Vault
  knowledge/         KnowledgeManager, graph, search, ontology
  tools/             ToolEngine, ToolRegistry, builtin tools
  skills/            SkillEngine, SkillRegistry
  models/            ModelManager, ModelRegistry, OllamaProvider
  executive/         ExecutiveController, Orchestrator, Planner
  executive/workers/ CodingWorker, TestingWorker, GitWorker, ...
  multi_agent/       CEOAgent, TeamPlanner, TeamRunner
  debug/             DebugLoop, TracebackParser
  quality/           QualityRunner, QualityReport (v2.0)
  workspace/         FileEditor, WorkspaceScanner, WorkspaceManager
  git/               GitClient, PRBuilder, GitStatus
  project_memory/    ProjectMemory, ProjectProfile
  long_running/      LongRunningEngine, CompletionReport
  dev_loop/          DevLoop, LoopResult
  engineer/          SoftwareEngineer, RequirementAnalyzer, ClarificationEngine
  reflection/        ReflectionEngine
  ui/                Console, Repl, CommandRouter, renderer, dashboard
  ui/commands/       All command modules
  config/            Settings
  logs/              Logger
  automation/        TaskScheduler
  vision/            ImageAnalyzer
  voice/             SpeechToText, TextToSpeech (legacy stub — the live voice
                     pipeline is smartagent/server/voice_manager.py)
  tts/               TTSProvider factory — Kokoro (default) / Piper / OpenAI / browser
  preview/           BrowserAgent — Playwright self-inspection of live previews
```

---

## Data Flow: `engineer Build a FastAPI Todo API`

```
User input
    │
    ▼
Console.run()
    │
    ▼
Repl.run()  ──[global exception handler]──▶  friendly error + continue
    │
    ▼
CommandRouter.dispatch()
    │
    ▼
engineer_cmd.handle_engineer()
    │
    ▼
SoftwareEngineer.build()
    ├── WorkspaceScanner.scan(".")       → workspace summary
    ├── RequirementAnalyzer.analyze()   → RequirementReport
    ├── ClarificationEngine.from_report() → ClarificationSet (defaults applied)
    ├── _enrich_goal()                  → enriched prompt string
    │
    └── DevLoop.run()
          ├── Cycle 1:
          │     ├── ExecutiveController.receive_goal()   → plan
          │     ├── subprocess.run("pytest")             → test output
          │     │     pass? ──▶ QualityRunner.run_all() → ruff/black/mypy
          │     │     fail? ──▶ DebugLoop.run()
          │     │                 ├── subprocess.run("pytest")
          │     │                 ├── TracebackParser.parse_all()
          │     │                 ├── debug_worker.fix()
          │     │                 └── FileEditor.edit()
          │     └── ReflectionEngine.reflect()
          │
          └── LoopResult (success=True, iterations=..., elapsed=...)
    │
    ├── GitClient.commit()    (if --commit)
    └── SoftwareEngineerReport → console display
```
