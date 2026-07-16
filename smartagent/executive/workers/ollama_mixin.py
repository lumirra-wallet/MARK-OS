"""
OllamaWorkerMixin — Phase 11.4 / 11.5 / v2.0 Performance Upgrade.

Provides Ollama-powered execution with:
  - Specialist system prompts per worker (trimmed to word caps — v2.0)
  - Prior-work context injection (Phase 11.5 collaborative intelligence)
  - Knowledge and memory context enrichment
  - Confidence scoring
  - Graceful fallback to stub when Ollama is unavailable
  - Per-worker timing (v2.0 — Phase 1: Performance Audit)
  - Prompt-section auditing (v2.0 — Phase 2: Prompt Audit)
  - Output caching (v2.0 — cache by goal+worker+model)
  - Complexity-aware context caps (v2.0 — Phase 3: Prompt Optimization)

Context caps (v2.0 — reduced from 3000/800):
  _MAX_PRIOR_CHARS    = 500   (was 3000) per prior result
  _MAX_CONTEXT_SNIPPET = 300  (was 800)  per knowledge/memory snippet

Services via ``context.metadata``:
  "model_manager"    — ModelManager
  "memory_manager"   — MemoryManager
  "knowledge_manager"— KnowledgeManager
  "settings"         — Settings

If ``model_manager`` is absent the mixin returns ``_stub_result()``,
so all existing tests continue to pass unchanged.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task
    from smartagent.executive.workers.base_worker import WorkerResult

logger = get_logger(__name__)

# v2.0 Performance Optimization — reduced from 3000 / 800
_MAX_PRIOR_CHARS = 500
_MAX_CONTEXT_SNIPPET = 300


class OllamaWorkerMixin:
    """
    Mixin that upgrades any ``BaseWorker`` subclass to Phase 11.4 (Ollama).

    v2.0 additions:
      - Per-worker timing stored in ``context.metadata["worker_timings"]``
      - Prompt-section audit stored in ``context.metadata["prompt_audits"]``
      - Output cache (global singleton) — cache by goal+task+worker+model
      - Complexity-aware prior-result cap (``TaskComplexity.max_prior_chars``)

    Subclasses set class-level attributes to customise behaviour:

    ``_system_prompt`` — specialist system prompt sent as the ``system``
        role message in every chat call.

    ``_preferred_model`` — ``"default"`` (general model) or ``"coding"``
        (coding-optimised model such as qwen2.5-coder).  The actual model
        id is resolved from ``Settings`` at runtime.
    """

    _system_prompt: str = "You are a helpful AI assistant."
    _preferred_model: str = "default"   # "default" | "coding"

    # ------------------------------------------------------------------
    # Phase identity
    # ------------------------------------------------------------------

    @property
    def phase(self) -> str:  # type: ignore[override]
        return "ollama"

    # ------------------------------------------------------------------
    # Service accessors
    # ------------------------------------------------------------------

    def _get_model_manager(self, context: "ExecutionContext"):
        return context.metadata.get("model_manager")

    def _get_memory_manager(self, context: "ExecutionContext"):
        return context.metadata.get("memory_manager")

    def _get_knowledge_manager(self, context: "ExecutionContext"):
        return context.metadata.get("knowledge_manager")

    def _get_settings(self, context: "ExecutionContext"):
        return context.metadata.get("settings")

    # ------------------------------------------------------------------
    # Model resolution
    # ------------------------------------------------------------------

    def _resolve_model_id(self, context: "ExecutionContext") -> str | None:
        settings = self._get_settings(context)
        if settings is None:
            return None
        if self._preferred_model == "coding":
            return getattr(settings, "ollama_coding_model", None)
        return getattr(settings, "ollama_default_model", None)

    # ------------------------------------------------------------------
    # Context assembly (Phase 11.5 — collaborative intelligence)
    # ------------------------------------------------------------------

    def _effective_prior_cap(self, context: "ExecutionContext") -> int:
        """Return the max-chars cap for prior results, scaled by complexity."""
        try:
            from smartagent.performance.complexity import TaskComplexity
            complexity_str = context.metadata.get("complexity", "medium")
            try:
                tc = TaskComplexity(complexity_str)
                return tc.max_prior_chars
            except ValueError:
                pass
        except ImportError:
            pass
        return _MAX_PRIOR_CHARS

    def _format_prior_results(self, task: "Task", context: "ExecutionContext") -> str:
        prior = self._prior_results(task, context)  # type: ignore[attr-defined]
        if not prior:
            return ""
        cap = self._effective_prior_cap(context)
        parts: list[str] = ["---\n## Context from prior steps\n"]
        for i, result_text in enumerate(prior, 1):
            snippet = (
                result_text[:cap] + "\n…[truncated]"
                if len(result_text) > cap
                else result_text
            )
            parts.append(f"### Step {i}\n{snippet}\n")
        return "\n".join(parts)

    def _fetch_knowledge_context(self, context: "ExecutionContext") -> str:
        km = self._get_knowledge_manager(context)
        if km is None:
            return ""
        try:
            results = km.search(context.goal, max_results=3)
            if not results:
                return ""
            snippets = [str(r)[:_MAX_CONTEXT_SNIPPET] for r in results[:3]]
            return "## Relevant Knowledge\n" + "\n\n".join(snippets)
        except Exception as exc:
            logger.debug("OllamaWorkerMixin: knowledge context unavailable: %s", exc)
            return ""

    def _fetch_memory_context(self, context: "ExecutionContext") -> str:
        mm = self._get_memory_manager(context)
        if mm is None:
            return ""
        try:
            memories = mm.search(context.goal, limit=3)
            if not memories:
                return ""
            snippets = [str(m)[:_MAX_CONTEXT_SNIPPET] for m in memories[:3]]
            return "## Relevant Past Experience\n" + "\n\n".join(snippets)
        except Exception as exc:
            logger.debug("OllamaWorkerMixin: memory context unavailable: %s", exc)
            return ""

    def _build_messages(
        self,
        task: "Task",
        context: "ExecutionContext",
    ) -> list[dict[str, str]]:
        """
        Assemble the user-turn message list for ``chat_stream``.

        v2.0: records a PromptAudit in context.metadata["prompt_audits"].
        """
        prior_block   = self._format_prior_results(task, context)
        goal_text     = f"## Goal\n{context.goal}"
        task_text     = f"## Current Task\n**{task.title}**\n{task.description or task.title}"
        knowledge_ctx = self._fetch_knowledge_context(context)
        memory_ctx    = self._fetch_memory_context(context)

        sections: list[str] = []
        if prior_block:
            sections.append(prior_block)
        sections.append(goal_text)
        sections.append(task_text)
        if knowledge_ctx:
            sections.append(knowledge_ctx)
        if memory_ctx:
            sections.append(memory_ctx)

        # v2.0 — Prompt audit (Phase 2)
        self._record_prompt_audit(
            context=context,
            task=task,
            prior_block=prior_block,
            goal_text=goal_text,
            task_text=task_text,
            knowledge_ctx=knowledge_ctx,
            memory_ctx=memory_ctx,
        )

        return [{"role": "user", "content": "\n\n".join(sections)}]

    def _record_prompt_audit(
        self,
        context: "ExecutionContext",
        task: "Task",
        prior_block: str,
        goal_text: str,
        task_text: str,
        knowledge_ctx: str,
        memory_ctx: str,
    ) -> None:
        """Store a PromptAudit entry in context.metadata — best-effort."""
        try:
            from smartagent.performance.prompt_auditor import measure_prompt
            audit = measure_prompt(
                system=self._system_prompt,
                prior_results=prior_block,
                goal=goal_text,
                task_desc=task_text,
                knowledge=knowledge_ctx,
                memory=memory_ctx,
            )
            if "prompt_audits" not in context.metadata:
                context.metadata["prompt_audits"] = {}
            worker_name = getattr(self, "name", type(self).__name__)
            context.metadata["prompt_audits"][worker_name] = audit
        except Exception as exc:
            logger.debug("OllamaWorkerMixin: prompt audit failed: %s", exc)

    # ------------------------------------------------------------------
    # Ollama call
    # ------------------------------------------------------------------

    def _stream_full(
        self,
        context: "ExecutionContext",
        full_messages: list[dict[str, str]],
    ) -> str | None:
        """
        Stream a response for a caller-assembled full message list.

        Unlike ``_stream_response()``, this does NOT prepend the
        ``_system_prompt``.  Used by ``WorkerToolMixin``.
        """
        mm = self._get_model_manager(context)
        if mm is None:
            return None
        model_id = self._resolve_model_id(context)
        kwargs: dict = {}
        if model_id:
            kwargs["model_id"] = model_id
        try:
            tokens = list(mm.chat_stream(full_messages, **kwargs))
            text = "".join(tokens).strip()
            return text if text else None
        except Exception as exc:
            logger.warning(
                "OllamaWorkerMixin [%s]: stream_full failed: %s",
                getattr(self, "name", "worker"), exc,
            )
            return None

    def _resolve_system_prompt(self, context: "ExecutionContext") -> str:
        """
        Return the best available system prompt for this worker.

        Priority:
          1. Evolved prompt from the PromptRegistry (Milestone 14).
          2. The worker's class-level ``_system_prompt``.
        """
        worker_name = getattr(self, "name", type(self).__name__)
        system_prompts: dict = context.metadata.get("system_prompts", {})
        evolved = system_prompts.get(worker_name)
        if evolved:
            logger.debug(
                "OllamaWorkerMixin [%s]: using evolved prompt from registry",
                worker_name,
            )
            return evolved
        return self._system_prompt

    def _stream_response(
        self,
        context: "ExecutionContext",
        messages: list[dict[str, str]],
    ) -> str | None:
        """
        Call ``ModelManager.chat_stream`` and collect all tokens.

        Returns the joined text, or ``None`` if Ollama is unavailable.
        """
        mm = self._get_model_manager(context)
        if mm is None:
            return None

        model_id = self._resolve_model_id(context)
        system_prompt = self._resolve_system_prompt(context)
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        kwargs: dict = {}
        if model_id:
            kwargs["model_id"] = model_id

        try:
            tokens = list(mm.chat_stream(full_messages, **kwargs))
            text = "".join(tokens).strip()
            return text if text else None
        except Exception as exc:
            logger.warning(
                "OllamaWorkerMixin [%s]: stream failed: %s",
                getattr(self, "name", "worker"),
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Confidence scoring (Phase 11.5)
    # ------------------------------------------------------------------

    def _compute_confidence(self, text: str) -> float:
        if not text:
            return 0.0
        words = text.split()
        base = min(0.85, len(words) / 400 * 0.85)
        if any(m in text for m in ("##", "**", "1.", "- ", "* ", "\n\n", "```")):
            base = min(0.95, base + 0.10)
        if any(p in text.lower() for p in ("i cannot", "i am unable", "i don't know", "unavailable")):
            base = max(0.0, base - 0.20)
        return round(base, 2)

    # ------------------------------------------------------------------
    # Stub fallback
    # ------------------------------------------------------------------

    def _stub_result(self, task: "Task", context: "ExecutionContext") -> str:
        worker_name = getattr(self, "name", "Worker")
        return (
            f"[{worker_name}] {task.title}\n"
            f"  Goal: {context.goal}\n"
            f"  (Ollama unavailable — stub result)"
        )

    # ------------------------------------------------------------------
    # v2.0 — Timing helpers
    # ------------------------------------------------------------------

    def _record_timing(
        self,
        context: "ExecutionContext",
        prompt_text: str,
        response_text: str,
        elapsed: float,
        model_id: str | None,
        was_cached: bool = False,
        was_stub: bool = False,
    ) -> None:
        """Store a WorkerTiming record in context.metadata — best-effort."""
        try:
            from smartagent.performance.worker_timer import WorkerTiming
            worker_name = getattr(self, "name", type(self).__name__)
            timing = WorkerTiming.record(
                worker_name=worker_name,
                model_id=model_id,
                prompt_text=prompt_text,
                response_text=response_text,
                generation_time=elapsed,
                was_cached=was_cached,
                was_stub=was_stub,
            )
            if "worker_timings" not in context.metadata:
                context.metadata["worker_timings"] = []
            context.metadata["worker_timings"].append(timing)
        except Exception as exc:
            logger.debug("OllamaWorkerMixin: timing record failed: %s", exc)

    # ------------------------------------------------------------------
    # v2.0 — Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(
        self, context: "ExecutionContext", task: "Task", model_id: str | None
    ) -> str:
        try:
            from smartagent.performance.worker_cache import get_global_cache
            cache = get_global_cache()
            worker_name = getattr(self, "name", type(self).__name__)
            return cache.make_key(context.goal, task.title, worker_name, model_id)
        except Exception:
            return ""

    def _cache_get(self, key: str) -> str | None:
        if not key:
            return None
        try:
            from smartagent.performance.worker_cache import get_global_cache
            return get_global_cache().get(key)
        except Exception:
            return None

    def _cache_put(self, key: str, value: str) -> None:
        if not key:
            return
        try:
            from smartagent.performance.worker_cache import get_global_cache
            get_global_cache().put(key, value)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def _execute_with_ollama(
        self,
        task: "Task",
        context: "ExecutionContext",
    ) -> str:
        """
        Full Phase 11.4 execution: build messages → call Ollama → score.

        v2.0 additions:
          - Check worker cache before calling Ollama
          - Record WorkerTiming after the call
          - Falls back to ``_stub_result()`` when Ollama is unreachable

        Returns a plain ``str`` compatible with the BaseWorker contract.
        """
        model_id = self._resolve_model_id(context)
        cache_key = self._cache_key(context, task, model_id)
        was_cached = False

        # v2.0 — cache check
        cached = self._cache_get(cache_key)
        if cached is not None:
            was_cached = True
            text = cached
        else:
            messages = self._build_messages(task, context)
            prompt_text = messages[0]["content"] if messages else ""
            t0 = time.perf_counter()
            text = self._stream_response(context, messages)
            elapsed = time.perf_counter() - t0

            was_stub = text is None
            if was_stub:
                text = self._stub_result(task, context)

            # Store timing (covers both real and stub calls)
            self._record_timing(
                context=context,
                prompt_text=prompt_text,
                response_text=text,
                elapsed=elapsed,
                model_id=model_id,
                was_cached=False,
                was_stub=was_stub,
            )

            # Cache successful non-stub responses
            if not was_stub and cache_key:
                self._cache_put(cache_key, text)

            confidence = 0.0 if was_stub else self._compute_confidence(text)
            worker_name = getattr(self, "name", "worker")
            logger.debug(
                "OllamaWorkerMixin [%s]: task=%r confidence=%.2f",
                worker_name, task.title, confidence,
            )
            if "task_confidence" not in context.metadata:
                context.metadata["task_confidence"] = {}
            context.metadata["task_confidence"][task.id] = confidence
            return text

        # Cache hit — still record confidence + stub=False timing
        if was_cached:
            self._record_timing(
                context=context,
                prompt_text="",
                response_text=text,
                elapsed=0.0,
                model_id=model_id,
                was_cached=True,
                was_stub=False,
            )
            confidence = self._compute_confidence(text)
            worker_name = getattr(self, "name", "worker")
            logger.debug(
                "OllamaWorkerMixin [%s]: cache hit task=%r",
                worker_name, task.title,
            )
            if "task_confidence" not in context.metadata:
                context.metadata["task_confidence"] = {}
            context.metadata["task_confidence"][task.id] = confidence

        return text
