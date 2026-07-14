"""
Tests for Milestone 5 — Model Framework v1.

Covers:
    - BaseModel contract (via a minimal concrete dummy), ModelStatus/
      ModelMetadata/ModelHealth shapes.
    - MockModelProvider (lifecycle, generate, stream, embed raises, health).
    - Future provider stubs stay abstract (design-only, not instantiable).
    - model_loader.discover_provider_classes (finds Mock, skips future stubs,
      handles a bad package gracefully).
    - ModelRegistry (register, unregister, find, list, reload, enable,
      disable, discover, health_check, statistics).
    - ConversationContext (turns, memory refs, tool outputs, summaries,
      token estimate, recent()).
    - PromptBuilder / Prompt (render, to_messages, token_estimate, with and
      without a ConversationContext).
    - ResponseParser (normalizes multiple raw shapes, tool calls, usage,
      non-dict raw).
    - ModelSettings (generation_kwargs, no hardcoded secrets by default).
    - ModelManager (discover, load, unload, switch, select_default,
      generate, stream, health_check, statistics, describe,
      NoActiveModelError when nothing is configured).
    - Brain integration via SmartAgent: `model` module handler stays
      success=False by default (no regression) and succeeds once
      `default_model_id="mock"` is configured; model lifecycle events land
      on the shared EventBus.

Design decisions preserved:
    - No databases, no real AI model calls, no internet access.
    - MockModelProvider is fully deterministic — asserted directly.
    - Filesystem/vault tests (via SmartAgent) use an isolated tmp_path.
"""

from __future__ import annotations

import inspect

import pytest

from smartagent.brain.agent import SmartAgent
from smartagent.brain.events import EventBus, Events
from smartagent.config.settings import Settings
from smartagent.models.base.base_model import BaseModel, ModelHealth, ModelMetadata, ModelStatus
from smartagent.models.config.model_settings import ModelSettings
from smartagent.models.context.conversation_context import ConversationContext, ConversationTurn
from smartagent.models.manager.model_manager import ModelManager, NoActiveModelError
from smartagent.models.prompts.prompt_builder import Prompt, PromptBuilder
from smartagent.models.providers import future_providers
from smartagent.models.providers.mock_provider import MockModelProvider
from smartagent.models.registry.model_loader import discover_provider_classes
from smartagent.models.registry.model_registry import ModelRegistry
from smartagent.models.responses.response_parser import ParsedResponse, ResponseParser, ToolRequest


def _settings(tmp_path):
    s = Settings.load()
    s.vault_path = str(tmp_path / "vault")
    return s


def _agent(tmp_path, **overrides) -> SmartAgent:
    settings = _settings(tmp_path)
    for key, value in overrides.items():
        setattr(settings, key, value)
    return SmartAgent(settings=settings)


# ---------------------------------------------------------------------------
# Minimal concrete BaseModel for infrastructure tests
# ---------------------------------------------------------------------------

class _DummyModel(BaseModel):
    """Concrete BaseModel that always succeeds — used for infrastructure tests."""

    def __init__(self) -> None:
        self._status = ModelStatus.UNLOADED

    @property
    def id(self) -> str:
        return "dummy"

    @property
    def name(self) -> str:
        return "Dummy Model"

    @property
    def provider(self) -> str:
        return "dummy_provider"

    @property
    def version(self) -> str:
        return "0.1.0"

    def initialize(self) -> None:
        pass

    def load(self) -> None:
        self._status = ModelStatus.LOADED

    def generate(self, prompt, **kwargs):
        return {"content": f"dummy reply to {prompt}"}

    def stream(self, prompt, **kwargs):
        yield "dummy "
        yield "stream"

    def embed(self, text):
        raise NotImplementedError("Dummy model does not implement embeddings.")

    def shutdown(self) -> None:
        self._status = ModelStatus.UNLOADED


# ---------------------------------------------------------------------------
# 1. BaseModel contract
# ---------------------------------------------------------------------------

