---
name: Milestone 11 Phase 1 — Executive Framework
description: Architecture decisions and wiring notes for the Phase 1 executive planning layer.
---

# Milestone 11 Phase 1 — Executive Framework

## Package location
`smartagent/executive/` — separate from `smartagent/mind/executive/` (the Mind OS controller).

## Naming disambiguation
- `agent.mind` → `smartagent.mind.executive.executive_controller.ExecutiveController` — Mind OS, observes state
- `agent.executive` → `smartagent.executive.executive_controller.ExecutiveController` — planning/task orchestration
- Imported in `brain/agent.py` as `PlanningController` to avoid name collision

## Key architecture decisions

**Linear dependency chain from Planner**
Each task depends only on its immediate predecessor. The Orchestrator/Scheduler
handle branching later. Simple and predictable for Phase 1.

**Why:** Phase 1 goal is a working, testable skeleton — not a production scheduler.
A linear chain is always valid, easy to display, and sufficient for the console demo.

**Rule-based Planner, no AI**
5 templates (api, script, research, algorithm, database, default) selected by keyword
regex on the goal string. Template name maps to a list of `_TaskSpec` dataclasses.

**Why:** Phase 4 replaces `_infer_template()` with an Ollama call returning JSON.
Everything else in the pipeline stays identical. Separating detection from the template
data makes this swap one method change.

**Scheduler stub in Phase 1**
`_execute()` returns `f"Completed: {task.title}"` when no worker registry has a
real callable. Real workers (Phase 2) register callable classes; `_execute()` already
checks for them.

**How to apply:** In Phase 2, register `BaseWorker` subclasses in `WorkerRegistry`.
`Scheduler._execute()` already tries `worker_class()` before falling back to stub.

**`agent.executive` created unconditionally in SmartAgent.__init__**
No settings flag. `PlanningController()` is cheap (no I/O, no threads).

**Console commands in Phase 1: `plan`, `tasks` only**
Phase 2 adds `workers`, `worker info`. Phase 3 adds `queue`, `run`, `cancel`.
Phase 4 adds `trace`, `history`.

## Test file
`tests/test_executive.py` — 104 tests, all pass. Uses `unittest.mock.MagicMock`
for agent fixture in console command tests (no full SmartAgent needed).

## Files created
executive/__init__.py, task.py, task_graph.py, task_queue.py, execution_state.py,
execution_context.py, planner.py, worker_registry.py, scheduler.py, orchestrator.py,
executive_controller.py, ui/commands/executive.py
