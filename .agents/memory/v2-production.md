---
name: v2.0 Production Grade upgrade
description: Architecture decisions and quirks from the 9-phase v2.0 production upgrade.
---

## New modules

- `smartagent/quality/quality_runner.py` — `QualityRunner` + `QualityReport` + `QualityResult`
- `smartagent/ui/dashboard.py` — `ExecutionDashboard` (text-based, CI-safe)
- `smartagent/ui/commands/validate_cmd.py` — Phase 9 validation suite (5 scenarios)

## FileEditor v2 additions (no breaking changes)
Added to `smartagent/workspace/file_editor.py`:
- `preview(path, new_content)` / `diff()` — unified diff without writing
- `snapshot()` → `{rel_path: content}` dict; `restore(snap)` → revert
- `move(src, dst)` / `rename()` — move within base dir, creates parents
- `export_audit_log()` → JSON string; `EditResult.to_dict()` for serialisation

## DevLoop v2 changes
- New `quality_runner` and `dashboard` constructor args (both optional)
- `_run_quality_phase()` fires only after tests pass (saves time on failures)
- `with_agent(agent, cwd=".")` now also builds `QualityRunner(cwd=cwd)`
- All `_dash_*` helpers are wrapped in `try/except` — dashboard never crashes the loop

## SoftwareEngineer v2 changes
- Step 0 added: `_scan_workspace(path)` before requirement analysis
- `_enrich_goal()` now includes workspace summary in the enriched prompt
- `SoftwareEngineerReport` gains `workspace_summary` and `quality_summary`
- `with_agent()` builds `ExecutionDashboard` and injects into DevLoop via `dev_loop._dashboard`
- `_count_cycles()` replaces fragile `loop_result._cycle_count()` lambda

## Reliability (REPL)
`repl.py` wraps `router.dispatch()` in `except Exception` — any command error is logged,
shown as a friendly message, and the REPL continues. Ctrl+C during a command is also caught.

**Why:** "No uncaught exceptions should terminate MARK" (Phase 8 spec).

## validate_cmd patch path quirk
`_execute_scenario()` uses a local import of `SoftwareEngineer`. Tests that patch it must use
`smartagent.engineer.software_engineer.SoftwareEngineer.with_agent` as the patch target,
NOT `smartagent.ui.commands.validate_cmd.SoftwareEngineer` (which doesn't exist at module level).

## Test count
2026 total tests passing after v2.0. New tests: 143 across 4 files:
- `tests/test_file_editor_v2.py` (45)
- `tests/test_quality_runner.py` (38)
- `tests/test_dashboard.py` (42)
- `tests/test_validate_cmd.py` (18)