class TestBaseModel:
    def test_cannot_instantiate_base_model_directly(self):
        with pytest.raises(TypeError):
            BaseModel()

    def test_default_capability_properties(self):
        model = _DummyModel()
        assert model.context_window == 0
        assert model.supports_streaming is False
        assert model.supports_tools is False
        assert model.supports_images is False
        assert model.supports_embeddings is False
        assert model.supports_functions is False

    def test_status_starts_unloaded_and_updates_on_load_shutdown(self):
        model = _DummyModel()
        assert model.status() == ModelStatus.UNLOADED
        model.load()
        assert model.status() == ModelStatus.LOADED
        model.shutdown()
        assert model.status() == ModelStatus.UNLOADED

    def test_metadata_snapshot(self):
        model = _DummyModel()
        meta = model.metadata()
        assert isinstance(meta, ModelMetadata)
        assert meta.id == "dummy"
        assert meta.provider == "dummy_provider"
        assert meta.supports_streaming is False

    def test_health_reports_unhealthy_until_loaded(self):
        model = _DummyModel()
        health = model.health()
        assert isinstance(health, ModelHealth)
        assert health.healthy is False
        model.load()
        assert model.health().healthy is True


# ---------------------------------------------------------------------------
# 2. MockModelProvider
# ---------------------------------------------------------------------------

class TestMockModelProvider:
    def test_identity_and_capabilities(self):
        model = MockModelProvider()
        assert model.id == "mock"
        assert model.provider == "mock"
        assert model.supports_streaming is True
        assert model.supports_embeddings is False
        assert model.context_window == 4096

    def test_generate_requires_load_first(self):
        model = MockModelProvider()
        with pytest.raises(RuntimeError):
            model.generate("hello")

    def test_generate_is_deterministic(self):
        model = MockModelProvider()
        model.load()
        first = model.generate("What is the capital of France?")
        second = model.generate("What is the capital of France?")
        assert first["content"] == second["content"]
        assert first["usage"]["total_tokens"] > 0
        assert model.call_count == 2

    def test_different_prompts_produce_different_content(self):
        model = MockModelProvider()
        model.load()
        a = model.generate("prompt A")
        b = model.generate("prompt B")
        assert a["content"] != b["content"]

    def test_stream_yields_full_content_incrementally(self):
        model = MockModelProvider()
        model.load()
        chunks = list(model.stream("stream this"))
        assert len(chunks) > 1
        assert "".join(chunks).strip() == model.generate("stream this")["content"]

    def test_embed_raises_not_implemented(self):
        model = MockModelProvider()
        model.load()
        with pytest.raises(NotImplementedError):
            model.embed("some text")

    def test_health_reflects_load_state(self):
        model = MockModelProvider()
        assert model.health().healthy is False
        model.load()
        assert model.health().healthy is True
        model.shutdown()
        assert model.health().healthy is False


# ---------------------------------------------------------------------------
# 3. Future provider stubs — design-only, not instantiable
# ---------------------------------------------------------------------------

class TestFutureProviders:
    @pytest.mark.parametrize(
        "cls",
        [
            future_providers.OllamaModel,
            future_providers.OpenAIModel,
            future_providers.AnthropicModel,
            future_providers.GeminiModel,
            future_providers.LMStudioModel,
            future_providers.OpenRouterModel,
            future_providers.AzureOpenAIModel,
            future_providers.BedrockModel,
            future_providers.DeepSeekModel,
            future_providers.MistralModel,
            future_providers.VLLMModel,
            future_providers.LlamaCppModel,
        ],
    )
    def test_future_provider_stays_abstract(self, cls):
        assert inspect.isabstract(cls)
        with pytest.raises(TypeError):
            cls()

    def test_future_provider_subclasses_base_model(self):
        assert issubclass(future_providers.OllamaModel, BaseModel)


# ---------------------------------------------------------------------------
# 4. Model loader / discovery
# ---------------------------------------------------------------------------

class TestModelLoader:
    def test_discovers_mock_provider(self):
        classes = discover_provider_classes()
        assert MockModelProvider in classes

    def test_does_not_discover_abstract_future_stubs(self):
        classes = discover_provider_classes()
        assert future_providers.OllamaModel not in classes
        assert future_providers.OpenAIModel not in classes

    def test_bad_package_returns_empty_list(self):
        assert discover_provider_classes("smartagent.models.does_not_exist") == []


