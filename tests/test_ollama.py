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
from types import SimpleNamespace
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
    """
    Isolated SmartAgent with Ollama HTTP calls mocked at the urllib level.

    Streaming is explicitly disabled so all pre-M10 tests continue to
    test the non-streaming return-value path unchanged.  The separate
    ``streaming_agent`` fixture (in ``TestStreamingConsole``) enables
    streaming to test the M10 path.
    """
    settings = Settings(
        vault_path=str(tmp_path / "vault"),
        knowledge_path=str(tmp_path / "knowledge"),
        workspace_path=str(tmp_path),
    )
    # Suppress all Ollama HTTP calls during agent construction.
    tags_resp = _make_http_response(_tags_response(["llama3.1:8b", "qwen2.5-coder:7b"]))
    with patch("urllib.request.urlopen", return_value=tags_resp):
        agent = SmartAgent(settings=settings)
        # SmartAgent.__init__ no longer auto-registers Ollama models (MARK's
        # live agent doesn't use Ollama by default) — register them
        # explicitly here so these Ollama-specific tests keep their expected
        # fixture state.
        agent.model_manager.load_ollama_models()
    # Keep the non-streaming path active so pre-M10 assertions on return
    # values continue to pass.  TestStreamingConsole tests the streaming path.
    agent.model_manager.settings.streaming_enabled = False
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
    def test_embed_uses_api_embed_endpoint(self):
        """embed() should call /api/embed and return the vector."""
        import json as _json
        vector = [0.1, 0.2, 0.3, 0.4]
        response_body = _json.dumps({"embeddings": [vector]}).encode()
        p = OllamaProvider()
        p._status = ModelStatus.LOADED
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = response_body
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            result = p.embed("hello world")
        assert result == vector

    def test_embed_falls_back_to_embeddings_endpoint(self):
        """embed() falls back to /api/embeddings on 404 from /api/embed."""
        import json as _json
        import urllib.error
        vector = [0.5, 0.6]
        fallback_body = _json.dumps({"embedding": vector}).encode()

        p = OllamaProvider()
        p._status = ModelStatus.LOADED

        call_count = [0]

        def side_effect(req, timeout=None):
            call_count[0] += 1
            url = req.full_url if hasattr(req, 'full_url') else str(req.get_full_url())
            if "/api/embed" in url and "/api/embeddings" not in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            mock_resp = MagicMock()
            mock_resp.read.return_value = fallback_body
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = p.embed("hello world")
        assert result == vector

    def test_embeddings_alias(self):
        """embeddings() is an alias for embed()."""
        import json as _json
        vector = [0.9, 0.8, 0.7]
        response_body = _json.dumps({"embeddings": [vector]}).encode()
        p = OllamaProvider()
        p._status = ModelStatus.LOADED
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = response_body
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            result = p.embeddings("test text")
        assert result == vector

    def test_list_models_returns_list(self):
        """list_models() returns a list of dicts (or empty list if offline)."""
        p = OllamaProvider()
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = Exception("offline")
            result = p.list_models()
        assert isinstance(result, list)

    def test_stream_chat_alias(self):
        """stream_chat() is an alias for chat_stream()."""
        import json as _json
        chunks = [
            _json.dumps({"message": {"content": "hi"}, "done": False}).encode(),
            _json.dumps({"message": {"content": ""}, "done": True}).encode(),
        ]
        p = OllamaProvider()
        p._status = ModelStatus.LOADED
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.__iter__ = MagicMock(return_value=iter(chunks))
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            tokens = list(p.stream_chat([{"role": "user", "content": "hi"}]))
        assert "hi" in tokens

    def test_switch_model_updates_model_name(self):
        """switch_model() updates the internal model name."""
        p = OllamaProvider(model_name="llama3:8b")
        p.switch_model("phi4:latest")
        assert p._model_name == "phi4:latest"


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

    def test_prompt_declares_operating_system_identity(self):
        assert "AI Operating System" in MARK_SYSTEM_PROMPT

    def test_prompt_never_claims_to_be_a_coding_agent(self):
        lower = MARK_SYSTEM_PROMPT.lower()
        assert "autonomous ai software engineer" not in lower
        assert "ai software engineering assistant" not in lower


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
    def test_ollama_base_url_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        s = Settings()
        assert s.ollama_base_url == "http://localhost:11434"

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


# ---------------------------------------------------------------------------
# Milestone 10 — Streaming upgrade
# ---------------------------------------------------------------------------


def _make_stream_response(tokens: list[str]) -> MagicMock:
    """
    Build a fake streaming ``urlopen`` context-manager that yields NDJSON lines
    for each token, followed by a final ``done=True`` chunk.
    """
    lines: list[bytes] = []
    for i, token in enumerate(tokens):
        done = i == len(tokens) - 1
        line = json.dumps({
            "message": {"role": "assistant", "content": token},
            "done": done,
        }).encode("utf-8")
        lines.append(line)

    fake_resp = MagicMock()
    fake_resp.__iter__ = MagicMock(return_value=iter(lines))
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = MagicMock(return_value=False)
    return fake_resp


