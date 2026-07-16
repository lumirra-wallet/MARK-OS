---
name: Milestones 18-19-20 Workspace Intelligence / File Editing / Self Debugging
description: Architecture, key decisions, and gotchas for M18 (ProjectScanner), M19 (FileEditor + FileEditMixin), M20 (TracebackParser + DebugLoop + DebugWorker).
---

## Milestone 18 — Workspace Intelligence

### What was built
`smartagent/workspace/scanner.py` — `ProjectScanner` + `ProjectSnapshot` dataclass.

7-step scan pipeline:
1. `_collect_files` — walk tree, skip `_IGNORE_DIRS`, detect language by extension, flag test files
2. `_build_module_map` — Python file path → dotted module name (strips `.__init__`)
3. `_collect_imports` — `ast.parse()` → `ImportEdge` records (both `import X` and `from X import`)
4. `_collect_dependencies` — parse requirements.txt, pyproject.toml, setup.cfg, package.json
5. `_collect_git` — subprocess `git rev-parse`, `git status --porcelain`, `git log --oneline -1`
6. `_detect_architecture` — keyword matching on directory names (MVC / DDD / Clean / Layered / Flat / Standard)
7. `_compute_summary` — `file_count`, `test_count`, `primary_language`

**Console commands**: `scan [path]`, `snapshot`, `imports [module]`  
**Snapshot persisted to**: `.mark/project-snapshot.md` in active workspace output/  
**Stored on agent as**: `agent._project_snapshot`

### Key decisions
- `_IGNORE_DIRS` is a `frozenset` — checked via `in`, not regex, for speed.
- `_detect_language` uses `os.path.splitext(filepath)[1].lower()` so uppercase `.PY` maps correctly.
- AST import parsing is best-effort: `SyntaxError` / `OSError` are silently skipped (files stay importless in the graph).
- pyproject.toml parsed with regex (no TOML dependency). Heuristic; works for `[project]` and `[tool.poetry.dependencies]`.
- Git availability gated on `git rev-parse --is-inside-work-tree` → returncode 0.

---

## Milestone 19 — File Editing Engine

### What was built
`smartagent/workspace/file_editor.py` — `FileEditor` + `EditResult`.  
`smartagent/executive/workers/file_edit_mixin.py` — `FileEditMixin`.

**FileEditor** is a scoped, tracked file editor. All paths resolved relative to `base_dir`. Path escape checked via `os.path.normpath` + `startswith(base_dir + os.sep)`. Operations: `create`, `edit`, `patch`, `delete`, `read`, `exists`, `list_files`, `list_edits`, `written_files`, `summary`.

**FileEditMixin** overrides `execute()` in the MRO and calls `_write_output_files()` after the parent execute chain returns. Must be the **leftmost** class in the MRO (before `WorkerToolMixin`).

### Injection into workers
`Orchestrator._inject_file_editor()` runs before `_inject_services()` and sets `context.metadata["file_editor"]`. It uses the active workspace's `output_path` if available, or `cwd/output/` as fallback.

**CodingWorker** and **TestingWorker** now inherit `FileEditMixin` first in their MRO.

### Filename annotation patterns (for FileEditMixin)
- **Pattern B** (fence label): ` ```python auth.py ` — filename on the opening fence
- **Pattern A** (first-line comment): `# filename: auth.py` or `# file: auth.py`
- **Pattern C** (MARK marker): `# ---FILE: routes/api.py---`

**Critical**: `_FIRSTLINE_NAME_RE` must list `filename:` before `file:` before `FILE[-:]?` in the alternation — otherwise `FILE` (4 chars) greedily matches the first 4 chars of `filename:`, preventing the more-specific alternative from matching.

---

## Milestone 20 — Self Debugging

### What was built
`smartagent/debug/__init__.py`  
`smartagent/debug/traceback_parser.py` — `TracebackParser`, `ParsedTraceback`, `TracebackFrame`  
`smartagent/debug/debug_loop.py` — `DebugLoop`, `DebugResult`, `DebugAttempt`  
`smartagent/executive/workers/debug_worker.py` — `DebugWorker`

**TracebackParser** splits on `Traceback (most recent call last):`, then parses `File "…", line N, in func` frames and the final `ErrorType: message` line. Pytest `FAILED` markers detected for `test_name`.

**`root_cause_frame`**: last frame where path doesn't contain `site-packages` or `/lib/python` and doesn't start with `<`. Falls back to last frame if all are stdlib.

**DebugLoop** flow per attempt:
1. `subprocess.run(command, shell=True, capture_output=True, timeout=120)`
2. `TracebackParser.parse_all(output)` → list of tracebacks
3. For each unique failing file: call `debug_worker.fix(tb, filepath, file_content)`
4. If fixed content unchanged → stop (no fix possible)
5. Write fix, re-run

**DebugWorker** has two interfaces:
- `execute(task, context)` — standard BaseWorker for DEBUGGING tasks in Orchestrator
- `fix(traceback, filepath, file_content)` — called directly by DebugLoop

Phase 2 stub: `fix()` returns original content unchanged → DebugLoop detects "no change" and stops immediately.  
Phase 4 (Ollama): calls `model_manager.generate()` or `model_manager.chat_stream()` with a focused system prompt. Strips accidental fenced code block wrapping from response.

**Console commands**: `debug <command>`, `debug-parse <command>`

### TaskType
`TaskType.DEBUGGING` added to the enum. DebugWorker registered in `build_default_registry()`.

---

## Test counts (post-M18/19/20)
- `tests/test_scanner.py`: 60 tests
- `tests/test_file_editor.py`: 73 tests  
- `tests/test_debug.py`: 64 tests
- Total project: 1565 tests, all passing