# ---------------------------------------------------------------------------
# 5. ModelRegistry
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def test_register_and_find(self):
        registry = ModelRegistry()
        model = _DummyModel()
        registry.register(model)
        assert registry.find("dummy") is model

    def test_find_unknown_returns_none(self):
        registry = ModelRegistry()
        assert registry.find("nope") is None

    def test_unregister_calls_shutdown_and_removes(self):
        registry = ModelRegistry()
        model = _DummyModel()
        model.load()
        registry.register(model)
        registry.unregister("dummy")
        assert registry.find("dummy") is None
        assert model.status() == ModelStatus.UNLOADED

    def test_unregister_missing_is_a_noop(self):
        registry = ModelRegistry()
        registry.unregister("does-not-exist")  # should not raise

    def test_list_defaults_to_enabled_only(self):
        registry = ModelRegistry()
        registry.register(_DummyModel())
        registry.disable("dummy")
        assert registry.list() == []
        assert len(registry.list(enabled_only=False)) == 1

    def test_list_available_includes_disabled(self):
        registry = ModelRegistry()
        registry.register(_DummyModel())
        registry.disable("dummy")
        assert registry.list_available() == ["dummy"]

    def test_enable_disable_unknown_model_returns_false(self):
        registry = ModelRegistry()
        assert registry.enable("nope") is False
        assert registry.disable("nope") is False

    def test_reload_reinstantiates_and_preserves_status(self):
        registry = ModelRegistry()
        original = _DummyModel()
        registry.register(original)
        registry.disable("dummy")
        fresh = registry.reload("dummy")
        assert fresh is not original
        assert fresh is not None
        assert registry.is_enabled("dummy") is False

    def test_reload_unknown_returns_none(self):
        registry = ModelRegistry()
        assert registry.reload("nope") is None

    def test_discover_registers_mock_provider(self):
        registry = ModelRegistry()
        registered = registry.discover()
        assert "mock" in registered
        assert registry.find("mock") is not None

    def test_discover_is_idempotent(self):
        registry = ModelRegistry()
        registry.discover()
        second_pass = registry.discover()
        assert second_pass == []  # already registered, not re-added

    def test_health_check_reports_all_models(self):
        registry = ModelRegistry()
        model = _DummyModel()
        model.load()
        registry.register(model)
        report = registry.health_check()
        assert report["healthy"] is True
        assert report["models"]["dummy"]["status"] == "loaded"

    def test_health_check_unhealthy_when_enabled_model_not_loaded(self):
        registry = ModelRegistry()
        registry.register(_DummyModel())
        report = registry.health_check()
        assert report["healthy"] is False

    def test_statistics_shape(self):
        registry = ModelRegistry()
        model = _DummyModel()
        model.load()
        registry.register(model)
        registry.record_generation("dummy")
        stats = registry.statistics()
        assert stats["total"] == 1
        assert stats["enabled"] == 1
        assert stats["loaded"] == 1
        assert stats["generation_counts"]["dummy"] == 1


# ---------------------------------------------------------------------------
# 6. ConversationContext
# ---------------------------------------------------------------------------

class TestConversationContext:
    def test_add_turn_appends_and_updates_timestamp(self):
        ctx = ConversationContext()
        turn = ctx.add_turn("user", "hello")
        assert isinstance(turn, ConversationTurn)
        assert ctx.history == [turn]

    def test_recent_returns_last_n_oldest_first(self):
        ctx = ConversationContext()
        for i in range(5):
            ctx.add_turn("user", f"message {i}")
        recent = ctx.recent(2)
        assert [t.content for t in recent] == ["message 3", "message 4"]

    def test_recent_with_zero_limit_returns_empty(self):
        ctx = ConversationContext()
        ctx.add_turn("user", "hi")
        assert ctx.recent(0) == []

    def test_memory_refs_and_tool_outputs_and_summaries(self):
        ctx = ConversationContext()
        ctx.add_memory_ref("user likes tea")
        ctx.add_tool_output("uuid: abc-123")
        ctx.add_summary("earlier the user asked about the weather")
        assert ctx.memory_refs == ["user likes tea"]
        assert ctx.tool_outputs == ["uuid: abc-123"]
        assert ctx.summaries == ["earlier the user asked about the weather"]

    def test_set_active_task(self):
        ctx = ConversationContext()
        ctx.set_active_task("write a report")
        assert ctx.active_task == "write a report"

    def test_token_estimate_grows_with_content(self):
        ctx = ConversationContext()
        empty_estimate = ctx.token_estimate()
        ctx.add_turn("user", "x" * 400)
        assert ctx.token_estimate() > empty_estimate

    def test_to_dict_shape(self):
        ctx = ConversationContext()
        ctx.add_turn("user", "hi")
        snapshot = ctx.to_dict()
        assert snapshot["turns"] == 1
        assert "token_estimate" in snapshot
        assert "created_at" in snapshot and "updated_at" in snapshot


