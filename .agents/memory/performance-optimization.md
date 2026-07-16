---
name: Performance Optimization v2.0
description: Architecture, decisions, and gotchas for the v2.0 performance audit and optimization layer.
---

# Performance Optimization v2.0

## Rule: Complexity detection belongs in the caller, not the Planner

`Planner.create_plan(goal, complexity="medium")` accepts an explicit `complexity` argument.
Only `complexity="trivial"` triggers the 2-task fast-path.  The Planner does NOT auto-detect
complexity internally — that caused 11 test regressions when goals like "Build a calculator"
were silently rerouted to the trivial template.

**Why:** Pre-existing tests call `create_plan(goal)` without complexity and rely on
keyword-based template matching (5-task default, 5-task api, 3-task script, etc.).
Auto-detect in the Planner breaks all of them.

**How to apply:** DevLoop / SoftwareEngineer should call `classify_complexity(goal)` first,
then pass the result to `create_plan(goal, complexity=detected.value)`.

---

## Rule: Medium filtering was also removed from the Planner

Earlier drafts filtered the keyword-matched template based on `complexity="medium"` by
removing DESIGN/DOCUMENTATION task types.  This broke `test_api_template_triggered`
(which expects Architecture) and `test_database_template_triggered` (expects Documentation).
The filter was removed entirely — the Planner only applies the trivial 2-task shortcut.

---

## Performance package layout

```
smartagent/performance/
  __init__.py        — exports all four submodules
  complexity.py      — TaskComplexity enum + classify_complexity(goal)
  worker_timer.py    — WorkerTiming dataclass + format_timing_table()
  prompt_auditor.py  — PromptAudit + measure_prompt()
  worker_cache.py    — WorkerCache (MD5 LRU 256 entries) + get_global_cache()
```

OllamaWorkerMixin integrates all four: checks cache → times Ollama call → records audit → caches result.

---

## CommandRouter.register() signature

Parameters: `name`, `handler`, `description`, `group`, `order` (int).
No `usage` or `priority` — those will raise TypeError.
`has_command(name)` was added in v2.0.

---

## RequirementAnalyzer: backend-only pattern list

`_BACKEND_ONLY_PATTERNS` suppresses frontend classification for CLI/script/calculator goals.
Does NOT include "library", "module", "package" — those are ambiguous (Vue.js component
library is frontend; a Python utility library is backend).  Only include unambiguous
CLI/computational patterns.

---

## Test counts

- Pre-v2.0: 2026 tests passing
- Post-v2.0 performance optimization: 2202 tests passing (+176 new)
