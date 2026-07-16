---
name: Milestones 22-25 Project Memory / Long Running / Dev Loop / Engineer
description: Architecture, key decisions, and quirks for M22-M25 implementation.
---

## Milestone 22 — Project Memory

**Packages:** `smartagent/project_memory/`
- `project_profile.py` — `ProjectProfile` dataclass; `as_ai_context()` for prompt injection
- `project_memory.py` — `ProjectMemory`: load/save JSON per project, set/get (known fields + prefs + tools + notes), `scan()` auto-detect tech stack, `list_projects()`, `delete()`, `inject_into_context()`
- `smartagent/ui/commands/project_cmd.py` — console command `project <sub>`

**Why:** MARK needs per-project context (language, framework, test runner, DB) so every future task in that project can be answered accurately without re-scanning from scratch.

**How to apply:** `agent.project_memory` is a live `ProjectMemory` instance on `SmartAgent`. Call `pm.load(name, path)` to get a profile; `pm.set(profile, key, value)` to remember things; `pm.ai_context(profile)` to get a prompt snippet.

**Quirk — scan loop break removed:** The filename-pattern rules in `scan()` must NOT break after the first match per file. `conftest.py` matches both the `.py` (Python) rule and the `conftest.py` (pytest) rule. The original `break` caused pytest detection to be skipped for that file.

---

## Milestone 23 — Long Running Execution

**Packages:** `smartagent/long_running/`
- `completion_report.py` — `PhaseResult` + `CompletionReport` with `as_display_lines()` / `as_short_summary()`
- `long_running_engine.py` — `LongRunningEngine`: wraps `CEOAgent.execute()`, maps `team_results` → `PhaseResult` objects, fires `on_phase_done` callback, persists summary to memory, injects project context
- `smartagent/ui/commands/long_run_cmd.py` — console command `long-run <goal>`

**Why:** Multi-hour CEO runs need structured output (completed / failed / remaining) rather than a wall of text. The `CompletionReport` is the canonical format for executive-level status.

**How to apply:** `agent.long_running_engine = LongRunningEngine(ceo_agent=agent.ceo, ...)`. Call `engine.run(goal)` for a blocking run with a structured report. Use `on_phase_done` callback for live progress streaming.

---

## Milestone 24 — Autonomous Development Loop

**Packages:** `smartagent/dev_loop/`
- `loop_result.py` — `LoopIteration` + `LoopResult` with full trace and display
- `dev_loop.py` — `DevLoop`: plan → test → debug → reflect → retry (up to `max_iterations`); uses `DebugLoop` for self-healing; fires `ReflectionEngine` after each cycle; auto-commit via `GitClient`
- `smartagent/ui/commands/dev_loop_cmd.py` — console command `dev-loop <goal>`

**Why:** MARK should fix its own test failures without human intervention. The loop exits on first all-green test run, or stops at `max_iterations` with a structured result.

**How to apply:** `agent.dev_loop = DevLoop.with_agent(agent)`. `DevLoop.with_agent` imports `DebugLoop` lazily inside a try/except — safe when the debug module is absent or incomplete.

**Quirk — no DebugWorker in debug module:** The codebase has `smartagent/debug/debug_loop.py` and `traceback_parser.py` but no `debug_worker.py`. `DevLoop.with_agent()` must only import `DebugLoop` (with `debug_worker=None`) — importing a non-existent `DebugWorker` crashes the factory.

---

## Milestone 25 — Full Software Engineer

**Packages:** `smartagent/engineer/`
- `requirement_analyzer.py` — `RequirementAnalyzer`: keyword-based domain detection, stack hint detection, complexity estimation (small/medium/large/xlarge), team selection, open-question generation
- `clarification_engine.py` — `ClarificationEngine`: turns open questions → `ClarificationSet` with `answer_all_with_defaults()` for non-interactive mode
- `software_engineer.py` — `SoftwareEngineer`: analyze → clarify → enrich goal → run `DevLoop` → auto-commit → summarize → persist
- `smartagent/ui/commands/engineer_cmd.py` — console command `engineer <goal>`

**Why:** MARK should act as a professional engineer: understand what is being asked, ask only what matters, then execute autonomously.

**How to apply:** `agent.software_engineer = SoftwareEngineer.with_agent(agent)`. Non-interactive mode (default) applies default answers to clarification questions (JWT, PostgreSQL, React, Stripe, Docker). Pass `interactive=True` to prompt stdin.

---

## M21 Bugs Fixed (pre-existing)

**`PRBuilder._infer_title` priority:** Branch name preferred when the slug (after prefix stripping) is descriptive (multi-word or > 3 chars). Short slugs like `feature/x` fall through to single-commit message. **Why:** "feature/login-system" → "Login System" is more useful than commit "X"; but "feature/x" is noise, so commit "Add login module" wins.

**`PRBuilder` test fixture `_make_git`:** Changed `changed or [defaults]` to `[defaults] if changed is None else changed`. The old code treated `changed=[]` as falsy and returned the default file list.

**`GitWorker` commit/rollback keyword collision:** `"rollback 2 commits"` contains `"commit"`, so the commit elif fired before the rollback elif. Fixed by guarding the commit branch: `"commit" in combined and not any(k in combined for k in ("rollback", "reset", "undo"))`.