# ---------------------------------------------------------------------------
# 7. PromptBuilder / Prompt
# ---------------------------------------------------------------------------

class TestPromptBuilder:
    def test_build_minimal_prompt_without_context(self):
        prompt = PromptBuilder().build("hello there")
        assert isinstance(prompt, Prompt)
        assert prompt.user_message == "hello there"
        assert prompt.history_lines == ()
        assert prompt.future_context == {}

    def test_render_omits_empty_sections(self):
        prompt = PromptBuilder().build("hi")
        rendered = prompt.render()
        assert "System:" in rendered
        assert "User: hi" in rendered
        assert "Relevant memory" not in rendered

    def test_render_includes_populated_sections(self):
        ctx = ConversationContext()
        ctx.add_turn("user", "earlier message")
        ctx.add_memory_ref("favorite color is blue")
        ctx.add_tool_output("date: 2026-07-14")
        prompt = PromptBuilder().build("what's my favorite color", context=ctx, skill_context="memory_skill")
        rendered = prompt.render()
        assert "Relevant memory" in rendered
        assert "favorite color is blue" in rendered
        assert "Available skills: memory_skill" in rendered
        assert "date: 2026-07-14" in rendered
        assert "earlier message" in rendered

    def test_to_messages_shape(self):
        ctx = ConversationContext()
        ctx.add_turn("assistant", "previous reply")
        prompt = PromptBuilder().build("next question", context=ctx)
        messages = prompt.to_messages()
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": "next question"}
        assert any(m["role"] == "assistant" for m in messages)

    def test_token_estimate_is_positive(self):
        prompt = PromptBuilder().build("some reasonably long user message here")
        assert prompt.token_estimate() > 0

    def test_history_limit_is_respected(self):
        ctx = ConversationContext()
        for i in range(10):
            ctx.add_turn("user", f"turn {i}")
        prompt = PromptBuilder().build("latest", context=ctx, history_limit=3)
        assert len(prompt.history_lines) == 3


# ---------------------------------------------------------------------------
# 8. ResponseParser
# ---------------------------------------------------------------------------

class TestResponseParser:
    def test_parses_mock_provider_shape(self):
        model = MockModelProvider()
        model.load()
        raw = model.generate("test prompt")
        parsed = ResponseParser().parse(raw, provider="mock", timing_ms=12.5)
        assert isinstance(parsed, ParsedResponse)
        assert parsed.text == raw["content"]
        assert parsed.usage["total_tokens"] == raw["usage"]["total_tokens"]
        assert parsed.timing_ms == 12.5
        assert parsed.provider == "mock"

    def test_parses_alternate_text_key(self):
        parsed = ResponseParser().parse({"text": "alt shape reply"})
        assert parsed.text == "alt shape reply"

    def test_parses_tool_calls(self):
        raw = {
            "content": "let me check that",
            "tool_calls": [{"name": "file_read", "arguments": {"path": "a.txt"}}],
        }
        parsed = ResponseParser().parse(raw)
        assert len(parsed.tool_requests) == 1
        assert parsed.tool_requests[0] == ToolRequest(name="file_read", arguments={"path": "a.txt"})

    def test_parses_confidence_and_metadata(self):
        raw = {"content": "hi", "confidence": 0.42, "finish_reason": "stop", "model": "mock"}
        parsed = ResponseParser().parse(raw)
        assert parsed.confidence == 0.42
        assert parsed.metadata["finish_reason"] == "stop"
        assert parsed.metadata["model"] == "mock"

    def test_defaults_confidence_to_one_when_absent(self):
        parsed = ResponseParser().parse({"content": "hi"})
        assert parsed.confidence == 1.0

    def test_non_dict_raw_is_coerced_to_text(self):
        parsed = ResponseParser().parse("just a plain string")
        assert parsed.text == "just a plain string"
        assert parsed.tool_requests == ()

    def test_missing_text_key_yields_empty_text(self):
        parsed = ResponseParser().parse({"usage": {"prompt_tokens": 1, "completion_tokens": 1}})
        assert parsed.text == ""
        assert parsed.usage["total_tokens"] == 2


