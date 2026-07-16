---
name: Milestone 15 Workspace Manager
description: Architecture, key design decisions, and integration patterns for the Project Workspace Manager (M15).
---

## Rule

Per-workspace service isolation is implemented by the **Orchestrator**, not
by WorkspaceManager itself.  WorkspaceManager stays import-free of
MemoryManager and KnowledgeManager at module load time (lazy import inside
`active_memory()` / `active_knowledge()`).

**Why:** Prevents circular imports.  WorkspaceManager can be imported anywhere;
MemoryManager and KnowledgeManager are only loaded when a workspace is first accessed.

**How to apply:** If future code needs to inject new services per-workspace, add them
in `Orchestrator._inject_services()` — not in WorkspaceManager.

---

## Key class responsibilities

| Class | File | Responsibility |
| --- | --- | --- |
| `Workspace` | `workspace/workspace.py` | Dataclass — name, status, paths (all computed), counters. No IO. |
| `WorkspaceStore` | `workspace/workspace_store.py` | Atomic JSON save/load per workspace dir. Uses `.tmp` + rename. |
| `WorkspaceManager` | `workspace/workspace_manager.py` | CRUD, active-workspace lifecycle, lazy scoped service cache. |
| `file_output.py` | `workspace/file_output.py` | `write_output_file(ws, filename, content)` → `output/<filename>`. |

---

## Integration points (Orchestrator)

1. `_inject_services(context)` — if `workspace_manager.active` is not None:
   - Writes `context.metadata["workspace"]` = active Workspace
   - Overrides `context.metadata["memory_manager"]` with scoped instance
   - Overrides `context.metadata["knowledge_manager"]` with scoped instance

2. `execute_goal()` — calls `_save_to_workspace(result)` after `_run_reflection`.
   This writes `history/<plan_id>.json` and appends lessons to `LESSONS.md`.

---

## Scoped service cache

`WorkspaceManager._scoped_memory[name]` and `_scoped_knowledge[name]` hold
one manager per workspace for the lifetime of the session.  They are cleared
in `delete()` to avoid dangling references.

---

## Name validation

`validate_workspace_name(name)` — regex `^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$`:
- 3–63 characters
- Lowercase letters, digits, hyphens only
- No leading/trailing hyphens
- "ws" (2 chars) is **invalid** — minimum is 3.

---

## Test count: 108 tests (tests/test_workspace.py), 0 regressions in 1163 pre-existing tests.

---

## Disk layout

```
workspaces/<name>/
  workspace.json   ← atomic-written metadata
  goals.md         ← append-only timestamped goal log
  memory/          ← scoped MemoryManager (vault.root = this dir)
  knowledge/       ← scoped KnowledgeManager
  output/          ← files written by workers
  history/         ← one JSON per execution run (keyed by plan_id)
  LESSONS.md       ← distilled reflection lessons per run
```
