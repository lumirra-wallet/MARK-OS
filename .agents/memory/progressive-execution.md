---
name: Progressive Execution Architecture
description: 3-tier routing in SoftwareEngineer.build() — trivial/small→fast path, medium→lean pipeline, large/enterprise→full pipeline.
---

## Rule

`SoftwareEngineer.build()` classifies every goal with `classify_complexity()` and routes to one of three execution tiers **before** any analysis or DevLoop work begins.

| Tier | Complexity values | Route | Max iterations | Quality |
|------|------------------|-------|----------------|---------|
| 1 | TRIVIAL, SMALL | `_fast_path_build()` — 1 LLM call, no DevLoop | n/a | no |
| 2 | MEDIUM | DevLoop, capped at 2 | 2 | no |
| 3 | LARGE, ENTERPRISE | Full DevLoop pipeline | as requested | yes |

## Key files

- `smartagent/performance/complexity.py` — `classify_complexity(goal) → TaskComplexity`; pattern lists have priority ordering: TRIVIAL → ENTERPRISE → LARGE → MEDIUM → word-count heuristic.
- `smartagent/engineer/fast_path.py` — `FastPathBuilder` + `FastPathResult`; `FastPathResult` duck-types `LoopResult` (has `.files_created`, `.files_modified`, `.project_dir`, `.stop_reason`, `.iterations`, `.as_display_lines()`).
- `smartagent/engineer/software_engineer.py` — `build()` classification + routing; `_fast_path_build()` wraps FastPathBuilder.
- `smartagent/executive/planner.py` — `_COMPLEXITY_UNSET` sentinel; `create_plan(goal, complexity="medium")` → `medium_app` template (3 tasks: Planning + Implementation + Testing, no Research/Architecture/Documentation).
- `smartagent/ui/commands/engineer_cmd.py` — tier banner before build(), `--timing` flag, `_build_timing_report()`.

## Critical pattern-matching gotcha

**"system with …"** fires the LARGE pattern `r"\bsystem\s+(?:with|that)\b"` before MEDIUM patterns are checked. Any goal containing "system with" will classify as LARGE, not MEDIUM, even if it also contains a MEDIUM keyword like "authentication system".

Test goals for MEDIUM tier must avoid "system with". Reliable MEDIUM anchors:
- `"user management"` → `r"\buser\s+management\b"`
- `"blog"` → `r"\bblog\b"`
- `"e-commerce"` / `"shop"` / `"store"`
- `"chat app"` / `"social"` / `"forum"` / `"portfolio"`

## Planner sentinel trick

`create_plan(goal)` (no complexity arg) → legacy keyword matching (unchanged).  
`create_plan(goal, complexity="medium")` → `medium_app` 3-task template.  
`create_plan(goal, complexity="large"|"enterprise")` → falls back to keyword matching.

Custom Planner subclasses used in tests **must** accept `**kwargs` in `create_plan()` or they raise `TypeError` when `Orchestrator.execute_goal(goal, complexity=...)` passes the complexity kwarg through.

## `engineer_cmd.py` --timing flag

`_build_timing_report(eng, report)` walks: `eng._dev_loop._executive.current_context.metadata["worker_timings"]` → calls `format_timing_table(timings)`. Returns `[]` if no data (fast path never records worker timings — Ollama workers do).

**Why:** Avoid wasted pipeline overhead for simple tasks; stream progress to user at each phase so they can see activity on long builds.

**How to apply:** Always use `classify_complexity()` before creating any DevLoop or Planner object. Never add `complexity` to `SoftwareEngineer.__init__()` — classification is always per-goal at call time.
