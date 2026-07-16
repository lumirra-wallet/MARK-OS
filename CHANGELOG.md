# Changelog

All notable changes to MARK are documented here.

---

## v2.0.0 — Production Grade

### Added

**Phase 3 — FileEditor v2** (`smartagent/workspace/file_editor.py`)
- `preview(path, new_content)` — returns unified diff without writing
- `diff(path, new_content)` — alias for preview
- `snapshot()` — captures `{path: content}` dict of all current files
- `restore(snapshot)` — reverts base directory to a captured state
- `move(src, dst)` — move/rename files within the base directory
- `rename(src, dst)` — alias for move
- `export_audit_log()` — returns full edit history as JSON
- `EditResult.to_dict()` — JSON-serialisable representation

**Phase 5 — QualityRunner** (`smartagent/quality/`)
- New `QualityRunner` class: runs pytest, ruff, black (check mode), mypy
- Each tool gracefully skips if not installed (marked `skipped`, not `failed`)
- `QualityReport` with `as_display_lines()`, `failing_tools()`, `get(tool)`
- `QualityResult` with `icon`, `one_line()`, `elapsed`
- Integrated into `DevLoop` — quality phase runs after tests pass

**Phase 6 — ExecutionDashboard** (`smartagent/ui/dashboard.py`)
- Text-based live dashboard (no ANSI cursor tricks — works in CI / piped output)
- Tracks: goal, current worker, completed/running/queued tasks
- Tracks: files modified, tests passed/failed, retries, model, tool calls
- Injected into `SoftwareEngineer.with_agent()` → `DevLoop`
- All dashboard calls are guarded (`try/except`) — never crashes the pipeline

**Phase 9 — Validation Suite** (`smartagent/ui/commands/validate_cmd.py`)
- `validate` command with 5 standard engineering scenarios
- `validate list` — show available scenarios
- `validate run <name>` — run a single scenario
- Scenarios: calculator-cli, rest-api, flask-blog, markdown-parser, jwt-auth

**Phase 8 — Reliability** (`smartagent/ui/repl.py`)
- Global exception handler wraps every `router.dispatch()` call
- Uncaught exceptions are logged, displayed as a friendly message, REPL continues
- Ctrl+C during a long command cancels it without terminating MARK

### Changed

**DevLoop** (`smartagent/dev_loop/dev_loop.py`)
- New `quality_runner` and `dashboard` constructor arguments
- New `_run_quality_phase()` — runs ruff/black/mypy after tests pass
- `with_agent()` factory now builds `QualityRunner` automatically
- Dashboard helper methods (`_dash_*`) all guarded with `try/except`
- `run()` accepts `run_quality` flag (default True)

**SoftwareEngineer** (`smartagent/engineer/software_engineer.py`)
- Step 0: workspace scan (WorkspaceScanner) before requirement analysis
- `_enrich_goal()` now includes workspace summary in the enriched prompt
- `SoftwareEngineerReport` gains `workspace_summary` and `quality_summary` fields
- `with_agent()` builds and injects `ExecutionDashboard` into DevLoop
- `_count_cycles()` helper replaces fragile `_cycle_count` lambda call

**Console** (`smartagent/ui/console.py`)
- Registered `validate_cmd` (Phase 9 Validation Suite)

### Tests Added
- `tests/test_file_editor_v2.py` — 45 tests for FileEditor v2
- `tests/test_quality_runner.py` — 38 tests for QualityRunner
- `tests/test_dashboard.py` — 42 tests for ExecutionDashboard
- `tests/test_validate_cmd.py` — 18 tests for validate command

---

## v1.0.0 — Execution OS (Milestones 18–25)

### Added
- M18: Workspace Intelligence (ProjectScanner, file/import/dependency graphs)
- M19: File Editing Engine (FileEditor, FileEditMixin — workers write real files)
- M20: Self Debugging (DebugLoop, TracebackParser — run→parse→fix→retry)
- M21: Git Engine (GitClient, PRBuilder, GitWorker, git console commands)
- M22: Project Memory (ProjectProfile, ProjectMemory, `project` commands)
- M23: Long Running Execution (LongRunningEngine, CompletionReport, `long-run`)
- M24: Autonomous Development Loop (DevLoop, LoopResult, `dev-loop`)
- M25: Full Software Engineer (SoftwareEngineer, RequirementAnalyzer, ClarificationEngine, `engineer`)

### Bug Fixes (M21)
- `PRBuilder._infer_title` priority: descriptive branch slug preferred; short slugs fall through to commit message
- `_make_git` test fixture: `changed=[]` now correctly produces empty file list
- `GitWorker` keyword routing: `"rollback 2 commits"` no longer matches the commit branch

---

## v0.9.0 — Intelligence (Milestones 11–17)

### Added
- M11: Executive Framework (Planner, Workers, Orchestrator, Scheduler)
- M14: Learning & Reflection (ReflectionEngine, LearningStore, PromptRegistry)
- M15: Workspace Manager (project isolation, scoped services, 108 tests)
- M17: Multi-Agent Collaboration (CEOAgent, TeamPlanner, TeamRunner, 97 tests)

---

## v0.5.0 — Foundation (Milestones 1–10)

### Added
- M1–M8:  Brain, Memory, Knowledge, Tools, Models, Mind OS, Console
- M9:     Ollama Integration (OllamaProvider, health, streaming)
- M10:    Streaming Upgrade (generate_stream, chat_stream, spinner, stats)
