"""
ModelManager — Milestone 5, Part 3.

The *only* component allowed to talk to model providers. The Brain,
Skills, and everything else call `ModelManager` — never a `BaseModel`
instance, never a provider module — mirroring how `ToolEngine` is the only
thing that calls a `BaseTool` directly (Part 11).

Responsibilities (Part 3): load/unload/switch models, select a default,
health monitoring, provider discovery, configuration, and statistics.

Design decision — no auto-loaded default model:
    `ModelSettings.default_model_id` defaults to `""` (empty), so a fresh
    `ModelManager` discovers providers (so `MockModelProvider` is
    *registered* and available to load on demand) but does not load any of
    them automatically. `generate()` raises `NoActiveModelError` until a
    caller explicitly `load()`s/`switch()`es to a model. This preserves the
    pre-Milestone-5 Brain behavior exactly (the old `ModelClient.generate()`
    always raised `NotImplementedError`, so the `model` module always fell
    through to the guaranteed-success `unknown` handler) while still giving
    `ModelManager` a fully working provider to load when a test — or a
    future deployment that sets `default_model_id="mock"` on purpose —
    wants real (if deterministic) generation.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

from smartagent.logs.logger import get_logger
from smartagent.models.base.base_model import BaseModel, ModelHealth
from smartagent.models.config.model_settings import ModelSettings
from smartagent.models.context.conversation_context import ConversationContext
from smartagent.models.prompts.prompt_builder import Prompt, PromptBuilder
from smartagent.models.registry.model_registry import ModelRegistry
from smartagent.models.responses.response_parser import ParsedResponse, ResponseParser

logger = get_logger(__name__)


class NoActiveModelError(Exception):
    """Raised when `ModelManager.generate()`/`stream()` is called with no active model loaded."""


class ModelManager:
    """
    Loads, switches between, and generates through model providers.

    Args:
        settings: Configuration (default model, generation params, timeouts).
            Defaults to `ModelSettings()` (no default model auto-loaded).
        registry: Where providers live. Defaults to a fresh `ModelRegistry`.
        response_parser: Normalizes raw provider output. Defaults to a fresh `ResponseParser`.
        prompt_builder: Assembles prompts from messages/context. Defaults to a fresh `PromptBuilder`.
        event_bus: Optional shared `EventBus` to publish model lifecycle events onto (Part 12).
    """

    def __init__(
        self,
        settings: ModelSettings | None = None,
        registry: ModelRegistry | None = None,
        response_parser: ResponseParser | None = None,
        prompt_builder: PromptBuilder | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self.settings = settings or ModelSettings()
        self.registry = registry or ModelRegistry()
        self.response_parser = response_parser or ResponseParser()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.events = event_bus
        self._active_model_id: str | None = None
        self._switch_count = 0

    # ------------------------------------------------------------------
    # Provider discovery
    # ------------------------------------------------------------------

    def discover_providers(self) -> list[str]:
        """Discover and register every built-in provider class. Does not load any of them."""
        discovered = self.registry.discover()
        if discovered:
            logger.info("Discovered %d model provider(s): %s", len(discovered), ", ".join(discovered))
        return discovered

    # ------------------------------------------------------------------
    # Load / unload / switch
    # ------------------------------------------------------------------

    def load(self, model_id: str) -> BaseModel:
        """
        Load (or return the already-loaded) provider registered under `model_id`.

        Raises:
            KeyError: If `model_id` is not registered.
        """
        model = self.registry.find(model_id)
        if model is None:
            raise KeyError(f"No model provider registered with id {model_id!r}.")
        if model.status().value != "loaded":
            model.load()
            self._publish("MODEL_LOADED", model_id=model_id, provider=model.provider)
        logger.info("Model loaded: %s (%s)", model_id, model.provider)
        return model

    def unload(self, model_id: str) -> bool:
        """
        Unload the provider registered under `model_id`, if currently loaded.

        Returns:
            `True` if a loaded model was found and unloaded, `False` otherwise.
        """
        model = self.registry.find(model_id)
        if model is None:
            return False
        model.shutdown()
        if self._active_model_id == model_id:
            self._active_model_id = None
        self._publish("MODEL_UNLOADED", model_id=model_id)
        logger.info("Model unloaded: %s", model_id)
        return True

    def switch(self, model_id: str) -> BaseModel:
        """
        Load `model_id` (if needed) and make it the active default for `generate()`/`stream()`.

        When ``settings.lazy_model_loading`` is ``True``, the previously
        active model is unloaded after the new one is ready — keeping only
        one model resident at a time (Milestone 10).

        Raises:
            KeyError: If `model_id` is not registered.
        """
        previous = self._active_model_id
        model = self.load(model_id)
        self._active_model_id = model_id
        self._switch_count += 1

        # Lazy loading: unload the previous model to free resources.
        if (
            getattr(self.settings, "lazy_model_loading", False)
            and previous is not None
            and previous != model_id
        ):
            prev_model = self.registry.find(previous)
            if prev_model is not None and prev_model.status().value == "loaded":
                prev_model.shutdown()
                logger.info("Lazy loading: unloaded previous model %s", previous)

        self._publish("MODEL_SWITCHED", from_model=previous, to_model=model_id)
        logger.info("Model switched: %s -> %s", previous, model_id)
        return model

    def select_default(self) -> str | None:
        """
        Resolve the id of the model that should be used when no explicit id is given.

        Prefers the currently active model (set via `switch()`), then falls
        back to `settings.default_model_id` if it names a registered model,
        else `None` — meaning "no default configured", which is the
        Milestone 5 out-of-the-box state (see module docstring).
        """
        if self._active_model_id is not None:
            return self._active_model_id
        if self.settings.default_model_id and self.registry.find(self.settings.default_model_id) is not None:
            return self.settings.default_model_id
        return None

    @property
    def active_model_id(self) -> str | None:
        """Id of the currently active model, or `None` if none has been loaded/switched to."""
        return self._active_model_id

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: "str | Prompt",
        model_id: str | None = None,
        context: ConversationContext | None = None,
        **overrides: Any,
    ) -> ParsedResponse:
        """
        Generate a response using the active (or explicitly given) model.

        Args:
            prompt: Either a raw string or an assembled `Prompt` (from
                `PromptBuilder`). A raw string is rendered as-is; a `Prompt`
                is flattened via `Prompt.render()` before being handed to
                the provider — providers see plain text, never a `Prompt` object.
            model_id: Explicit model to use. Defaults to `select_default()`.
            context: Optional `ConversationContext`, appended to with the
                new turn and its response so callers don't have to do that bookkeeping.
            **overrides: Per-call overrides merged over `settings.generation_kwargs()`.

        Raises:
            NoActiveModelError: If no model was given/switched-to and no
                default is configured (the out-of-the-box Milestone 5 state).

        Returns:
            A `ParsedResponse`. Never raises for provider-level failures —
            those surface as `ParsedResponse.metadata["error"]` instead, so
            Brain integration only needs one exception to handle (this one).
        """
        resolved_id = model_id or self.select_default()
        if resolved_id is None:
            raise NoActiveModelError(
                "No model is currently loaded and no default_model_id is configured. "
                "Call ModelManager.load()/switch() with a registered model id first."
            )
        model = self.load(resolved_id)

        rendered = prompt.render() if isinstance(prompt, Prompt) else prompt
        prompt_size = len(rendered)
        context_size = context.token_estimate() if context is not None else 0
        logger.info(
            "Generating with model=%s prompt_size=%d context_size=%d",
            resolved_id,
            prompt_size,
            context_size,
        )

        kwargs = {**self.settings.generation_kwargs(), **overrides}
        start = time.monotonic()
        try:
            raw = model.generate(rendered, **kwargs)
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 — a failing provider must not crash the caller
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("Model generation failed: model=%s error=%s", resolved_id, exc)
            return ParsedResponse(
                text="",
                confidence=0.0,
                metadata={"error": str(exc)},
                timing_ms=elapsed_ms,
                provider=model.provider,
            )
        elapsed_ms = (time.monotonic() - start) * 1000

        parsed = self.response_parser.parse(raw, provider=model.provider, timing_ms=elapsed_ms)
        self.registry.record_generation(resolved_id)
        logger.info("Model response: model=%s response_time=%.2fms error=%s", resolved_id, elapsed_ms, error)

        if context is not None:
            user_text = prompt.user_message if isinstance(prompt, Prompt) else rendered
            context.add_turn("user", user_text)
            context.add_turn("assistant", parsed.text)

        return parsed

    def stream(
        self,
        prompt: "str | Prompt",
        model_id: str | None = None,
        **overrides: Any,
    ) -> Iterator[str]:
        """
        Stream a response using the active (or explicitly given) model.

        Raises:
            NoActiveModelError: Same condition as `generate()`.
        """
        resolved_id = model_id or self.select_default()
        if resolved_id is None:
            raise NoActiveModelError(
                "No model is currently loaded and no default_model_id is configured. "
                "Call ModelManager.load()/switch() with a registered model id first."
            )
        model = self.load(resolved_id)
        rendered = prompt.render() if isinstance(prompt, Prompt) else prompt
        kwargs = {**self.settings.generation_kwargs(), **overrides}
        yield from model.stream(rendered, **kwargs)

    def generate_stream(
        self,
        prompt: "str | Prompt",
        model_id: str | None = None,
        **overrides: Any,
    ) -> Iterator[str]:
        """
        Stream a response for *prompt*, yielding tokens as they arrive.

        Delegates to the active (or explicitly given) model's
        ``generate_stream()`` method.  Use this instead of ``stream()``
        for new code — it is the preferred streaming entry point as of
        Milestone 10.

        Raises:
            NoActiveModelError: Same condition as ``generate()``.
        """
        resolved_id = model_id or self.select_default()
        if resolved_id is None:
            raise NoActiveModelError(
                "No model is currently loaded and no default_model_id is configured. "
                "Call ModelManager.load()/switch() with a registered model id first."
            )
        model = self.load(resolved_id)
        rendered = prompt.render() if isinstance(prompt, Prompt) else prompt
        kwargs = {**self.settings.generation_kwargs(), **overrides}
        yield from model.generate_stream(rendered, **kwargs)

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        model_id: str | None = None,
        **overrides: Any,
    ) -> Iterator[str]:
        """
        Stream a response for a chat-style *messages* list, yielding tokens
        as they arrive.

        Delegates to the active (or explicitly given) model's
        ``chat_stream()`` method.  Providers with native chat-streaming
        (e.g. ``OllamaProvider``) will use the message list directly;
        providers without it fall back to flattening via ``BaseModel``'s
        default implementation.

        Raises:
            NoActiveModelError: Same condition as ``generate()``.
        """
        resolved_id = model_id or self.select_default()
        if resolved_id is None:
            raise NoActiveModelError(
                "No model is currently loaded and no default_model_id is configured. "
                "Call ModelManager.load()/switch() with a registered model id first."
            )
        model = self.load(resolved_id)
        kwargs = {**self.settings.generation_kwargs(), **overrides}
        yield from model.chat_stream(messages, **kwargs)

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model_id: str | None = None,
        **overrides: Any,
    ) -> Any:
        """
        Non-streaming chat call with tool/function-calling definitions.

        Delegates to the active model's ``chat_with_tools()`` method.  Only
        providers that implement the method (e.g. ``GitHubProvider``) support
        this; calling it against a provider that doesn't will raise
        ``AttributeError``.

        Returns the raw provider message object so callers can inspect
        ``.tool_calls`` and ``.content`` directly.

        Raises:
            NoActiveModelError: Same condition as ``generate()``.
        """
        resolved_id = model_id or self.select_default()
        if resolved_id is None:
            raise NoActiveModelError(
                "No model is currently loaded and no default_model_id is configured. "
                "Call ModelManager.load()/switch() with a registered model id first."
            )
        model = self.load(resolved_id)
        if not hasattr(model, "chat_with_tools"):
            raise AttributeError(
                f"Provider {model.provider!r} (model {resolved_id!r}) does not support "
                "tool/function calling.  Switch to a provider that implements "
                "chat_with_tools() (e.g. GitHub Models or OpenAI)."
            )
        return model.chat_with_tools(messages, tools, **overrides)

    # ------------------------------------------------------------------
    # Health / statistics
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Delegate to `ModelRegistry.health_check()`."""
        report = self.registry.health_check()
        self._publish("MODEL_HEALTH_CHECKED", healthy=report.get("healthy", False))
        return report

    def health(self, model_id: str) -> ModelHealth | None:
        """Health snapshot for a single model, or `None` if not registered."""
        model = self.registry.find(model_id)
        return model.health() if model is not None else None

    def statistics(self) -> dict[str, Any]:
        """Registry-level statistics plus manager-level state (active model, switch count)."""
        stats = self.registry.statistics()
        stats["active_model_id"] = self._active_model_id
        stats["switch_count"] = self._switch_count
        return stats

    def list_available(self) -> list[str]:
        """Ids of every registered model, enabled or not."""
        return self.registry.list_available()

    # ------------------------------------------------------------------
    # Milestone 9 — Ollama integration helpers
    # ------------------------------------------------------------------

    def list_models(self) -> list[BaseModel]:
        """All registered model provider instances (enabled or not)."""
        return self.registry.list(enabled_only=False)

    def load_model(self, model_id: str) -> BaseModel:
        """Alias for ``load()`` — provided for spec-mandated API surface."""
        return self.load(model_id)

    def unload_model(self, model_id: str) -> bool:
        """Alias for ``unload()`` — provided for spec-mandated API surface."""
        return self.unload(model_id)

    def switch_model(self, model_id: str) -> BaseModel:
        """Alias for ``switch()`` — provided for spec-mandated API surface."""
        return self.switch(model_id)

    def active_model(self) -> BaseModel | None:
        """
        Return the currently active ``BaseModel`` instance, or ``None``.

        Complements ``active_model_id`` (the id string) with the live object.
        """
        if self._active_model_id is None:
            return None
        return self.registry.find(self._active_model_id)

    def load_ollama_models(
        self,
        base_url: str = "http://127.0.0.1:11434",
        default_model: str = "llama3.1:8b",
        coding_model: str = "qwen2.5-coder:7b",
    ) -> list[str]:
        """
        Create and register ``OllamaProvider`` instances for the configured models.

        Always registers the default and coding models (so ``model use <name>``
        works even if Ollama is currently offline).  Also discovers and registers
        any additional models installed on the running Ollama server.

        Returns the list of newly registered model ids.
        """
        # Lazy import to keep ModelManager free of a hard dependency on a
        # concrete provider — mirrors the pattern used by _publish() for EventBus.
        from smartagent.models.providers.ollama_provider import (
            OllamaModelDiscovery,
            OllamaProvider,
        )

        registered: list[str] = []
        warmup = getattr(self.settings, "warmup_enabled", False)

        # Always register the two configured models.
        for model_name in dict.fromkeys([default_model, coding_model]):  # preserve order, deduplicate
            if self.registry.find(model_name) is None:
                provider = OllamaProvider(
                    model_name=model_name,
                    base_url=base_url,
                    warmup_enabled=warmup,
                )
                self.registry.register(provider)
                registered.append(model_name)
                logger.info("Registered Ollama model: %s", model_name)

        # Discover additional installed models from the running server.
        try:
            discovery = OllamaModelDiscovery(base_url=base_url)
            for info in discovery.list_models(timeout=3.0):
                if self.registry.find(info.name) is None:
                    provider = OllamaProvider(
                        model_name=info.name,
                        base_url=base_url,
                        warmup_enabled=warmup,
                    )
                    self.registry.register(provider)
                    registered.append(info.name)
                    logger.info("Registered discovered Ollama model: %s", info.name)
        except Exception:  # noqa: BLE001
            pass  # Ollama offline at startup — providers still registered as UNLOADED

        return registered

    def load_github_models(
        self,
        default_model: str = "gpt-4.1-mini",
        coding_model: str = "gpt-4.1",
        fallback_model: str = "gpt-4o-mini",
        token: str | None = None,
    ) -> list[str]:
        """
        Create and register ``GitHubProvider`` instances for the configured models.

        Silently no-ops when ``GITHUB_TOKEN`` is not set (so tests without the
        env var continue to pass unchanged).

        Returns the list of newly registered model ids.
        """
        import os
        resolved_token = token or os.environ.get("GITHUB_TOKEN", "")
        if not resolved_token:
            logger.debug("load_github_models: GITHUB_TOKEN not set — skipping")
            return []

        try:
            from smartagent.llm.github_provider import GitHubProvider
        except ImportError:
            logger.warning("load_github_models: smartagent.llm not available")
            return []

        registered: list[str] = []
        for model_name in dict.fromkeys([default_model, coding_model, fallback_model]):
            if self.registry.find(model_name) is None:
                provider = GitHubProvider(model_name=model_name, token=resolved_token)
                self.registry.register(provider)
                registered.append(model_name)
                logger.info("Registered GitHub model: %s", model_name)
        return registered

    def describe(self) -> str:
        """One-line human-readable summary, mirroring `ToolEngine.describe()`."""
        available = self.list_available()
        if not available:
            return "No model providers are currently registered."
        active = self._active_model_id or "none"
        return f"{len(available)} model provider(s) available: {', '.join(available)}. Active model: {active}."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish(self, event_name: str, **payload: Any) -> None:
        if self.events is None:
            return
        # Imported lazily to avoid a hard dependency on smartagent.brain at
        # module import time — ModelManager must stay usable standalone
        # (e.g. in tests that never construct a SmartAgent/EventBus).
        from smartagent.brain.events import Events

        resolved_name = getattr(Events, event_name, event_name)
        self.events.publish(resolved_name, **payload)
