"""
OllamaWorkerMixin — Phase 11.4 / 11.5 AI execution layer for all workers.

Provides Ollama-powered execution with:
  - Specialist system prompts per worker
  - Prior-work context injection (Phase 11.5 collaborative intelligence)
  - Knowledge and memory context enrichment
  - Confidence scoring
  - Graceful fallback to stub when Ollama is unavailable

Usage::

    class MyWorker(OllamaWorkerMixin, BaseWorker):
        _system_prompt = "You are a specialist in ..."
        _preferred_model = "default"   # or "coding"

        def execute(self, task, context):
            return self._execute_with_ollama(task, context)

Services are accessed via ``context.metadata`` keys injected by the
Orchestrator (Phase 11.4):
  - ``context.metadata["model_manager"]``   — ModelManager instance
  - ``context.metadata["memory_manager"]``  — MemoryManager instance
  - ``context.metadata["knowledge_manager"]`` — KnowledgeManager instance
  - ``context.metadata["settings"]``        — Settings instance

If ``model_manager`` is absent the mixin returns ``_stub_result()``,
so all existing tests continue to pass unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task
    from smartagent.executive.workers.base_worker import WorkerResult

logger = get_logger(__name__)

# Maximum chars from a single prior result included in the context block.
_MAX_PRIOR_CHARS = 3000
# Maximum chars of knowledge/memory snippets appended to the prompt.
_MAX_CONTEXT_SNIPPET = 800


class OllamaWorkerMixin:
    """
    Mixin that upgrades any ``BaseWorker`` subclass to Phase 11.4 (Ollama).

    Subclasses set class-level attributes to customise behaviour:

    ``_system_prompt`` — specialist system prompt sent as the ``system``
        role message in every chat call.

    ``_preferred_model`` — ``"default"`` (general model) or ``"coding"``
        (coding-optimised model such as qwen2.5-coder).  The actual model
        id is resolved from ``Settings`` at runtime.

    ``_worker_label`` — label used in stub results, e.g. ``"[Research]"``.
        Defaults to the worker ``name`` property.
    """

    _system_prompt: str = "You are a helpful AI assistant."
    _preferred_model: str = "default"   # "default" | "coding"

    # ------------------------------------------------------------------
    # Phase identity
    # ------------------------------------------------------------------

    @property
    def phase(self) -> str:  # type: ignore[override]
        """Phase 11.4 workers are real Ollama workers."""
        return "ollama"

    # ------------------------------------------------------------------
    # Service accessors
    # ------------------------------------------------------------------

    def _get_model_manager(self, context: "ExecutionContext"):
        """Return the ModelManager from the context, or None."""
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
        """
        Resolve the target Ollama model id from Settings.

        Returns ``None`` if settings are unavailable (caller falls back to
        the ModelManager's currently active model).
        """
        settings = self._get_settings(context)
        if settings is None:
            return None
        if self._preferred_model == "coding":
            return getattr(settings, "ollama_coding_model", None)
        return getattr(settings, "ollama_default_model", None)

    # ------------------------------------------------------------------
    # Context assembly (Phase 11.5 — collaborative intelligence)
    # ------------------------------------------------------------------

    def _format_prior_results(self, task: "Task", context: "ExecutionContext") -> str:
        """
        Build a markdown block of all prior task outputs that *task* depends on.

        This is the core of Phase 11.5 collaborative intelligence: every
        worker starts from where the previous worker left off rather than
        working in isolation.
        """
        # _prior_results is defined on BaseWorker
        prior = self._prior_results(task, context)  # type: ignore[attr-defined]
        if not prior:
            return ""
        parts: list[str] = ["---\n## Context from prior steps\n"]
        for i, result_text in enumerate(prior, 1):
            snippet = (
                result_text[:_MAX_PRIOR_CHARS] + "\n…[truncated]"
                if len(result_text) > _MAX_PRIOR_CHARS
                else result_text
            )
            parts.append(f"### Step {i}\n{snippet}\n")
        return "\n".join(parts)

    def _fetch_knowledge_context(self, context: "ExecutionContext") -> str:
        """Query the KnowledgeManager for concepts relevant to the goal."""
        km = self._get_knowledge_manager(context)
        if km is None:
            return ""
        try:
            # KnowledgeManager exposes a query engine; try keyword search
            results = km.search(context.goal, max_results=3)
            if not results:
                return ""
            snippets: list[str] = []
            for r in results[:3]:
                text = str(r)[:_MAX_CONTEXT_SNIPPET]
                snippets.append(text)
            return "## Relevant Knowledge\n" + "\n\n".join(snippets)
        except Exception as exc:
            logger.debug("OllamaWorkerMixin: knowledge context unavailable: %s", exc)
            return ""

    def _fetch_memory_context(self, context: "ExecutionContext") -> str:
        """Search MemoryManager for past experiences relevant to the goal."""
        mm = self._get_memory_manager(context)
        if mm is None:
            return ""
        try:
            memories = mm.search(context.goal, limit=3)
            if not memories:
                return ""
            snippets: list[str] = []
            for m in memories[:3]:
                text = str(m)[:_MAX_CONTEXT_SNIPPET]
                snippets.append(text)
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

        Injects:
          1. Prior task outputs (Phase 11.5 collaborative context).
          2. The goal and current task description.
          3. Knowledge and memory context if available.
        """
        sections: list[str] = []

        prior_block = self._format_prior_results(task, context)
        if prior_block:
            sections.append(prior_block)

        sections.append(f"## Goal\n{context.goal}")
        sections.append(
            f"## Current Task\n**{task.title}**\n{task.description or task.title}"
        )

        knowledge_ctx = self._fetch_knowledge_context(context)
        if knowledge_ctx:
            sections.append(knowledge_ctx)

        memory_ctx = self._fetch_memory_context(context)
        if memory_ctx:
            sections.append(memory_ctx)

        return [{"role": "user", "content": "\n\n".join(sections)}]

    # ------------------------------------------------------------------
    # Ollama call
    # ------------------------------------------------------------------

    def _stream_response(
        self,
        context: "ExecutionContext",
        messages: list[dict[str, str]],
    ) -> str | None:
        """
        Call ``ModelManager.chat_stream`` and collect all tokens.

        Returns the joined text, or ``None`` if Ollama is unavailable or
        the response is empty (triggers stub fallback in the caller).
        """
        mm = self._get_model_manager(context)
        if mm is None:
            return None

        model_id = self._resolve_model_id(context)
        full_messages = [
            {"role": "system", "content": self._system_prompt}
        ] + messages

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
        """
        Heuristic confidence score (0.0 – 1.0) based on response quality.

        Signals checked:
          - Word count (more is generally better for substantive tasks).
          - Structural markers (headers, bullet lists, numbered steps).
          - Absence of apology / uncertainty phrases.
        """
        if not text:
            return 0.0

        words = text.split()
        word_count = len(words)

        # Base score from length — saturates at ~400 words → 0.85
        base = min(0.85, word_count / 400 * 0.85)

        # Bonus for structured output
        structure_markers = any(
            marker in text
            for marker in ("##", "**", "1.", "- ", "* ", "\n\n", "```")
        )
        if structure_markers:
            base = min(0.95, base + 0.10)

        # Penalty for uncertainty / failure phrases
        uncertainty = any(
            phrase in text.lower()
            for phrase in ("i cannot", "i am unable", "i don't know", "unavailable")
        )
        if uncertainty:
            base = max(0.0, base - 0.20)

        return round(base, 2)

    # ------------------------------------------------------------------
    # Stub fallback
    # ------------------------------------------------------------------

    def _stub_result(self, task: "Task", context: "ExecutionContext") -> str:
        """
        Return a stub result when Ollama is unavailable.

        Ensures the result contains the worker's name so existing tests
        that check ``assert "Research" in result`` etc. continue to pass.
        """
        worker_name = getattr(self, "name", "Worker")
        return (
            f"[{worker_name}] {task.title}\n"
            f"  Goal: {context.goal}\n"
            f"  (Ollama unavailable — stub result)"
        )

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

        Falls back to ``_stub_result()`` when Ollama is unreachable so all
        existing tests remain green (``isinstance(result, str)`` is True).

        Confidence is stored in ``context.metadata["task_confidence"][task.id]``
        so the Scheduler and Orchestrator can surface it in summaries.

        Returns a plain ``str`` — compatible with the BaseWorker contract and
        all existing scheduler/test expectations.
        """
        messages = self._build_messages(task, context)
        text = self._stream_response(context, messages)

        if text is None:
            text = self._stub_result(task, context)
            confidence = 0.0
        else:
            confidence = self._compute_confidence(text)

        worker_name = getattr(self, "name", "worker")
        logger.debug(
            "OllamaWorkerMixin [%s]: task=%r confidence=%.2f",
            worker_name, task.title, confidence,
        )

        # Store confidence in context.metadata for the execution summary
        if "task_confidence" not in context.metadata:
            context.metadata["task_confidence"] = {}
        context.metadata["task_confidence"][task.id] = confidence

        return text
