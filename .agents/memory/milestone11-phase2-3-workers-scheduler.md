---
name: Milestone 11 Phases 2-3 — Workers and Scheduler
description: Architecture decisions, wiring notes, and gotchas for Phase 2 (workers) and Phase 3 (scheduler+cancellation).
---

# Milestone 11 Phases 2 & 3

## What was built

**Phase 2 — Workers**
- `smartagent/executive/workers/` package: `BaseWorker` (ABC), `WorkerResult`, 9 specialist workers
- Multi-type workers: `DesignWorker` (DESIGN + ARCHITECTURE), `CodingWorker` (CODING + IMPLEMENTATION)
- `MemoryWorker` deliberately has `task_types = []` — it's cross-cutting, not auto-routed
- `build_default_registry()` registers real classes; `list_workers()` deduplicates by class identity (id())
- Console: `workers`, `worker info <type>`

**Phase 3 — Scheduler + Cancellation**
- `ExecutionContext.cancel()` — marks all non-terminal tasks BLOCKED, transitions to CANCELLED
- `ExecutionContext.is_cancelled` property
- `ExecutiveController.cancel()` — returns True/False; False when no plan or already terminal
- `Scheduler.run()` — checks `is_cancelled` BEFORE calling `transition_to(RUNNING)` (critical: early exit)
- Final state logic: COMPLETED only when ALL tasks are terminal and none failed; BLOCKED/PENDING non-terminal tasks → FAILED
- Console: `queue`, `run`, `cancel`

## Key decisions

**Scheduler early-exit before transition_to(RUNNING)**
The check for `context.is_cancelled` must come before `context.transition_to(ExecutionState.RUNNING)`,
not after. Otherwise RUNNING overwrites CANCELLED and the context arrives in the wrong state.

**Why:** `transition_to()` unconditionally sets `state`. If a context is cancelled, no state transition
should happen — return immediately.

**Non-terminal tasks (BLOCKED/PENDING) → FAILED final state**
When the scheduler loop exits, any task that is not terminal (COMPLETED or FAILED) signals unfinished
work — usually caused by an upstream task blocking downstream ones. The final state should be FAILED,
not COMPLETED.

**Why:** A plan where tasks are left BLOCKED looks "done" to the scheduler (queue is empty) but the
goal was not actually accomplished.

**`worker info <unknown>` falls back to GenericWorker**
The registry `get()` method falls back to the GENERIC worker when a specific type is not registered.
`worker info nonexistent` therefore shows the Generic Worker rather than an error message.

**Why:** This is correct registry behavior — the fallback exists to ensure any task type can be
handled. The test was updated to reflect this.

**`list_workers()` deduplicates by class id()**
CodingWorker is registered for both CODING and IMPLEMENTATION. `list_workers()` tracks seen class
ids and skips duplicates so the console shows "Coding Worker" exactly once.

**Why:** The registry maps task_type → class (many-to-one is intentional). The listing should show
workers, not task-type mappings.

## Test files
- `tests/test_executive.py` — 104 Phase 1 tests
- `tests/test_executive_phase2.py` — ~130 Phase 2+3 tests
- Total: 201 executive tests, all pass
