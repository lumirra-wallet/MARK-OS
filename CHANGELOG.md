# Changelog

All notable changes to MARK are documented here.

---

## Unreleased — Engineering Workspace Redesign

### Added

**Combined server** — `smartagent/server/app.py` now mounts the built dashboard
(`artifacts/mark-dashboard/dist/public`) as static files with a SPA-fallback
route, so the API and dashboard run from a single port/process. `pnpm dev`
now builds once + watches; the old split two-process mode is `pnpm dev:split`.

**Executive synthesis layer** — `DevPipeline` (`smartagent/engineer/
dev_pipeline.py`) no longer streams raw internal prose to chat. Every phase
(plan, milestone, test, review, commit) now publishes a structured
`ActivityFeedEntry` (Timeline detail only); one LLM call per milestone (and
one at the end) composes MARK's actual executive-voice chat message. The
existing `Narration` WS event (previously defined but never published) now
has a real producer, wired to the same text via `DevPipeline._speak()`.

**Per-task permission scoping** — `smartagent/engineer/agent_tools.py`'s
`execute_tool()` accepts an optional `allowed_paths` list; write/rename/
delete calls outside that scope are rejected. `DevPipeline` computes it per
milestone from the milestone's own declared file targets (`extract_file_targets`).

**Project Inspector** (`ProjectInspector.tsx`) — new composite panel:
Running Applications, Current Branch, Recent Commits, Files Changed, Test
Results (new persistent `lastTestRun` store state), Worker Status, real
Performance telemetry (replacing `PerformanceView`'s previously mocked/random
data with an actual tokens/sec series), and Active Model/Provider.

**Browser automation** (`smartagent/preview/browser_agent.py`) — Playwright-
based self-inspection of MARK's own live previews via the system-installed
Chromium (no bundled-browser download). Navigate, click, fill, screenshot,
console-error capture, and a dependency-free accessibility floor check.
Wired into `DevPipeline` — a screenshot + findings get captured after each
milestone if a preview is active, persisted to the Timeline
(`MilestoneScreenshot` event), and folded into that milestone's executive
summary. New endpoint: `POST /previews/{id}/inspect`.

**Kokoro TTS provider** (`smartagent/tts/`) — new provider abstraction
(`TTSProvider` protocol, mirroring `smartagent/llm/`'s factory pattern) with
Kokoro (default, CPU/ONNX, `kokoro-onnx`), Piper, OpenAI, and browser
providers, switchable via `POST /tts/provider`. `VoicePanel.tsx` is now a
slim Narration panel (Voice Provider, Voice Selection, Speaking Status,
Volume, Mute) — Push-to-Talk/Wake-Word/Continuous-mode UI and mic recording
controls were removed from the frontend (the underlying `/voice/*` STT
endpoints are untouched, for backward compatibility).

**Engineering Workspace sidebar** — `Dashboard.tsx`'s sidebar regrouped
around Active Run / Active Workers / Timeline / Checkpoints / Git / Live
Preview / Project Inspector / Engineering Memory / Models, with the rest
preserved under an Advanced group. `WorkersView.tsx` cards now show
progress, runtime, and files touched per worker (collapsible).

**Timeline 8-stage lifecycle** — `ReasoningStage` (and the stepper UI) now
covers Analyze → Plan → Write → Run → Test → Review → Commit → Deploy;
`TimelineView.tsx` renders screenshot thumbnails (lightbox + side-by-side
comparison) for entries that have one.

### Fixed

- `agent_tools._safe_path`'s traversal check used `str.startswith()`, which
  wrongly allows a sibling directory sharing the workspace path as a string
  prefix; now uses `resolve()` + `is_relative_to()`.
- Preview framework label mismatch: backend `classify()` emits `"nextjs"`,
  frontend `FRAMEWORK_COLORS` only had `"next"` — both now map correctly.
  Added Electron / Flutter Web / React Native Web detection.
- `pnpm --filter @workspace/mark-dashboard build` failed outright without
  `PORT`/`BASE_PATH` env vars set — now defaults sensibly.

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
