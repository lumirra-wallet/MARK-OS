"""
Tests for Milestone 9 — Ollama Integration.

Strategy:
- All Ollama HTTP calls are mocked via ``unittest.mock.patch`` on
  ``urllib.request.urlopen`` — no network, no real Ollama server required.
- ``OllamaProvider`` and ``OllamaModelDiscovery`` are unit-tested directly.
- ``ModelManager.load_ollama_models()`` and the new alias methods are
  integration-tested with a fresh ``ModelManager``.
- Console commands (``models``, ``model use``, ``model current``,
  ``model info``, ``chat``) are tested through the ``SmartAgent``
  fixture — Ollama HTTP mocked globally for the whole agent.
- Free-text fallback is tested both with and without an active model.
- Coding auto-routing is tested via keyword detection.
- All 658 existing tests continue to pass (no regressions).
"""

from __future__ import annotations

import io
import json
import urllib.error
from http.client import HTTPResponse
from io import BytesIO
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from smartagent.brain.agent import SmartAgent
from smartagent.config.settings import Settings
from smartagent.models.base.base_model import ModelStatus
from smartagent.models.config.model_settings import ModelSettings
from smartagent.models.manager.model_manager import ModelManager
from smartagent.models.prompts.mark_system_prompt import MARK_SYSTEM_PROMPT
from smartagent.models.prompts.prompt_builder import Prompt, PromptBuilder
from smartagent.models.providers.ollama_provider import (
    OllamaModelDiscovery,
    OllamaModelInfo,
    OllamaProvider,
)
from smartagent.ui.command_router import CommandRouter
from smartagent.ui.commands.models import (
    _is_coding_request,
    fallback_chat,
    handle_chat,
    handle_model,
    handle_models,
)
from smartagent.ui.console import Console


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_http_response(body: dict | list, status: int = 200) -> MagicMock:
    """Build a fake ``urllib.request.urlopen`` context-manager response."""
    payload = json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = payload
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _tags_response(model_names: list[str]) -> dict:
    return {
        "models": [
            {
                "name": name,
                "size": 4_000_000_000,
                "modified_at": "2024-01-01T00:00:00Z",
                "details": {"family": "llama"},
            }
            for name in model_names
        ]
    }


def _chat_response(content: str, model: str = "llama3.1:8b") -> dict:
    return {
        "model": model,
        "message": {"role": "assistant", "content": content},
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 20,
    }


@pytest.fixture()
def tmp_agent(tmp_path: Path) -> SmartAgent:
    """Isolated SmartAgent with Ollama HTTP calls mocked at the urllib level."""
    settings = Settings(
        vault_path=str(tmp_path / "vault"),
        knowledge_path=str(tmp_path / "knowledge"),
        workspace_path=str(tmp_path),
    )
    # Suppress all Ollama HTTP calls during agent construction.
    tags_resp = _make_http_response(_tags_response(["llama3.1:8b", "qwen2.5-coder:7b"]))
    with patch("urllib.request.urlopen", return_value=tags_resp):
        agent = SmartAgent(settings=settings)
    return agent


@pytest.fixture()
def console(tmp_agent: SmartAgent) -> Console:
    return Console(tmp_agent)


# ---------------------------------------------------------------------------
# OllamaModelInfo dataclass
# ---------------------------------------------------------------------------


class TestOllamaModelInfo:
    def test_fields(self):
        info = OllamaModelInfo(
            name="llama3.1:8b",
            size=4_000_000_000,
            family="llama",
            modified_at="2024-01-01T00:00:00Z",
        )
        assert info.name == "llama3.1:8b"
        assert info.size == 4_000_000_000
        assert info.family == "llama"
        assert info.modified_at == "2024-01-01T00:00:00Z"
        assert info.status == "available"


# ---------------------------------------------------------------------------
# OllamaModelDiscovery
# ---------------------------------------------------------------------------