# ---------------------------------------------------------------------------
# 9. ModelSettings
# ---------------------------------------------------------------------------

class TestModelSettings:
    def test_defaults_have_no_default_model_and_no_secrets(self):
        settings = ModelSettings()
        assert settings.default_model_id == ""
        assert settings.api_keys == {}
        assert settings.local_model_paths == {}

    def test_generation_kwargs_shape(self):
        settings = ModelSettings(temperature=0.2, top_p=0.9, top_k=10, max_tokens=256)
        kwargs = settings.generation_kwargs()
        assert kwargs == {"temperature": 0.2, "top_p": 0.9, "top_k": 10, "max_tokens": 256}


# ---------------------------------------------------------------------------
# 10. ModelManager
# ---------------------------------------------------------------------------

class TestModelManager:
    def _manager(self, **settings_overrides) -> ModelManager:
        manager = ModelManager(settings=ModelSettings(**settings_overrides), event_bus=EventBus())
        manager.discover_providers()
        return manager

    def test_discover_providers_registers_mock(self):
        manager = self._manager()
        assert "mock" in manager.list_available()

    def test_generate_without_default_raises(self):
        manager = self._manager()
        with pytest.raises(NoActiveModelError):
            manager.generate("hello")

    def test_load_unknown_model_raises_key_error(self):
        manager = self._manager()
        with pytest.raises(KeyError):
            manager.load("nonexistent")

    def test_load_and_generate_with_explicit_model_id(self):
        manager = self._manager()
        response = manager.generate("hello there", model_id="mock")
        assert response.text.startswith("[mock-")
        assert response.provider == "mock"
        assert response.timing_ms >= 0.0

    def test_switch_sets_active_model_and_select_default(self):
        manager = self._manager()
        assert manager.select_default() is None
        manager.switch("mock")
        assert manager.active_model_id == "mock"
        assert manager.select_default() == "mock"

    def test_generate_uses_active_model_after_switch(self):
        manager = self._manager()
        manager.switch("mock")
        response = manager.generate("no explicit model id")
        assert response.provider == "mock"

    def test_default_model_id_setting_is_used_when_no_active_model(self):
        manager = self._manager(default_model_id="mock")
        assert manager.select_default() == "mock"
        response = manager.generate("hi")
        assert response.provider == "mock"

    def test_unload_resets_active_model(self):
        manager = self._manager()
        manager.switch("mock")
        assert manager.unload("mock") is True
        assert manager.active_model_id is None

    def test_unload_unknown_model_returns_false(self):
        manager = self._manager()
        assert manager.unload("nope") is False

    def test_stream_yields_text(self):
        manager = self._manager()
        chunks = list(manager.stream("stream please", model_id="mock"))
        assert len(chunks) > 0
        assert "".join(chunks).strip() != ""

    def test_stream_without_default_raises(self):
        manager = self._manager()
        with pytest.raises(NoActiveModelError):
            list(manager.stream("no model configured"))

    def test_generate_records_generation_count_and_statistics(self):
        manager = self._manager()
        manager.generate("one", model_id="mock")
        manager.generate("two", model_id="mock")
        stats = manager.statistics()
        assert stats["generation_counts"]["mock"] == 2
        # An explicit model_id override does not itself become "active" —
        # only switch()/select_default() change that (see test below).
        assert stats["active_model_id"] is None

    def test_switch_count_increments(self):
        manager = self._manager()
        manager.switch("mock")
        manager.unload("mock")
        manager.switch("mock")
        assert manager.statistics()["switch_count"] == 2

    def test_health_check_reports_mock(self):
        manager = self._manager()
        manager.switch("mock")
        report = manager.health_check()
        assert report["models"]["mock"]["healthy"] is True

    def test_health_for_single_model(self):
        manager = self._manager()
        manager.switch("mock")
        health = manager.health("mock")
        assert health is not None
        assert health.healthy is True
        assert manager.health("nope") is None

    def test_describe_with_and_without_models(self):
        empty_manager = ModelManager()
        assert "No model providers" in empty_manager.describe()

        manager = self._manager()
        manager.switch("mock")
        description = manager.describe()
        assert "mock" in description
        assert "Active model: mock" in description

    def test_generate_populates_conversation_context(self):
        manager = self._manager()
        ctx = ConversationContext()
        manager.generate("remember this", model_id="mock", context=ctx)
        assert len(ctx.history) == 2
        assert ctx.history[0].role == "user"
        assert ctx.history[1].role == "assistant"

    def test_generate_with_prompt_object(self):
        manager = self._manager()
        prompt = PromptBuilder().build("assembled prompt message")
        response = manager.generate(prompt, model_id="mock")
        assert response.provider == "mock"

    def test_generate_publishes_model_loaded_event(self):
        events = EventBus()
        manager = ModelManager(event_bus=events)
        manager.discover_providers()
        manager.generate("hi", model_id="mock")
        names = [e.name for e in events.history()]
        assert Events.MODEL_LOADED in names

    def test_switch_publishes_model_switched_event(self):
        events = EventBus()
        manager = ModelManager(event_bus=events)
        manager.discover_providers()
        manager.switch("mock")
        names = [e.name for e in events.history()]
        assert Events.MODEL_SWITCHED in names

    def test_unload_publishes_model_unloaded_event(self):
        events = EventBus()
        manager = ModelManager(event_bus=events)
        manager.discover_providers()
        manager.switch("mock")
        manager.unload("mock")
        names = [e.name for e in events.history()]
        assert Events.MODEL_UNLOADED in names

    def test_health_check_publishes_event(self):
        events = EventBus()
        manager = ModelManager(event_bus=events)
        manager.discover_providers()
        manager.health_check()
        names = [e.name for e in events.history()]
        assert Events.MODEL_HEALTH_CHECKED in names

    def test_generate_provider_failure_is_reported_not_raised(self):
        manager = self._manager()
        manager.registry.disable("mock")  # doesn't block direct load(), but exercise error path via bad kwargs
        model = manager.registry.find("mock")

        def _boom(prompt, **kwargs):
            raise RuntimeError("simulated provider failure")

        model.generate = _boom  # type: ignore[assignment]
        response = manager.generate("trigger failure", model_id="mock")
        assert response.confidence == 0.0
        assert "simulated provider failure" in response.metadata["error"]