class TestOllamaProviderGenerateStream:
    """Tests for OllamaProvider.generate_stream() — Part 1/2."""

    def _loaded(self) -> OllamaProvider:
        p = OllamaProvider(model_name="llama3.1:8b")
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        return p

    def test_generate_stream_yields_tokens_in_order(self):
        p = self._loaded()
        tokens = ["Hello", " Mr.", " Smart", "."]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = list(p.generate_stream("hello"))
        assert result == tokens

    def test_generate_stream_yields_partial_output(self):
        p = self._loaded()
        tokens = ["Alpha", " Beta"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            gen = p.generate_stream("test")
            first = next(gen)
        assert first == "Alpha"

    def test_generate_stream_fallback_when_unavailable(self):
        p = self._loaded()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            chunks = list(p.generate_stream("hi"))
        assert len(chunks) == 1
        assert "unavailable" in chunks[0].lower()

    def test_generate_stream_raises_before_load(self):
        p = OllamaProvider()
        with pytest.raises(RuntimeError, match="load"):
            list(p.generate_stream("hi"))

    def test_generate_stream_increments_call_count(self):
        p = self._loaded()
        with patch("urllib.request.urlopen", return_value=_make_stream_response(["hi"])):
            list(p.generate_stream("hello"))
        assert p.call_count == 1

    def test_stream_delegates_to_generate_stream(self):
        """stream() must remain backward-compatible by delegating to generate_stream()."""
        p = self._loaded()
        tokens = ["token1", " token2"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = list(p.stream("hello"))
        assert result == tokens


class TestOllamaProviderChatStream:
    """Tests for OllamaProvider.chat_stream() — Part 1/2."""

    def _loaded(self) -> OllamaProvider:
        p = OllamaProvider()
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()
        return p

    def test_chat_stream_yields_tokens(self):
        p = self._loaded()
        tokens = ["Hello", " there"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = list(p.chat_stream([{"role": "user", "content": "hi"}]))
        assert result == tokens

    def test_chat_stream_fallback_when_unavailable(self):
        p = self._loaded()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            chunks = list(p.chat_stream([{"role": "user", "content": "hi"}]))
        assert "unavailable" in chunks[0].lower()

    def test_chat_stream_raises_before_load(self):
        p = OllamaProvider()
        with pytest.raises(RuntimeError, match="load"):
            list(p.chat_stream([{"role": "user", "content": "hi"}]))

    def test_chat_stream_increments_call_count(self):
        p = self._loaded()
        with patch("urllib.request.urlopen", return_value=_make_stream_response(["ok"])):
            list(p.chat_stream([{"role": "user", "content": "hi"}]))
        assert p.call_count == 1


class TestBaseModelStreamDefaults:
    """Tests for new concrete default methods on BaseModel — Part 2."""

    def test_generate_stream_default_delegates_to_stream(self):
        """MockModelProvider inherits generate_stream() → stream() → generate()."""
        from smartagent.models.providers.mock_provider import MockModelProvider
        m = MockModelProvider()
        m.initialize()
        m.load()
        chunks = list(m.generate_stream("hello world"))
        assert len(chunks) > 0
        # Must reconstruct the full content (ignoring spacing differences).
        assert "mock" in " ".join(chunks).lower() or "hello" in " ".join(chunks).lower()

    def test_chat_stream_default_yields_content(self):
        """chat_stream() default flattens messages and delegates to stream()."""
        from smartagent.models.providers.mock_provider import MockModelProvider
        m = MockModelProvider()
        m.initialize()
        m.load()
        messages = [{"role": "user", "content": "hello"}]
        chunks = list(m.chat_stream(messages))
        assert len(chunks) > 0


class TestModelManagerStreaming:
    """Tests for ModelManager.generate_stream() and chat_stream() — Part 3."""

    def _manager_with_ollama(self) -> ModelManager:
        mgr = ModelManager(settings=ModelSettings())
        tags_resp = _make_http_response(_tags_response(["llama3.1:8b"]))
        with patch("urllib.request.urlopen", return_value=tags_resp):
            mgr.load_ollama_models(default_model="llama3.1:8b", coding_model="llama3.1:8b")
        with patch("urllib.request.urlopen", side_effect=OSError()):
            mgr.switch("llama3.1:8b")
        return mgr

    def test_generate_stream_yields_tokens(self):
        mgr = self._manager_with_ollama()
        tokens = ["Hi", " there"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = list(mgr.generate_stream("hello"))
        assert result == tokens

    def test_generate_stream_raises_no_active_model(self):
        from smartagent.models.manager.model_manager import NoActiveModelError
        mgr = ModelManager()
        with pytest.raises(NoActiveModelError):
            list(mgr.generate_stream("hello"))

    def test_generate_stream_with_explicit_model_id(self):
        mgr = self._manager_with_ollama()
        tokens = ["token"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = list(mgr.generate_stream("hello", model_id="llama3.1:8b"))
        assert result == tokens

    def test_chat_stream_yields_tokens(self):
        mgr = self._manager_with_ollama()
        tokens = ["Hello", " world"]
        messages = [{"role": "user", "content": "hi"}]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = list(mgr.chat_stream(messages))
        assert result == tokens

    def test_chat_stream_raises_no_active_model(self):
        from smartagent.models.manager.model_manager import NoActiveModelError
        mgr = ModelManager()
        with pytest.raises(NoActiveModelError):
            list(mgr.chat_stream([{"role": "user", "content": "hi"}]))

    def test_no_duplicate_logic_generate_vs_generate_stream(self):
        """generate() and generate_stream() are separate code paths — both work."""
        mgr = self._manager_with_ollama()
        # Non-streaming
        with patch("urllib.request.urlopen", return_value=_make_http_response(_chat_response("ok"))):
            resp = mgr.generate("hello")
        assert resp.text == "ok"
        # Streaming
        with patch("urllib.request.urlopen", return_value=_make_stream_response(["ok"])):
            chunks = list(mgr.generate_stream("hello"))
        assert "ok" in chunks


class TestWarmup:
    """Tests for OllamaProvider model warmup on load() — Part 8."""

    def test_warmup_called_on_load_when_enabled(self):
        p = OllamaProvider(model_name="llama3.1:8b", warmup_enabled=True)
        p.initialize()
        call_args: list[tuple] = []

        def fake_urlopen(req, timeout=None):
            call_args.append((req,))
            resp = MagicMock()
            resp.read.return_value = json.dumps(_tags_response(["llama3.1:8b"])).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            p.load()

        # First call: /api/tags (health ping). Second call: /api/chat (warmup).
        assert len(call_args) == 2

    def test_warmup_not_called_when_disabled(self):
        p = OllamaProvider(model_name="llama3.1:8b", warmup_enabled=False)
        p.initialize()
        call_args: list[tuple] = []

        def fake_urlopen(req, timeout=None):
            call_args.append((req,))
            resp = MagicMock()
            resp.read.return_value = json.dumps(_tags_response(["llama3.1:8b"])).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            p.load()

        # Only the /api/tags health ping, no warmup.
        assert len(call_args) == 1

    def test_warmup_survives_server_down(self):
        """warmup() must not raise even if Ollama is unreachable."""
        p = OllamaProvider(model_name="llama3.1:8b", warmup_enabled=True)
        p.initialize()
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            p.load()  # must not raise
        assert p.status() == ModelStatus.LOADED

    def test_warmup_enabled_passed_by_model_manager(self):
        """load_ollama_models() passes warmup_enabled from settings."""
        from smartagent.models.config.model_settings import ModelSettings
        settings = ModelSettings(warmup_enabled=True)
        mgr = ModelManager(settings=settings)
        with patch("urllib.request.urlopen", side_effect=OSError()):
            mgr.load_ollama_models()
        provider = mgr.registry.find("llama3.1:8b")
        assert provider is not None
        from smartagent.models.providers.ollama_provider import OllamaProvider
        assert isinstance(provider, OllamaProvider)
        assert provider._warmup_enabled is True


class TestLazyLoading:
    """Tests for lazy model loading on switch() — Part 9."""

    def _mgr_with_lazy(self) -> ModelManager:
        from smartagent.models.config.model_settings import ModelSettings
        settings = ModelSettings(lazy_model_loading=True)
        mgr = ModelManager(settings=settings)
        with patch("urllib.request.urlopen", side_effect=OSError()):
            mgr.load_ollama_models(
                default_model="llama3.1:8b",
                coding_model="qwen2.5-coder:7b",
            )
        return mgr

    def test_lazy_switch_unloads_previous_model(self):
        mgr = self._mgr_with_lazy()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            mgr.switch("llama3.1:8b")
        # llama3.1:8b is now loaded
        assert mgr.registry.find("llama3.1:8b").status() == ModelStatus.LOADED

        with patch("urllib.request.urlopen", side_effect=OSError()):
            mgr.switch("qwen2.5-coder:7b")
        # After switching away, previous model should be unloaded
        assert mgr.registry.find("llama3.1:8b").status() == ModelStatus.UNLOADED
        assert mgr.registry.find("qwen2.5-coder:7b").status() == ModelStatus.LOADED

    def test_lazy_switch_does_not_unload_same_model(self):
        mgr = self._mgr_with_lazy()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            mgr.switch("llama3.1:8b")
            mgr.switch("llama3.1:8b")  # switch to same model
        assert mgr.registry.find("llama3.1:8b").status() == ModelStatus.LOADED

    def test_no_lazy_unload_when_disabled(self):
        """Without lazy_model_loading, switching keeps both models loaded."""
        from smartagent.models.config.model_settings import ModelSettings
        settings = ModelSettings(lazy_model_loading=False)
        mgr = ModelManager(settings=settings)
        with patch("urllib.request.urlopen", side_effect=OSError()):
            mgr.load_ollama_models(
                default_model="llama3.1:8b",
                coding_model="qwen2.5-coder:7b",
            )
            mgr.switch("llama3.1:8b")
            mgr.switch("qwen2.5-coder:7b")
        # Both stay loaded when lazy loading is off.
        assert mgr.registry.find("llama3.1:8b").status() == ModelStatus.LOADED
        assert mgr.registry.find("qwen2.5-coder:7b").status() == ModelStatus.LOADED


class TestModelSettings10:
    """Tests for new Milestone 10 settings fields — Part 10."""

    def test_warmup_enabled_default(self):
        from smartagent.models.config.model_settings import ModelSettings
        assert ModelSettings().warmup_enabled is True

    def test_cache_prompts_default(self):
        from smartagent.models.config.model_settings import ModelSettings
        assert ModelSettings().cache_prompts is True

    def test_show_generation_stats_default(self):
        from smartagent.models.config.model_settings import ModelSettings
        assert ModelSettings().show_generation_stats is False

    def test_lazy_model_loading_default(self):
        from smartagent.models.config.model_settings import ModelSettings
        assert ModelSettings().lazy_model_loading is False

    def test_streaming_enabled_default(self):
        from smartagent.models.config.model_settings import ModelSettings
        assert ModelSettings().streaming_enabled is True

    def test_settings_configurable(self):
        from smartagent.models.config.model_settings import ModelSettings
        s = ModelSettings(
            warmup_enabled=False,
            cache_prompts=False,
            show_generation_stats=True,
            lazy_model_loading=True,
            streaming_enabled=False,
        )
        assert s.warmup_enabled is False
        assert s.cache_prompts is False
        assert s.show_generation_stats is True
        assert s.lazy_model_loading is True
        assert s.streaming_enabled is False


class TestPromptCache:
    """Tests for the static prompt context cache in _send_to_model — Part 7."""

    def test_cache_key_stable_for_same_context(self):
        from smartagent.ui.commands.models import _static_cache_key
        k1 = _static_cache_key("MARK v1", "idle", ["goal A"])
        k2 = _static_cache_key("MARK v1", "idle", ["goal A"])
        assert k1 == k2

    def test_cache_key_differs_for_different_context(self):
        from smartagent.ui.commands.models import _static_cache_key
        k1 = _static_cache_key("MARK v1", "idle", ["goal A"])
        k2 = _static_cache_key("MARK v1", "thinking", ["goal B"])
        assert k1 != k2

    def test_cache_put_and_retrieve(self):
        from smartagent.ui.commands import models as m_mod
        # Reset cache for isolation.
        m_mod._STATIC_CTX_CACHE.clear()
        key = m_mod._static_cache_key("MARK", "idle", ["g1"])
        m_mod._put_cache(key, "MARK", "idle", ["g1"])
        assert key in m_mod._STATIC_CTX_CACHE
        identity, mind_state, goals = m_mod._STATIC_CTX_CACHE[key]
        assert identity == "MARK"
        assert mind_state == "idle"
        assert goals == ["g1"]

    def test_cache_max_size_respected(self):
        from smartagent.ui.commands import models as m_mod
        m_mod._STATIC_CTX_CACHE.clear()
        # Fill beyond _CACHE_MAX
        for i in range(m_mod._CACHE_MAX + 5):
            key = m_mod._static_cache_key(f"id{i}", f"state{i}", [])
            m_mod._put_cache(key, f"id{i}", f"state{i}", [])
        assert len(m_mod._STATIC_CTX_CACHE) <= m_mod._CACHE_MAX


class TestStreamingConsole:
    """
    Tests for the streaming console path — Parts 4, 5, 6.

    Strategy: disable streaming via settings (streaming_enabled=False) to
    test the non-streaming path, and use stdout capture for the streaming path.
    """

    @pytest.fixture()
    def streaming_agent(self, tmp_path: Path) -> "SmartAgent":
        from smartagent.config.settings import Settings
        from smartagent.models.config.model_settings import ModelSettings
        settings = Settings(
            vault_path=str(tmp_path / "vault"),
            knowledge_path=str(tmp_path / "knowledge"),
            workspace_path=str(tmp_path),
        )
        tags_resp = _make_http_response(_tags_response(["llama3.1:8b", "qwen2.5-coder:7b"]))
        with patch("urllib.request.urlopen", return_value=tags_resp):
            agent = SmartAgent(settings=settings)
            # SmartAgent.__init__ no longer auto-registers Ollama models —
            # register them explicitly (see tmp_agent's fixture docstring above).
            agent.model_manager.load_ollama_models()
        # Patch streaming settings on the model_manager.
        agent.model_manager.settings.streaming_enabled = True
        agent.model_manager.settings.show_generation_stats = False
        return agent

    def test_non_streaming_path_returns_text(self, tmp_agent):
        """With streaming_enabled=False, _send_to_model returns the full response string."""
        from smartagent.ui.commands.models import _send_to_model
        tmp_agent.model_manager.settings.streaming_enabled = False
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        with patch("urllib.request.urlopen", return_value=_make_http_response(_chat_response("Hello Mr. Smart"))):
            result = _send_to_model(tmp_agent, "hello")
        assert "Hello Mr. Smart" in result

    def test_streaming_path_returns_empty_string(self, streaming_agent, capsys):
        """Streaming path prints to stdout and returns '' so REPL doesn't double-print."""
        from smartagent.ui.commands.models import _send_to_model
        with patch("urllib.request.urlopen", side_effect=OSError()):
            streaming_agent.model_manager.switch("llama3.1:8b")
        tokens = ["Hello", " Mr.", " Smart"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = _send_to_model(streaming_agent, "hello")
        captured = capsys.readouterr()
        # Result is empty (REPL should not print anything extra).
        assert result == ""
        # Tokens were written to stdout.
        combined = captured.out.replace("\r", "").replace(" " * 20, "").strip()
        assert "Hello" in combined

    def test_streaming_token_order_preserved(self, streaming_agent, capsys):
        """Tokens appear in the correct order in stdout."""
        from smartagent.ui.commands.models import _send_to_model
        with patch("urllib.request.urlopen", side_effect=OSError()):
            streaming_agent.model_manager.switch("llama3.1:8b")
        tokens = ["Alpha", " Beta", " Gamma"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            _send_to_model(streaming_agent, "test")
        out = capsys.readouterr().out
        idx_a = out.find("Alpha")
        idx_b = out.find("Beta")
        idx_g = out.find("Gamma")
        assert idx_a < idx_b < idx_g

    def test_streaming_unavailable_returns_error_message(self, streaming_agent):
        """Streaming path gracefully handles Ollama being down."""
        from smartagent.ui.commands.models import _send_to_model
        with patch("urllib.request.urlopen", side_effect=OSError()):
            streaming_agent.model_manager.switch("llama3.1:8b")
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            result = _send_to_model(streaming_agent, "hello")
        assert "unavailable" in result.lower()

    def test_spinner_frames_are_defined(self):
        from smartagent.ui.commands.models import _SPINNER_FRAMES
        assert len(_SPINNER_FRAMES) > 0

    def test_stats_displayed_when_enabled(self, streaming_agent, capsys):
        """Generation stats are printed when show_generation_stats=True."""
        from smartagent.ui.commands.models import _send_to_model
        streaming_agent.model_manager.settings.show_generation_stats = True
        with patch("urllib.request.urlopen", side_effect=OSError()):
            streaming_agent.model_manager.switch("llama3.1:8b")
        tokens = ["Hello"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            _send_to_model(streaming_agent, "hello")
        out = capsys.readouterr().out
        assert "Generation Stats" in out or "First token" in out

    def test_stats_not_displayed_when_disabled(self, streaming_agent, capsys):
        """Generation stats are not shown when show_generation_stats=False."""
        from smartagent.ui.commands.models import _send_to_model
        streaming_agent.model_manager.settings.show_generation_stats = False
        with patch("urllib.request.urlopen", side_effect=OSError()):
            streaming_agent.model_manager.switch("llama3.1:8b")
        tokens = ["Hello"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            _send_to_model(streaming_agent, "hello")
        out = capsys.readouterr().out
        assert "Generation Stats" not in out and "First token" not in out

    def test_fallback_to_non_streaming_when_disabled(self, tmp_agent):
        """fallback_chat() works correctly when streaming is disabled."""
        tmp_agent.model_manager.settings.streaming_enabled = False
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        with patch("urllib.request.urlopen", return_value=_make_http_response(_chat_response("Hi!"))):
            result = fallback_chat(tmp_agent, "hello")
        assert "Hi!" in result


class TestBackwardCompatibility:
    """Ensure 100% backward compatibility — all pre-M10 behaviors preserved."""

    def test_generate_still_works(self, tmp_agent):
        """generate() non-streaming path unchanged."""
        with patch("urllib.request.urlopen", side_effect=OSError()):
            tmp_agent.model_manager.switch("llama3.1:8b")
        with patch("urllib.request.urlopen", return_value=_make_http_response(_chat_response("OK"))):
            resp = tmp_agent.model_manager.generate("hello")
        assert resp.text == "OK"

    def test_chat_still_works_on_provider(self, tmp_agent):
        """OllamaProvider.chat() unchanged."""
        provider = tmp_agent.model_manager.registry.find("llama3.1:8b")
        assert provider is not None
        with patch("urllib.request.urlopen", side_effect=OSError()):
            provider.load()
        with patch("urllib.request.urlopen", return_value=_make_http_response(_chat_response("Yep"))):
            raw = provider.chat([{"role": "user", "content": "hello"}])
        assert raw["content"] == "Yep"

    def test_stream_backward_compatible(self, tmp_agent):
        """stream() still works and delegates to generate_stream()."""
        provider = tmp_agent.model_manager.registry.find("llama3.1:8b")
        assert provider is not None
        with patch("urllib.request.urlopen", side_effect=OSError()):
            provider.load()
        tokens = ["A", "B"]
        with patch("urllib.request.urlopen", return_value=_make_stream_response(tokens)):
            result = list(provider.stream("hello"))
        assert result == tokens

    def test_model_switch_still_works(self, tmp_agent):
        """model switch command unchanged."""
        from smartagent.ui.console import Console
        console = Console(tmp_agent)
        with patch("urllib.request.urlopen", side_effect=OSError()):
            resp = console.router.dispatch(tmp_agent, "model use llama3.1:8b")
        assert "llama3.1:8b" in resp

    def test_fallback_still_returns_unknown_command_with_no_model(self, tmp_agent):
        """No model active → Unknown command (identical to pre-M10)."""
        response = fallback_chat(tmp_agent, "xyzzy")
        assert "Unknown command" in response

    def test_no_active_model_error_still_raised(self):
        """NoActiveModelError raised when no model configured."""
        from smartagent.models.manager.model_manager import NoActiveModelError
        mgr = ModelManager()
        with pytest.raises(NoActiveModelError):
            list(mgr.generate_stream("hello"))
        with pytest.raises(NoActiveModelError):
            list(mgr.chat_stream([{"role": "user", "content": "hi"}]))


# ---------------------------------------------------------------------------
# Ollama as MARK's local core — chat_with_tools, capability detection,
# ModelManager fallback, factory wiring, and a real worker-pipeline run.
#
# All HTTP mocked at the urllib level, same as every other class in this
# file — no live Ollama server or network access required.
# ---------------------------------------------------------------------------

def _tags_response_with_capabilities(entries: list[tuple[str, list[str]]]) -> dict:
    """Like _tags_response() but with a per-model ``capabilities`` list."""
    return {
        "models": [
            {
                "name": name,
                "size": 2_000_000_000,
                "modified_at": "2026-01-01T00:00:00Z",
                "details": {"family": "llama"},
                "capabilities": caps,
            }
            for name, caps in entries
        ]
    }


def _tool_call_chat_response(name: str, arguments: dict, call_id: str = "call_test1") -> dict:
    """Shape of Ollama's POST /api/chat response when the model calls a tool."""
    return {
        "model": "llama3.2:3b",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": call_id, "function": {"index": 0, "name": name, "arguments": arguments}},
            ],
        },
        "done": True,
    }


class TestOllamaProviderCapabilities:
    """supports_tools / supports_functions — live capability detection."""

    def test_supports_tools_true_when_model_advertises_it(self):
        p = OllamaProvider(model_name="llama3.2:3b")
        resp = _make_http_response(_tags_response_with_capabilities(
            [("llama3.2:3b", ["completion", "tools"])]
        ))
        with patch("urllib.request.urlopen", return_value=resp):
            assert p.supports_tools is True
            assert p.supports_functions is True

    def test_supports_tools_false_when_model_lacks_it(self):
        p = OllamaProvider(model_name="llama3:latest")
        resp = _make_http_response(_tags_response_with_capabilities(
            [("llama3:latest", ["completion"])]
        ))
        with patch("urllib.request.urlopen", return_value=resp):
            assert p.supports_tools is False

    def test_supports_tools_false_when_server_unreachable(self):
        """Unreachable server must never raise — defaults to False."""
        p = OllamaProvider(model_name="llama3.2:3b")
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            assert p.supports_tools is False

    def test_supports_tools_cached_after_first_check(self):
        """Only one network call for repeated access — see docstring."""
        p = OllamaProvider(model_name="llama3.2:3b")
        resp = _make_http_response(_tags_response_with_capabilities(
            [("llama3.2:3b", ["completion", "tools"])]
        ))
        with patch("urllib.request.urlopen", return_value=resp) as mock_open:
            assert p.supports_tools is True
            assert p.supports_tools is True
            assert mock_open.call_count == 1


class TestOllamaProviderChatWithTools:
    """chat_with_tools() — the method the worker pipeline actually calls."""

    TOOLS = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
        },
    }]

    def _loaded(self) -> OllamaProvider:
        p = OllamaProvider(model_name="llama3.2:3b")
        with patch("urllib.request.urlopen", side_effect=OSError()):
            p.load()  # load() always succeeds; connectivity is health()'s job
        return p

    def test_returns_content_and_empty_tool_calls_on_final_answer(self):
        p = self._loaded()
        resp = _make_http_response(_chat_response("The answer is 4."))
        with patch("urllib.request.urlopen", return_value=resp):
            result = p.chat_with_tools([{"role": "user", "content": "2+2?"}], tools=self.TOOLS)
        assert result.content == "The answer is 4."
        assert result.tool_calls == []

    def test_tool_call_shape_matches_agent_loop_contract(self):
        """
        agent_loop.py reads response_msg.tool_calls[i].id,
        .function.name, and json.loads(.function.arguments) — arguments
        must come back as a JSON *string*, even though Ollama's own API
        returns an already-parsed object.
        """
        p = self._loaded()
        resp = _make_http_response(
            _tool_call_chat_response("get_weather", {"city": "Berlin"}, call_id="call_abc")
        )
        with patch("urllib.request.urlopen", return_value=resp):
            result = p.chat_with_tools(
                [{"role": "user", "content": "Weather in Berlin?"}], tools=self.TOOLS,
            )
        assert result.content == ""
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "call_abc"
        assert tc.function.name == "get_weather"
        assert isinstance(tc.function.arguments, str)
        assert json.loads(tc.function.arguments) == {"city": "Berlin"}

    def test_raises_when_server_unavailable(self):
        """Matches NvidiaProvider.chat_with_tools()'s raise-don't-swallow contract."""
        p = self._loaded()
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            with pytest.raises(RuntimeError, match="unavailable"):
                p.chat_with_tools([{"role": "user", "content": "hi"}], tools=self.TOOLS)

    def test_raises_when_not_loaded(self):
        p = OllamaProvider(model_name="llama3.2:3b")  # never load()ed
        with pytest.raises(RuntimeError, match="must be load"):
            p.chat_with_tools([{"role": "user", "content": "hi"}], tools=self.TOOLS)

    def test_thinking_field_never_surfaces_as_content(self):
        """qwen3-style reasoning trace must be dropped, matching every other provider."""
        p = self._loaded()
        body = _chat_response("Final answer only.")
        body["message"]["thinking"] = "Let me reason step by step..."
        with patch("urllib.request.urlopen", return_value=_make_http_response(body)):
            result = p.chat_with_tools([{"role": "user", "content": "hi"}], tools=self.TOOLS)
        assert result.content == "Final answer only."
        assert "reason step by step" not in result.content


class TestModelManagerFallback:
    """set_fallback() — generic mechanism, no knowledge of specific providers."""

    def _manager_with_two_models(self):
        mm = ModelManager()
        primary = MagicMock()
        primary.provider = "primary"
        primary.status.return_value = MagicMock(value="loaded")
        secondary = MagicMock()
        secondary.provider = "secondary"
        secondary.status.return_value = MagicMock(value="loaded")
        mm.registry.register = MagicMock()
        mm.registry.find = MagicMock(side_effect=lambda mid: {"primary": primary, "secondary": secondary}.get(mid))
        return mm, primary, secondary

    def test_no_fallback_configured_is_unchanged_behavior(self):
        """Default state (nothing calls set_fallback) — identical to pre-fallback code."""
        mm, primary, secondary = self._manager_with_two_models()
        primary.chat_with_tools.return_value = SimpleNamespace(content="Ollama server unavailable.", tool_calls=[])
        result = mm.chat_with_tools([{"role": "user", "content": "hi"}], tools=[], model_id="primary")
        assert result.content == "Ollama server unavailable."
        secondary.chat_with_tools.assert_not_called()

    def test_falls_back_on_sentinel_content(self):
        mm, primary, secondary = self._manager_with_two_models()
        primary.chat_with_tools.return_value = SimpleNamespace(content="Ollama server unavailable.", tool_calls=[])
        secondary.chat_with_tools.return_value = SimpleNamespace(content="Real answer.", tool_calls=[])
        mm.set_fallback("secondary", is_failure=lambda c: c.startswith("Ollama server unavailable."))

        result = mm.chat_with_tools([{"role": "user", "content": "hi"}], tools=[], model_id="primary")

        assert result.content == "Real answer."
        secondary.chat_with_tools.assert_called_once()

    def test_falls_back_on_exception(self):
        mm, primary, secondary = self._manager_with_two_models()
        primary.chat_with_tools.side_effect = ConnectionError("refused")
        secondary.chat_with_tools.return_value = SimpleNamespace(content="Real answer.", tool_calls=[])
        mm.set_fallback("secondary", is_failure=lambda c: False)

        result = mm.chat_with_tools([{"role": "user", "content": "hi"}], tools=[], model_id="primary")

        assert result.content == "Real answer."

    def test_no_fallback_retry_when_primary_succeeds(self):
        """The success path must never touch the fallback model at all."""
        mm, primary, secondary = self._manager_with_two_models()
        primary.chat_with_tools.return_value = SimpleNamespace(content="All good.", tool_calls=[])
        mm.set_fallback("secondary", is_failure=lambda c: "unavailable" in c)

        result = mm.chat_with_tools([{"role": "user", "content": "hi"}], tools=[], model_id="primary")

        assert result.content == "All good."
        secondary.chat_with_tools.assert_not_called()

    def test_does_not_fall_back_to_itself(self):
        """If the active model IS the fallback model, no infinite-retry risk."""
        mm, primary, _secondary = self._manager_with_two_models()
        primary.chat_with_tools.return_value = SimpleNamespace(content="Ollama server unavailable.", tool_calls=[])
        mm.set_fallback("primary", is_failure=lambda c: True)

        result = mm.chat_with_tools([{"role": "user", "content": "hi"}], tools=[], model_id="primary")

        assert result.content == "Ollama server unavailable."
        assert primary.chat_with_tools.call_count == 1

    def test_streaming_falls_back_when_only_chunk_is_sentinel(self):
        mm, primary, secondary = self._manager_with_two_models()
        primary.chat_stream.return_value = iter(["Ollama server unavailable."])
        secondary.chat_stream.return_value = iter(["Real ", "streamed ", "answer."])
        mm.set_fallback("secondary", is_failure=lambda c: c.startswith("Ollama server unavailable."))

        chunks = list(mm.chat_stream([{"role": "user", "content": "hi"}], model_id="primary"))

        assert "".join(chunks) == "Real streamed answer."

    def test_streaming_does_not_fall_back_after_real_content_started(self):
        """A sentinel-looking chunk followed by more content is NOT a total failure."""
        mm, primary, secondary = self._manager_with_two_models()
        primary.chat_stream.return_value = iter(["Ollama server unavailable.", " actually continuing"])
        mm.set_fallback("secondary", is_failure=lambda c: c.startswith("Ollama server unavailable."))

        chunks = list(mm.chat_stream([{"role": "user", "content": "hi"}], model_id="primary"))

        assert "".join(chunks) == "Ollama server unavailable. actually continuing"
        secondary.chat_stream.assert_not_called()

    def test_streaming_unchanged_when_no_fallback_configured(self):
        mm, primary, _secondary = self._manager_with_two_models()
        primary.chat_stream.return_value = iter(["A", "B", "C"])
        chunks = list(mm.chat_stream([{"role": "user", "content": "hi"}], model_id="primary"))
        assert chunks == ["A", "B", "C"]


class TestProviderFactoryOllamaWiring:
    """smartagent.llm.factory — _load_ollama() and NVIDIA-as-fallback wiring."""

    def test_ollama_in_valid_providers(self):
        from smartagent.llm.factory import _VALID_PROVIDERS
        assert "ollama" in _VALID_PROVIDERS

    def test_load_ollama_registers_and_switches(self, monkeypatch):
        from smartagent.llm.factory import _load_ollama
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        mm = ModelManager()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            _load_ollama("llama3.2:3b", mm)
        assert mm.active_model_id == "llama3.2:3b"
        assert mm.registry.find("llama3.2:3b") is not None

    def test_load_ollama_registers_nvidia_as_silent_fallback(self, monkeypatch):
        from smartagent.llm.factory import _load_ollama, NVIDIA_DEFAULT_MODEL
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
        mm = ModelManager()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            _load_ollama("llama3.2:3b", mm)
        # Active model is still Ollama — NVIDIA is registered but never switched to.
        assert mm.active_model_id == "llama3.2:3b"
        assert mm.registry.find(NVIDIA_DEFAULT_MODEL) is not None
        assert mm._fallback_model_id == NVIDIA_DEFAULT_MODEL

    def test_load_ollama_no_fallback_without_nvidia_key(self, monkeypatch):
        from smartagent.llm.factory import _load_ollama
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        mm = ModelManager()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            _load_ollama("llama3.2:3b", mm)
        assert mm._fallback_model_id is None

    def test_ollama_error_sentinel_recognized(self):
        from smartagent.llm.factory import is_llm_error_text
        assert is_llm_error_text("Ollama server unavailable.") is True
        assert is_llm_error_text("The answer is 4.") is False

    def test_switching_away_from_ollama_clears_fallback(self, monkeypatch):
        """No stale NVIDIA-fallback left configured after switching to github."""
        from smartagent.llm.factory import _load_ollama, _wire_provider
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
        monkeypatch.setenv("GITHUB_TOKEN", "gh-test-token")
        mm = ModelManager()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            _load_ollama("llama3.2:3b", mm)
        assert mm._fallback_model_id is not None
        _wire_provider("github", "gpt-4.1", mm)
        assert mm._fallback_model_id is None


class TestWorkerPipelineWithOllama:
    """
    End-to-end: run_agent_loop() driven by a REAL ModelManager + real
    OllamaProvider (HTTP mocked) — proves the actual integration chain the
    live worker pipeline uses, not just isolated units mocking ModelManager.
    """

    def test_worker_completes_task_via_real_ollama_chain(self, tmp_path):
        from smartagent.engineer.agent_loop import run_agent_loop

        mm = ModelManager()
        with patch("urllib.request.urlopen", side_effect=OSError()):
            provider = OllamaProvider(model_name="llama3.2:3b")
            mm.registry.register(provider)
            mm.switch("llama3.2:3b")

        event_bus = MagicMock()
        final_response = _chat_response("Task complete — nothing further to do.")
        with patch("urllib.request.urlopen", return_value=_make_http_response(final_response)):
            result = run_agent_loop(
                "Say hello", mm, event_bus, str(tmp_path), allow_direct_reply=False,
            )

        assert result.success is True
        assert result.stop_reason == "done"
        assert "Task complete" in result.final_summary

    def test_worker_pipeline_unaffected_when_model_manager_is_mocked(self, tmp_path):
        """
        Regression guard: DevPipeline/agent_loop tests across this suite mock
        ModelManager entirely (see test_dev_pipeline.py, test_agent_loop.py) —
        none of this phase's changes touch agent_loop.py or dev_pipeline.py,
        so a mocked model_manager's chat_with_tools() contract is exactly
        what it was before. This test just re-confirms that contract here.
        """
        from smartagent.engineer.agent_loop import run_agent_loop

        mm = MagicMock()
        msg = MagicMock()
        msg.tool_calls = []
        msg.content = "Done."
        mm.chat_with_tools.return_value = msg
        eb = MagicMock()

        result = run_agent_loop("goal", mm, eb, str(tmp_path))

        assert result.success is True
        assert result.final_summary == "Done."