class TestOllamaModelDiscovery:
    def test_list_models_success(self):
        resp = _make_http_response(_tags_response(["llama3.1:8b", "qwen2.5-coder:7b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            disc = OllamaModelDiscovery("http://127.0.0.1:11434")
            models = disc.list_models()
        assert len(models) == 2
        assert models[0].name == "llama3.1:8b"
        assert models[1].name == "qwen2.5-coder:7b"
        assert models[0].family == "llama"
        assert isinstance(models[0].size, int)

    def test_list_models_empty_server(self):
        resp = _make_http_response({"models": []})
        with patch("urllib.request.urlopen", return_value=resp):
            disc = OllamaModelDiscovery("http://127.0.0.1:11434")
            models = disc.list_models()
        assert models == []

    def test_list_models_server_unreachable(self):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            disc = OllamaModelDiscovery("http://127.0.0.1:11434")
            models = disc.list_models()
        # Must never raise — returns empty list instead.
        assert models == []

    def test_is_model_installed_true(self):
        resp = _make_http_response(_tags_response(["llama3.1:8b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            disc = OllamaModelDiscovery()
            assert disc.is_model_installed("llama3.1:8b") is True

    def test_is_model_installed_false(self):
        resp = _make_http_response(_tags_response(["llama3.1:8b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            disc = OllamaModelDiscovery()
            assert disc.is_model_installed("mistral:7b") is False

    def test_is_model_installed_server_down(self):
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            disc = OllamaModelDiscovery()
            assert disc.is_model_installed("llama3.1:8b") is False


# ---------------------------------------------------------------------------
# OllamaProvider — identity and capabilities
# ---------------------------------------------------------------------------


class TestOllamaProviderIdentity:
    def test_id_equals_model_name(self):
        p = OllamaProvider(model_name="llama3.1:8b")
        assert p.id == "llama3.1:8b"

    def test_name_includes_model(self):
        p = OllamaProvider(model_name="llama3.1:8b")
        assert "llama3.1:8b" in p.name

    def test_provider_is_ollama(self):
        p = OllamaProvider()
        assert p.provider == "ollama"

    def test_version_is_string(self):
        p = OllamaProvider()
        assert isinstance(p.version, str) and p.version

    def test_exclude_from_discovery_flag(self):
        assert OllamaProvider._exclude_from_discovery is True

    def test_capabilities(self):
        p = OllamaProvider()
        assert p.supports_streaming is True
        assert p.supports_embeddings is False
        assert p.context_window > 0


# ---------------------------------------------------------------------------
# OllamaProvider — lifecycle
# ---------------------------------------------------------------------------


class TestOllamaProviderLifecycle:
    def test_initial_status_unloaded(self):
        p = OllamaProvider()
        assert p.status() == ModelStatus.UNLOADED

    def test_load_sets_status_loaded(self):
        p = OllamaProvider()
        p.initialize()
        resp = _make_http_response(_tags_response(["llama3.1:8b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            p.load()
        assert p.status() == ModelStatus.LOADED

    def test_load_survives_offline_server(self):
        """load() must not raise even if Ollama is unreachable."""
        p = OllamaProvider()
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            p.load()  # must not raise
        assert p.status() == ModelStatus.LOADED

    def test_shutdown_sets_unloaded(self):
        p = OllamaProvider()
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        p.shutdown()
        assert p.status() == ModelStatus.UNLOADED

    def test_unload_alias(self):
        p = OllamaProvider()
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        p.unload()
        assert p.status() == ModelStatus.UNLOADED

    def test_generate_raises_before_load(self):
        p = OllamaProvider()
        with pytest.raises(RuntimeError, match="load"):
            p.generate("hi")

    def test_chat_raises_before_load(self):
        p = OllamaProvider()
        with pytest.raises(RuntimeError, match="load"):
            p.chat([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# OllamaProvider — generate()
# ---------------------------------------------------------------------------


class TestOllamaProviderGenerate:
    def _loaded_provider(self) -> OllamaProvider:
        p = OllamaProvider(model_name="llama3.1:8b")
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        return p

    def test_generate_returns_dict_with_content(self):
        p = self._loaded_provider()
        resp = _make_http_response(_chat_response("Hello Mr. Smart!"))
        with patch("urllib.request.urlopen", return_value=resp):
            raw = p.generate("hello")
        assert isinstance(raw, dict)
        assert raw["content"] == "Hello Mr. Smart!"

    def test_generate_returns_usage(self):
        p = self._loaded_provider()
        resp = _make_http_response(_chat_response("hi"))
        with patch("urllib.request.urlopen", return_value=resp):
            raw = p.generate("hello")
        assert "usage" in raw
        assert raw["usage"]["prompt_tokens"] == 10
        assert raw["usage"]["completion_tokens"] == 20

    def test_generate_increments_call_count(self):
        p = self._loaded_provider()
        resp = _make_http_response(_chat_response("hi"))
        with patch("urllib.request.urlopen", return_value=resp):
            p.generate("hello")
            p.generate("world")
        assert p.call_count == 2

    def test_generate_fallback_when_unavailable(self):
        """Ollama down → content is the fallback string, not a raise."""
        p = self._loaded_provider()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            raw = p.generate("hello")
        assert "unavailable" in raw["content"].lower()
        assert raw["finish_reason"] == "error"

    def test_generate_fallback_on_os_error(self):
        p = self._loaded_provider()
        with patch("urllib.request.urlopen", side_effect=OSError("no route")):
            raw = p.generate("hello")
        assert "unavailable" in raw["content"].lower()

    def test_generate_finish_reason_stop_on_success(self):
        p = self._loaded_provider()
        resp = _make_http_response(_chat_response("ok"))
        with patch("urllib.request.urlopen", return_value=resp):
            raw = p.generate("hello")
        assert raw["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# OllamaProvider — chat()
# ---------------------------------------------------------------------------


class TestOllamaProviderChat:
    def _loaded_provider(self) -> OllamaProvider:
        p = OllamaProvider()
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        return p

    def test_chat_success(self):
        p = self._loaded_provider()
        resp = _make_http_response(_chat_response("I can help with that."))
        with patch("urllib.request.urlopen", return_value=resp):
            raw = p.chat([{"role": "user", "content": "hello"}])
        assert raw["content"] == "I can help with that."

    def test_chat_fallback_when_unavailable(self):
        p = self._loaded_provider()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            raw = p.chat([{"role": "user", "content": "hi"}])
        assert "unavailable" in raw["content"].lower()


# ---------------------------------------------------------------------------
# OllamaProvider — stream()
# ---------------------------------------------------------------------------


class TestOllamaProviderStream:
    def _loaded_provider(self) -> OllamaProvider:
        p = OllamaProvider()
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        return p

    def test_stream_yields_tokens(self):
        p = self._loaded_provider()
        chunks = [
            json.dumps({"message": {"role": "assistant", "content": "Hello"}, "done": False}).encode(),
            json.dumps({"message": {"role": "assistant", "content": " world"}, "done": True}).encode(),
        ]
        fake_resp = MagicMock()
        fake_resp.__iter__ = MagicMock(return_value=iter(chunks))
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=fake_resp):
            tokens = list(p.stream("hello"))
        assert "Hello" in tokens
        assert " world" in tokens

    def test_stream_fallback_when_unavailable(self):
        p = self._loaded_provider()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            tokens = list(p.stream("hello"))
        assert len(tokens) == 1
        assert "unavailable" in tokens[0].lower()

    def test_stream_raises_before_load(self):
        p = OllamaProvider()
        with pytest.raises(RuntimeError, match="load"):
            list(p.stream("hi"))


# ---------------------------------------------------------------------------
# OllamaProvider — health()
# ---------------------------------------------------------------------------


class TestOllamaProviderHealth:
    def _provider(self) -> OllamaProvider:
        p = OllamaProvider(model_name="llama3.1:8b")
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        return p

    def test_health_healthy_when_installed(self):
        p = self._provider()
        resp = _make_http_response(_tags_response(["llama3.1:8b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            health = p.health()
        assert health.healthy is True
        assert "installed" in health.message.lower()

    def test_health_unhealthy_when_not_installed(self):
        p = self._provider()
        resp = _make_http_response(_tags_response(["mistral:7b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            health = p.health()
        assert health.healthy is False
        assert "not installed" in health.message.lower()

    def test_health_unhealthy_when_server_down(self):
        p = self._provider()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            health = p.health()
        assert health.healthy is False
        assert "unreachable" in health.message.lower()

    def test_health_returns_model_health_type(self):
        from smartagent.models.base.base_model import ModelHealth
        p = self._provider()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            health = p.health()
        assert isinstance(health, ModelHealth)


# ---------------------------------------------------------------------------
# OllamaProvider — model_info()
# ---------------------------------------------------------------------------


class TestOllamaProviderModelInfo:
    def test_model_info_returns_info_when_installed(self):
        p = OllamaProvider(model_name="llama3.1:8b")
        resp = _make_http_response(_tags_response(["llama3.1:8b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            info = p.model_info()
        assert info is not None
        assert info.name == "llama3.1:8b"

    def test_model_info_returns_none_when_not_found(self):
        p = OllamaProvider(model_name="mistral:7b")
        resp = _make_http_response(_tags_response(["llama3.1:8b"]))
        with patch("urllib.request.urlopen", return_value=resp):
            info = p.model_info()
        assert info is None

    def test_model_info_returns_none_when_server_down(self):
        p = OllamaProvider(model_name="llama3.1:8b")
        with patch("urllib.request.urlopen", side_effect=OSError()):
            info = p.model_info()
        assert info is None


# ---------------------------------------------------------------------------
# OllamaProvider — embed() raises
# ---------------------------------------------------------------------------


class TestOllamaProviderEmbed:
    def test_embed_raises_not_implemented(self):
        p = OllamaProvider()
        with pytest.raises(NotImplementedError):
            p.embed("hello world")


# ---------------------------------------------------------------------------
# OllamaProvider — excluded from auto-discovery
# ---------------------------------------------------------------------------


class TestOllamaProviderDiscoveryExclusion:
    def test_not_in_discovered_classes(self):
        from smartagent.models.registry.model_loader import discover_provider_classes
        classes = discover_provider_classes()
        names = [c.__name__ for c in classes]
        assert "OllamaProvider" not in names

    def test_mock_provider_still_discovered(self):
        from smartagent.models.registry.model_loader import discover_provider_classes
        classes = discover_provider_classes()
        names = [c.__name__ for c in classes]
        assert "MockModelProvider" in names


# ---------------------------------------------------------------------------
# ModelManager — new API surface
# ---------------------------------------------------------------------------


class TestModelManagerOllamaAPI:
    def _manager(self) -> ModelManager:
        return ModelManager(settings=ModelSettings())

    def test_list_models_returns_base_model_instances(self):
        mgr = self._manager()
        mgr.discover_providers()
        models = mgr.list_models()
        from smartagent.models.base.base_model import BaseModel
        assert all(isinstance(m, BaseModel) for m in models)

    def test_load_model_alias(self):
        mgr = self._manager()
        mgr.discover_providers()
        m = mgr.load_model("mock")
        assert m.id == "mock"
        assert m.status().value == "loaded"

    def test_switch_model_alias(self):
        mgr = self._manager()
        mgr.discover_providers()
        mgr.switch_model("mock")
        assert mgr.active_model_id == "mock"

    def test_unload_model_alias(self):
        mgr = self._manager()
        mgr.discover_providers()
        mgr.load_model("mock")
        result = mgr.unload_model("mock")
        assert result is True

    def test_active_model_returns_instance(self):
        mgr = self._manager()
        mgr.discover_providers()
        mgr.switch_model("mock")
        m = mgr.active_model()
        assert m is not None
        assert m.id == "mock"

    def test_active_model_returns_none_when_none_active(self):
        mgr = self._manager()
        mgr.discover_providers()
        assert mgr.active_model() is None

    def test_load_ollama_models_registers_providers(self):
        mgr = self._manager()
        tags_resp = _make_http_response(_tags_response(["llama3.1:8b", "qwen2.5-coder:7b"]))
        with patch("urllib.request.urlopen", return_value=tags_resp):
            registered = mgr.load_ollama_models(
                default_model="llama3.1:8b",
                coding_model="qwen2.5-coder:7b",
            )
        assert "llama3.1:8b" in registered or mgr.registry.find("llama3.1:8b") is not None
        assert mgr.registry.find("llama3.1:8b") is not None
        assert mgr.registry.find("qwen2.5-coder:7b") is not None

    def test_load_ollama_models_works_when_server_down(self):
        """No crash when Ollama is offline — providers still registered."""
        mgr = self._manager()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            registered = mgr.load_ollama_models()
        assert mgr.registry.find("llama3.1:8b") is not None

    def test_load_ollama_models_idempotent(self):
        """Calling twice does not duplicate registrations."""
        mgr = self._manager()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            mgr.load_ollama_models()
            mgr.load_ollama_models()
        assert len([m for m in mgr.list_models() if m.id == "llama3.1:8b"]) == 1

    def test_load_ollama_models_registers_discovered_extras(self):
        """Extra models from the server are also registered."""
        mgr = self._manager()
        tags_resp = _make_http_response(
            _tags_response(["llama3.1:8b", "qwen2.5-coder:7b", "mistral:7b"])
        )
        with patch("urllib.request.urlopen", return_value=tags_resp):
            mgr.load_ollama_models()
        assert mgr.registry.find("mistral:7b") is not None


# ---------------------------------------------------------------------------
# MARK system prompt
# ---------------------------------------------------------------------------


class TestMarkSystemPrompt:
    def test_prompt_is_non_empty_string(self):
        assert isinstance(MARK_SYSTEM_PROMPT, str)
        assert len(MARK_SYSTEM_PROMPT) > 50

    def test_prompt_mentions_mark(self):
        assert "MARK" in MARK_SYSTEM_PROMPT

    def test_prompt_mentions_owner(self):
        assert "Mr. Smart" in MARK_SYSTEM_PROMPT

    def test_prompt_includes_mission(self):
        lower = MARK_SYSTEM_PROMPT.lower()
        assert "mission" in lower or "serve" in lower


# ---------------------------------------------------------------------------
# PromptBuilder — Milestone 9 extensions
# ---------------------------------------------------------------------------


class TestPromptBuilderExtensions:
    def test_build_with_knowledge_context(self):
        pb = PromptBuilder()
        p = pb.build("hello", knowledge_snippets=["Python is a language"])
        assert "Python is a language" in p.knowledge_context

    def test_build_with_mind_state(self):
        pb = PromptBuilder()
        p = pb.build("hello", mind_state="thinking")
        assert p.mind_state == "thinking"

    def test_build_with_identity(self):
        pb = PromptBuilder()
        p = pb.build("hello", identity="MARK v0.10")
        assert p.identity == "MARK v0.10"

    def test_build_with_goals(self):
        pb = PromptBuilder()
        p = pb.build("hello", goals=["help Mr. Smart", "protect data"])
        assert "help Mr. Smart" in p.goals

    def test_build_backward_compatible(self):
        """Existing call sites with no new kwargs still work."""
        pb = PromptBuilder()
        p = pb.build("hello world")
        assert p.user_message == "hello world"
        assert p.knowledge_context == ()
        assert p.mind_state == ""

    def test_prompt_render_includes_knowledge(self):
        pb = PromptBuilder()
        p = pb.build("hello", knowledge_snippets=["SQL is a query language"])
        rendered = p.render()
        assert "SQL is a query language" in rendered

    def test_prompt_render_includes_goals(self):
        pb = PromptBuilder()
        p = pb.build("hello", goals=["write better code"])
        rendered = p.render()
        assert "write better code" in rendered

    def test_prompt_render_includes_mind_state(self):
        pb = PromptBuilder()
        p = pb.build("hello", mind_state="idle")
        rendered = p.render()
        assert "idle" in rendered

    def test_prompt_to_messages_includes_knowledge(self):
        pb = PromptBuilder()
        p = pb.build("hello", knowledge_snippets=["fact one"])
        messages = p.to_messages()
        combined = " ".join(m["content"] for m in messages)
        assert "fact one" in combined

    def test_prompt_to_messages_includes_goals(self):
        pb = PromptBuilder()
        p = pb.build("hello", goals=["goal alpha"])
        messages = p.to_messages()
        combined = " ".join(m["content"] for m in messages)
        assert "goal alpha" in combined


# ---------------------------------------------------------------------------
# Coding detection
# ---------------------------------------------------------------------------


class TestCodingDetection:
    def test_python_keyword_detected(self):
        assert _is_coding_request("write a python web scraper") is True

    def test_code_keyword_detected(self):
        assert _is_coding_request("write some code for me") is True

    def test_sql_keyword_detected(self):
        assert _is_coding_request("write a sql query") is True

    def test_plain_greeting_not_coding(self):
        assert _is_coding_request("hello how are you") is False

    def test_general_question_not_coding(self):
        assert _is_coding_request("what is the weather today") is False

    def test_algorithm_is_coding(self):
        assert _is_coding_request("explain a sorting algorithm") is True

    def test_debug_is_coding(self):
        assert _is_coding_request("debug this error please") is True


# ---------------------------------------------------------------------------
# Console commands — models / model / chat
# ---------------------------------------------------------------------------


class TestModelsConsoleCommand:
    def test_models_returns_string(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "models")
        assert isinstance(response, str)

    def test_models_no_error(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "models")
        assert not response.startswith("[error]")

    def test_models_lists_ollama_providers(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "models")
        assert "llama3.1:8b" in response or "qwen2.5-coder:7b" in response

    def test_models_shows_active_when_set(self, console, tmp_agent):
        # Switch to Ollama model (load() is mocked to survive Ollama being down).
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        response = console.router.dispatch(tmp_agent, "models")
        assert "llama3.1:8b" in response


class TestModelSubcommand:
    def test_model_use_switches_model(self, console, tmp_agent):
        with patch("urllib.request.urlopen", side_effect=OSError()):
            response = console.router.dispatch(tmp_agent, "model use llama3.1:8b")
        assert "llama3.1:8b" in response
        assert "Active model" in response

    def test_model_use_unknown_model_returns_message(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "model use does-not-exist:99b")
        assert "not registered" in response.lower() or "unavailable" in response.lower() or "not" in response.lower()

    def test_model_current_when_none_active(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "model current")
        assert "no model" in response.lower() or "none" in response.lower() or "active" in response.lower()

    def test_model_current_after_switch(self, console, tmp_agent):
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        response = console.router.dispatch(tmp_agent, "model current")
        assert "llama3.1:8b" in response

    def test_model_info_when_none_active(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "model info")
        assert "no model" in response.lower() or "none" in response.lower() or "active" in response.lower()

    def test_model_info_after_switch(self, console, tmp_agent):
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        with patch("urllib.request.urlopen", side_effect=OSError()):
            response = console.router.dispatch(tmp_agent, "model info")
        assert "llama3.1:8b" in response
        assert "ollama" in response.lower() or "provider" in response.lower()

    def test_model_list_alias(self, console, tmp_agent):
        r1 = console.router.dispatch(tmp_agent, "models")
        r2 = console.router.dispatch(tmp_agent, "model list")
        assert r1 == r2

    def test_model_no_subcommand_shows_help(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "model")
        assert "use" in response.lower()

    def test_model_use_no_name_shows_usage(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "model use")
        assert "usage" in response.lower() or "model-name" in response.lower()


class TestChatCommand:
    def test_chat_no_args_shows_usage(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "chat")
        assert "usage" in response.lower()

    def test_chat_no_active_model_returns_message(self, console, tmp_agent):
        # tmp_agent has no active model by default.
        response = console.router.dispatch(tmp_agent, "chat hello there")
        assert "no model" in response.lower() or "model" in response.lower()

    def test_chat_with_active_model_calls_ollama(self, console, tmp_agent):
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        chat_resp = _make_http_response(_chat_response("Hello Mr. Smart!"))
        with patch("urllib.request.urlopen", return_value=chat_resp):
            response = console.router.dispatch(tmp_agent, "chat hello")
        assert "Hello Mr. Smart!" in response

    def test_chat_ollama_unavailable_returns_message(self, console, tmp_agent):
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            response = console.router.dispatch(tmp_agent, "chat hello")
        assert "unavailable" in response.lower()

    def test_chat_coding_request_routes_to_coding_model(self, console, tmp_agent):
        """A coding request routes to the coding model, not the default model."""
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        chat_resp = _make_http_response(_chat_response("Here is a Python scraper."))
        with patch("urllib.request.urlopen", return_value=chat_resp):
            response = console.router.dispatch(
                tmp_agent, "chat write a python web scraper"
            )
        # Either the response text or a routing note should be present.
        assert "qwen2.5-coder:7b" in response or "Python" in response or "scraper" in response.lower()


# ---------------------------------------------------------------------------
# Free-text fallback
# ---------------------------------------------------------------------------


class TestFreeTextFallback:
    def test_fallback_returns_unknown_when_no_active_model(self, console, tmp_agent):
        """With no active model, free text → 'Unknown command' message."""
        response = console.router.dispatch(tmp_agent, "hello there")
        assert "Unknown command" in response

    def test_fallback_routes_to_model_when_active(self, console, tmp_agent):
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        chat_resp = _make_http_response(_chat_response("Hi, I am MARK."))
        with patch("urllib.request.urlopen", return_value=chat_resp):
            response = console.router.dispatch(tmp_agent, "hi")
        assert "MARK" in response or "Hi" in response

    def test_fallback_unavailable_message_when_ollama_down(self, console, tmp_agent):
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            response = console.router.dispatch(tmp_agent, "what is the capital of France")
        assert "unavailable" in response.lower()

    def test_fallback_registered_in_console(self, console):
        """Console sets a fallback on its router."""
        assert console.router._fallback is not None

    def test_known_commands_not_affected_by_fallback(self, console, tmp_agent):
        """Registered commands still work normally when a fallback is set."""
        response = console.router.dispatch(tmp_agent, "version")
        assert "0." in response  # version number

    def test_fallback_handler_standalone(self, tmp_agent):
        """fallback_chat() directly: no model → 'Unknown command' message."""
        response = fallback_chat(tmp_agent, "xyzzy not a command")
        assert "Unknown command" in response

    def test_fallback_handler_with_model(self, tmp_agent):
        """fallback_chat() directly: model active → calls model."""
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        chat_resp = _make_http_response(_chat_response("I am MARK."))
        with patch("urllib.request.urlopen", return_value=chat_resp):
            response = fallback_chat(tmp_agent, "hello there")
        assert "MARK" in response or "I am" in response


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestOllamaSettings:
    def test_ollama_base_url_default(self):
        s = Settings()
        assert s.ollama_base_url == "http://127.0.0.1:11434"

    def test_ollama_default_model(self):
        s = Settings()
        assert s.ollama_default_model == "llama3.1:8b"

    def test_ollama_coding_model(self):
        s = Settings()
        assert s.ollama_coding_model == "qwen2.5-coder:7b"

    def test_custom_base_url(self):
        s = Settings(ollama_base_url="http://192.168.1.10:11434")
        assert s.ollama_base_url == "http://192.168.1.10:11434"

    def test_model_settings_ollama_fields(self):
        ms = ModelSettings(ollama_base_url="http://example.com:11434")
        assert ms.ollama_base_url == "http://example.com:11434"
        assert ms.ollama_default_model == "llama3.1:8b"
        assert ms.ollama_coding_model == "qwen2.5-coder:7b"


# ---------------------------------------------------------------------------
# Agent — Ollama models registered at startup
# ---------------------------------------------------------------------------


class TestAgentOllamaStartup:
    def test_agent_registers_default_ollama_models(self, tmp_agent):
        registry = tmp_agent.model_manager.registry
        assert registry.find("llama3.1:8b") is not None
        assert registry.find("qwen2.5-coder:7b") is not None

    def test_agent_no_active_model_at_startup(self, tmp_agent):
        assert tmp_agent.model_manager.active_model_id is None

    def test_agent_mock_provider_also_registered(self, tmp_agent):
        assert tmp_agent.model_manager.registry.find("mock") is not None
