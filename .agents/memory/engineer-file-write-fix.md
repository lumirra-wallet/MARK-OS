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

## Test file

`tests/test_engineer_e2e.py` — 32 tests covering all five bugs. Total suite: 2311 tests.