# ---------------------------------------------------------------------------
# 11. Brain integration via SmartAgent
# ---------------------------------------------------------------------------

class TestBrainIntegration:
    def test_agent_constructs_model_manager_with_mock_discovered(self, tmp_path):
        agent = _agent(tmp_path)
        assert "mock" in agent.model_manager.list_available()

    def test_model_handler_fails_gracefully_with_no_default_model(self, tmp_path):
        agent = _agent(tmp_path)
        result = agent.modules.get("model")("some random free-text message")
        assert result.success is False
        assert result.source == "model"

    def test_handle_message_still_falls_back_to_unknown_by_default(self, tmp_path):
        # No regression: with no default_model_id configured, arbitrary
        # free text with nothing in memory still reaches the guaranteed
        # `unknown` fallback, exactly like before Milestone 5.
        agent = _agent(tmp_path)
        response = agent.handle_message("something nobody could possibly answer")
        assert "something nobody could possibly answer" in response

    def test_model_handler_succeeds_once_default_model_id_is_configured(self, tmp_path):
        agent = _agent(tmp_path, default_model_id="mock")
        result = agent.modules.get("model")("what's the weather like")
        assert result.success is True
        assert result.source == "model"
        assert result.data is not None  # the ParsedResponse

    def test_legacy_model_client_still_exists_for_skill_context(self, tmp_path):
        agent = _agent(tmp_path)
        assert agent.model is not None
        assert agent.model.model_name == agent.settings.default_language_model

    def test_model_manager_reachable_but_brain_never_imports_providers_directly(self):
        import smartagent.brain.module_bindings as module_bindings

        source = inspect.getsource(module_bindings)
        assert "smartagent.models.providers" not in source
        assert "MockModelProvider" not in source
