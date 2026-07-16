---
name: Engineer file-write pipeline fix
description: Root causes and fixes for the bug where `engineer` reports success but creates no files. 2311 total tests after fix.
---

## The five root causes

1. **System prompt format mismatch (most critical)**
   Workers instructed LLMs to use ` ```python filename: calculator.py` but `_FENCE_RE` in FileEditMixin
   cannot parse `filename:` as a fence label — `fence_name` requires a `word.ext` pattern with no prefix.
   The fence line also failed the trailing `[ \t]*\n` guard, so the entire block was silently skipped.

   **Fix:** CodingWorker and TestingWorker now instruct `` ```python calculator.py `` (Pattern B, no label).

2. **FileEditor rooted at `./output/` not `./`**
   `Orchestrator._inject_file_editor` defaulted to `os.path.join(os.getcwd(), "output")`.
   Files landed in `./output/calculator.py`, invisible to a bare `find . -name "calculator.py"`.

   **Fix:** Default is now `os.getcwd()`. The `set_project_dir(path)` method lets DevLoop override it.

3. **Tests run against SmartAgent's own 2000+ suite**
   `DevLoop._run_test_phase` ran bare `pytest` (no args) in the CWD (SmartAgent root),
   discovering all internal tests — generated project tests never ran.

   **Fix:** `_build_scoped_test_cmd(test_cmd, file_editor, project_dir)` detects generated `test_*.py`
   files from the FileEditor edit log and replaces bare `pytest` with `pytest test_foo.py`.
   Custom test commands (e.g. `pytest tests/ -v`) are returned unchanged.

4. **No project_dir threading through the pipeline**
   SoftwareEngineer → DevLoop → Orchestrator had no way to agree on which directory to use.

   **Fix:** `SoftwareEngineer.build(project_dir=None)`, `DevLoop.run(project_dir=None)` both accept
   the parameter. `_set_orchestrator_project_dir(executive, path)` propagates it to `Orchestrator`
   before `receive_goal()` is called. DebugLoop cwd is patched via `_patch_debug_loop_cwd`.

5. **SoftwareEngineerReport / LoopResult had no file tracking**
   No fields for which files were created.

   **Fix:** Both dataclasses gained `files_created: list[str]`, `files_modified: list[str]`,
   `project_dir: str`. Both `as_display_lines()` show `+ file.py` / `~ file.py` / `(in /path)`.

## Key invariants going forward

- `_FENCE_RE` fence_name group: `[^\s`\n]+\.[a-zA-Z0-9]+` — needs `word.ext` with NO prefix colon.
  Any system prompt that puts `filename:` before the path will silently fail extraction.
- `_build_scoped_test_cmd` only rewrites bare `"pytest"` or `"python -m pytest"` — never custom cmds.
- `Orchestrator.set_project_dir()` must be called BEFORE `execute_goal()` / `receive_goal()`.
  After those run, `_inject_file_editor` has already fired.
- `DevLoop._run_test_phase` and `_run_debug_phase` pass `cwd=project_dir` to subprocess.

## Bug 6 — MRO override: CodingWorker.execute() bypasses FileEditMixin (discovered post-v2.0)

CodingWorker and TestingWorker both defined their own execute() that called
`_execute_with_tools()` directly. Because CodingWorker comes before FileEditMixin
in the MRO (FileEditMixin, WorkerToolMixin …), Python found CodingWorker.execute()
first, FileEditMixin.execute() was never called, and files were NEVER written.

**Fix:**
1. Add `execute()` to `WorkerToolMixin` — calls `_execute_with_tools()`.
2. Remove `execute()` from `CodingWorker` and `TestingWorker`.
   The correct MRO chain is: FileEditMixin.execute() → super().execute()
   → WorkerToolMixin.execute() → _execute_with_tools() → LLM → back to
   FileEditMixin._write_output_files() → disk.

## Bug 7 — "Where is hello.py?" routed to chat model

Intent router's `_CHAT_STARTERS` includes "where", so "where is hello.py?" went
to `fallback_chat()` which had no knowledge of what was just built.

**Fix:**
1. `engineer_cmd.handle_engineer()` now stores `agent.last_engineer_report = report`
   after each build.
2. `intent_aware_fallback()` calls `_answer_last_build_file_query(agent, raw)` BEFORE
   `classify_intent()`. If the query mentions a file from `last_engineer_report`, the
   absolute path is returned immediately — the chat model is never reached.
3. `_FILE_LOC_RE` regex matches: "where is X", "where's X", "find X", "locate X",
   "path to X", "path of X".

## Test file

`tests/test_engineer_e2e.py` — 42 tests (32 original + 10 full-pipeline E2E).
Total suite: 2321 tests.
