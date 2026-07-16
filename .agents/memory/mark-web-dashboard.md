---
name: MARK Web Dashboard Phase 2+ (All 20 Features)
description: React+Vite dashboard; all 20 spec features implemented; architecture + gotchas for future sessions.
---

## Feature status (all 20 complete)

| # | Feature | Backend file | Frontend component |
|---|---|---|---|
| 1 | Real Planning Agent (task graph) | api_task_graph.py | TaskGraphView.tsx |
| 2 | Parallel Worker Scheduler | api.py + existing workers | ExecutionView / WorkersView |
| 3 | Tool Calling Framework | api_tools.py | ToolsPanel.tsx |
| 4 | Memory Engine (semantic TF-IDF) | existing memory | MemoryPanel.tsx |
| 5 | RAG over Repository | api_code.py → /rag/search | CodeIndexPanel.tsx |
| 6 | Codebase Indexer (AST) | api_code.py → /code/* | CodeIndexPanel.tsx |
| 7 | Multi-Agent Communication | api_task_graph.py → /agent/messages | TaskGraphView.tsx |
| 8 | Self Reflection | api.py post-run hook → ReflectionComplete WS | markStore handles event |
| 9 | Conversation Branches | markStore.ts: branches/activeBranch/createBranch/switchBranch/deleteBranch | ChatView BranchBar |
| 10 | Checkpoints | api_checkpoints.py | CheckpointsPanel.tsx |
| 11 | Live Terminal | api_terminal.py | LiveTerminal.tsx |
| 12 | Better Git Integration | api_git_enhanced.py | GitPanel.tsx (5 tabs: log/status/stage/branches/stash) |
| 13 | Token Budget Manager | api.py post-run → TokenBudgetUpdate WS | Dashboard TopNav TokenBudgetPill |
| 14 | Long Running Jobs | api_jobs.py | JobsPanel.tsx |
| 15 | Model Router | model_router.py + api_system.py endpoints | ModelsPanel.tsx router section |
| 16 | Agent Timeline | api_timeline.py | TimelineView.tsx |
| 17 | Evaluation Framework | api_eval.py + api.py auto-submit | EvaluationPanel.tsx |
| 18 | Plugin Architecture | api_tools.py plugin discovery | ToolsPanel.tsx |
| 19 | Security Layer | api_tools.py path sandbox + audit ring buffer | ToolsPanel audit tab |
| 20 | Performance Dashboard | existing PerformanceView.tsx | PerformanceView.tsx |

## Architecture rules

- All new backend features are isolated `smartagent/server/api_*.py` files with their own FastAPI routers.
- All new frontend panels are in `artifacts/mark-dashboard/src/components/`.
- `app.py` mounts all routers.
- `events.py` holds all WS event constants (20+ new ones added).
- `Dashboard.tsx` renders every panel via sidebar icon-rail tabs; sidebar is now scrollable (overflow-y-auto).

## Key decisions and gotchas

**Why:** In-memory TF-IDF for RAG (no vector DB), keeps stack local.
**How to apply:** `api_code.py` `build_index()` + `rag_search()`.

**Why:** Post-run hooks (token budget, evaluation, reflection, job completion) are async fire-and-forget inside `_run()` in `api.py`; wrapped in try/except so any failure is silent.
**How to apply:** Look for "Post-run hooks" comment block in `api.py`.

**Why:** `_run_id` is a dynamic attribute set on the `RunState` dataclass instance (not declared in the dataclass). Python allows this; no need to declare it.
**How to apply:** `_state._run_id = new_run_id()` — works fine; don't add it to the dataclass.

**Why:** Conversation branches store messages per-branch name in `markStore.ts`; switching branches swaps the `messages` array and saves the current one.
**How to apply:** `createBranch(name)` → copies current messages; `switchBranch(name)` → saves current + restores target.

**Why:** `TokenBudgetPill` placed BEFORE `Dashboard` in `Dashboard.tsx` — avoids "not defined" runtime error during HMR when component order matters.
**How to apply:** Always define helper components above the component that uses them in the same file.

**Why:** `JSX.Element` type causes TS error with isolatedModules — use `React.ReactElement` for icon map types.
**How to apply:** Any `Record<string, JSX.Element>` → `Record<string, React.ReactElement>`.

**Why:** `useNodesState`/`useEdgesState` in React Flow need explicit type parameters.
**How to apply:** `useNodesState<Node>([])` and `useEdgesState<Edge>([])`.

## Test counts

- Python: 2460 tests (stable — no changes broke existing tests)
- TypeScript: 0 errors (`tsc --noEmit`)
