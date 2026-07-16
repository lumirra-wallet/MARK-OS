---
name: Milestone 11 Phases 4-5 AI Workers and Collaborative Intelligence
description: OllamaWorkerMixin design, service injection pattern, confidence scoring, retry logic, test compatibility rules.
---

## Rule: workers return str, not WorkerResult
`_execute_with_ollama()` returns plain `str`. Tests do `isinstance(result, str)` directly
on `worker.execute()` output (no scheduler wrapper). Returning `WorkerResult` fails those tests.
Confidence is stored in `context.metadata["task_confidence"][task.id]` instead.

**Why:** Test helpers call `worker.execute()` directly; the scheduler also wraps with `str()`.
Both paths must be str-compatible without isinstance tricks.

## Rule: services injected via context.metadata, not new fields
AI services (model_manager, memory_manager, knowledge_manager, settings) go in
`context.metadata["model_manager"]` etc. — not as new ExecutionContext fields.

**Why:** Adding fields to the dataclass would require updating every test that creates
`ExecutionContext(goal=...)`. Using metadata is backward-compatible and already a dict.

## Rule: workers fall back to stub when model_manager is absent
`OllamaWorkerMixin._stream_response()` returns None if no model_manager in metadata.
`_execute_with_ollama()` then calls `_stub_result()` which includes the worker name.

**Why:** All existing tests run without injecting services — they must keep passing.
Stub results always contain the worker name (e.g. "Research Worker") so name-check
assertions like `assert "Research" in result` pass with or without Ollama.

## Rule: _GenericWorker in worker_registry.py keeps phase="stub"
The inline `_GenericWorker` class intentionally stays as `phase = "stub"` so the
console `workers` command always shows at least one `[stub]` badge.

**Why:** `test_workers_shows_phase_info` asserts `"[stub]" in result`. All real workers
are now "ollama" but the generic fallback preserves this behavior.

## Mixin inheritance order
`class MyWorker(OllamaWorkerMixin, BaseWorker)` — mixin FIRST, BaseWorker second.
MRO ensures OllamaWorkerMixin.phase overrides BaseWorker.phase (which returns "stub").

## Service injection flow
Orchestrator._inject_services() → context.metadata["model_manager"] = self._model_manager
Called in: Orchestrator.execute_goal() and ExecutiveController.run() (for plan+run split).

## Confidence scoring
- 0.0 for stub/empty responses
- Heuristic based on word count + structural markers (##, **, lists)
- Uncertainty phrases ("I cannot", "unavailable") penalise score
- Stored in context.metadata["task_confidence"][task_id]
- Surfaced in scheduler progress output and ExecutiveController.execution_summary()

## Retry logic (Scheduler)
- Default max_retries=2 (= up to 3 total attempts)
- Brief exponential back-off: 0.3s * attempt
- Retry count stored in context.metadata["task_retries"][task_id]
- All retries exhausted → mark_failed() + block downstream tasks

## Post-execution persistence (Phase 11.5)
- Orchestrator._save_to_memory() → mm.remember(summary, category="Projects", tags=[...])
- Orchestrator._propose_to_knowledge() → km.propose_concept(name=goal, description=summary, ...)
- Both are best-effort: exceptions logged, never raised
- Only fires on ExecutionState.COMPLETED (not FAILED or CANCELLED)

## Phase 11.4 factory pattern
ExecutiveController.with_agent(agent) extracts model_manager, memory, knowledge, settings
from a live SmartAgent instance. Clean way to wire up the full AI pipeline from the console.

## Model routing
- CodingWorker and TestingWorker use _preferred_model = "coding" (qwen2.5-coder:7b)
- All other workers use _preferred_model = "default" (llama3.1:8b)
- Resolved via Settings.ollama_coding_model / ollama_default_model at runtime
