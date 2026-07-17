"""
Tests for OpenAIProvider and AnthropicProvider.

All tests use unittest.mock — no real API calls are made.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_chat_response(content: str = "hello", model: str = "gpt-4o-mini") -> MagicMock:
    usage   = MagicMock(prompt_tokens=5, completion_tokens=3, total_tokens=8)
    choice  = MagicMock()
    choice.message.content = content
    choice.finish_reason   = "stop"
    resp    = MagicMock()
    resp.choices = [choice]
    resp.usage   = usage
    resp.model   = model
    return resp


def _make_stream_chunks(tokens: list[str]) -> list[MagicMock]:
    chunks = []
    for tok in tokens:
        delta  = MagicMock()
        delta.content = tok
        choice = MagicMock()
        choice.delta = delta
        chunk  = MagicMock()
        chunk.choices = [choice]
        chunks.append(chunk)
    return chunks


def _make_embed_response(dim: int = 1536) -> MagicMock:
    embedding = MagicMock()
    embedding.embedding = [0.1] * dim
    resp = MagicMock()
    resp.data = [embedding]
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAIProvider
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpenAIProviderInit:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY",       raising=False)
        monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL",      raising=False)
        # re-import so module-level defaults re-evaluate
        if "smartagent.llm.openai_provider" in sys.modules:
            del sys.modules["smartagent.llm.openai_provider"]
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider()
        assert p._model     == "gpt-4o-mini"
        assert p._api_key   == ""
        assert p._client    is None

    def test_explicit_args(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(model_name="gpt-4o", api_key="sk-test", base_url="https://custom")
        assert p._model    == "gpt-4o"
        assert p._api_key  == "sk-test"
        assert p._base_url == "https://custom"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider()
        assert p._api_key == "sk-from-env"

    def test_exclude_from_discovery(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        assert OpenAIProvider._exclude_from_discovery is True

    def test_load_raises_without_openai_package(self, monkeypatch):
        import builtins, importlib
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("no openai")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(api_key="sk-test")
        p._client = None
        with pytest.raises(RuntimeError, match="pip install openai"):
            p.load()


class TestOpenAIProviderChat:
    def setup_method(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        self.p = OpenAIProvider(model_name="gpt-4o-mini", api_key="sk-test")
        self.mock_client = MagicMock()
        self.p._client   = self.mock_client

    def test_chat_returns_content(self):
        self.mock_client.chat.completions.create.return_value = _make_chat_response("world")
        result = self.p.chat([{"role": "user", "content": "hello"}])
        assert result["content"]       == "world"
        assert result["finish_reason"] == "stop"
        assert result["model"]         == "gpt-4o-mini"

    def test_chat_usage_fields(self):
        self.mock_client.chat.completions.create.return_value = _make_chat_response()
        result = self.p.chat([{"role": "user", "content": "hi"}])
        assert "usage" in result
        assert result["usage"]["prompt_tokens"]     == 5
        assert result["usage"]["completion_tokens"] == 3
        assert result["usage"]["total_tokens"]      == 8

    def test_chat_passes_temperature(self):
        self.mock_client.chat.completions.create.return_value = _make_chat_response()
        self.p.chat([{"role": "user", "content": "hi"}], temperature=0.2)
        call = self.mock_client.chat.completions.create.call_args
        assert call.kwargs["temperature"] == 0.2

    def test_chat_passes_max_tokens(self):
        self.mock_client.chat.completions.create.return_value = _make_chat_response()
        self.p.chat([{"role": "user", "content": "hi"}], max_tokens=100)
        call = self.mock_client.chat.completions.create.call_args
        assert call.kwargs["max_tokens"] == 100

    def test_chat_stream_false(self):
        self.mock_client.chat.completions.create.return_value = _make_chat_response()
        self.p.chat([{"role": "user", "content": "hi"}])
        call = self.mock_client.chat.completions.create.call_args
        assert call.kwargs["stream"] is False

    def test_generate_alias(self):
        self.mock_client.chat.completions.create.return_value = _make_chat_response("alias")
        result = self.p.generate("prompt text")
        assert result["content"] == "alias"


class TestOpenAIProviderStreamChat:
    def setup_method(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        self.p = OpenAIProvider(model_name="gpt-4o-mini", api_key="sk-test")
        self.mock_client = MagicMock()
        self.p._client   = self.mock_client

    def test_stream_yields_tokens(self):
        chunks = _make_stream_chunks(["Hello", " world"])
        self.mock_client.chat.completions.create.return_value = iter(chunks)
        tokens = list(self.p.stream_chat([{"role": "user", "content": "hi"}]))
        assert tokens == ["Hello", " world"]

    def test_stream_skips_none_content(self):
        # chunk with delta.content = None
        delta  = MagicMock(); delta.content = None
        choice = MagicMock(); choice.delta  = delta
        chunk  = MagicMock(); chunk.choices = [choice]
        self.mock_client.chat.completions.create.return_value = iter([chunk])
        tokens = list(self.p.stream_chat([{"role": "user", "content": "hi"}]))
        assert tokens == []

    def test_stream_passes_stream_true(self):
        self.mock_client.chat.completions.create.return_value = iter([])
        list(self.p.stream_chat([{"role": "user", "content": "hi"}]))
        call = self.mock_client.chat.completions.create.call_args
        assert call.kwargs["stream"] is True


class TestOpenAIProviderEmbed:
    def setup_method(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        self.p = OpenAIProvider(api_key="sk-test")
        self.mock_client = MagicMock()
        self.p._client   = self.mock_client

    def test_embed_returns_list(self):
        self.mock_client.embeddings.create.return_value = _make_embed_response(1536)
        vec = self.p.embed("hello")
        assert isinstance(vec, list)
        assert len(vec) == 1536

    def test_embeddings_alias(self):
        self.mock_client.embeddings.create.return_value = _make_embed_response(1536)
        vec = self.p.embeddings("hello")
        assert len(vec) == 1536

    def test_embed_uses_embed_model(self):
        self.mock_client.embeddings.create.return_value = _make_embed_response()
        self.p.embed("test")
        call = self.mock_client.embeddings.create.call_args
        assert "text-embedding" in call.kwargs["model"]


class TestOpenAIProviderListModels:
    def setup_method(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        self.p = OpenAIProvider(api_key="sk-test")
        self.mock_client = MagicMock()
        self.p._client   = self.mock_client

    def test_list_models_filters_gpt(self):
        m1 = MagicMock(); m1.id = "gpt-4o"
        m2 = MagicMock(); m2.id = "gpt-3.5-turbo"
        m3 = MagicMock(); m3.id = "text-embedding-3-small"
        m4 = MagicMock(); m4.id = "babbage-002"   # should be excluded
        models = MagicMock(); models.data = [m1, m2, m3, m4]
        self.mock_client.models.list.return_value = models
        result = self.p.list_models()
        ids = [r["id"] for r in result]
        assert "gpt-4o" in ids
        assert "text-embedding-3-small" in ids
        assert "babbage-002" not in ids

    def test_list_models_returns_empty_on_error(self):
        self.mock_client.models.list.side_effect = Exception("network error")
        result = self.p.list_models()
        assert result == []

    def test_list_models_provider_field(self):
        m = MagicMock(); m.id = "gpt-4o"
        models = MagicMock(); models.data = [m]
        self.mock_client.models.list.return_value = models
        result = self.p.list_models()
        assert result[0]["provider"] == "openai"


class TestOpenAIProviderHealth:
    def test_health_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(api_key="")
        h = p.health()
        assert h["healthy"] is False
        assert "OPENAI_API_KEY" in h["message"]

    def test_health_ok(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(api_key="sk-test")
        mock_client = MagicMock()
        p._client = mock_client
        mock_client.chat.completions.create.return_value = _make_chat_response()
        h = p.health()
        assert h["healthy"] is True
        assert "reachable" in h["message"].lower()
        assert "latency" in h["message"].lower() or "ms" in h["message"].lower()

    def test_health_error(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(api_key="sk-bad")
        mock_client = MagicMock()
        p._client = mock_client
        mock_client.chat.completions.create.side_effect = Exception("401 auth failed")
        h = p.health()
        assert h["healthy"] is False
        assert "401" in h["message"]


class TestOpenAIProviderSwitchModel:
    def test_switch_model(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(model_name="gpt-4o-mini", api_key="sk-test")
        p.switch_model("gpt-4o")
        assert p._model == "gpt-4o"

    def test_switch_model_does_not_reload(self):
        from smartagent.llm.openai_provider import OpenAIProvider
        p = OpenAIProvider(api_key="sk-test")
        mock_client = MagicMock()
        p._client = mock_client
        p.switch_model("gpt-4o")
        # client should not have been replaced
        assert p._client is mock_client


# ═══════════════════════════════════════════════════════════════════════════════
# AnthropicProvider
# ═══════════════════════════════════════════════════════════════════════════════

def _make_anthropic_response(text: str = "hello") -> MagicMock:
    block    = MagicMock(); block.text = text
    usage    = MagicMock(); usage.input_tokens = 4; usage.output_tokens = 2
    response = MagicMock()
    response.content     = [block]
    response.usage       = usage
    response.stop_reason = "end_turn"
    return response


class TestAnthropicProviderInit:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY",       raising=False)
        monkeypatch.delenv("ANTHROPIC_DEFAULT_MODEL", raising=False)
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider()
        assert "claude" in p._model
        assert p._api_key == ""
        assert p._client  is None

    def test_explicit_key(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        assert p._api_key == "sk-ant-test"

    def test_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider()
        assert p._api_key == "sk-ant-env"

    def test_exclude_from_discovery(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        assert AnthropicProvider._exclude_from_discovery is True

    def test_load_raises_without_anthropic_package(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("no anthropic")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        p._client = None
        with pytest.raises(RuntimeError, match="pip install anthropic"):
            p.load()


class TestAnthropicProviderChat:
    def setup_method(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        self.p = AnthropicProvider(api_key="sk-ant-test")
        self.mock_client = MagicMock()
        self.p._client   = self.mock_client

    def test_chat_returns_content(self):
        self.mock_client.messages.create.return_value = _make_anthropic_response("claude says hi")
        result = self.p.chat([{"role": "user", "content": "hello"}])
        assert result["content"]       == "claude says hi"
        assert result["finish_reason"] == "end_turn"

    def test_chat_usage_fields(self):
        self.mock_client.messages.create.return_value = _make_anthropic_response()
        result = self.p.chat([{"role": "user", "content": "hi"}])
        assert result["usage"]["prompt_tokens"]     == 4
        assert result["usage"]["completion_tokens"] == 2
        assert result["usage"]["total_tokens"]      == 6

    def test_chat_system_message_extracted(self):
        self.mock_client.messages.create.return_value = _make_anthropic_response()
        self.p.chat([
            {"role": "system",  "content": "You are helpful."},
            {"role": "user",    "content": "hi"},
        ])
        call = self.mock_client.messages.create.call_args
        assert call.kwargs.get("system") == "You are helpful."
        # system message must not appear in messages list
        assert all(m["role"] != "system" for m in call.kwargs["messages"])

    def test_chat_no_system_message(self):
        self.mock_client.messages.create.return_value = _make_anthropic_response()
        self.p.chat([{"role": "user", "content": "hi"}])
        call = self.mock_client.messages.create.call_args
        # no system kwarg when absent
        assert "system" not in call.kwargs or call.kwargs["system"] == ""

    def test_chat_model_in_response(self):
        self.mock_client.messages.create.return_value = _make_anthropic_response()
        result = self.p.chat([{"role": "user", "content": "hi"}])
        assert "claude" in result["model"].lower()

    def test_generate_alias(self):
        self.mock_client.messages.create.return_value = _make_anthropic_response("alias")
        result = self.p.generate("prompt text")
        assert result["content"] == "alias"


class TestAnthropicProviderStreamChat:
    def setup_method(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        self.p = AnthropicProvider(api_key="sk-ant-test")
        self.mock_client = MagicMock()
        self.p._client   = self.mock_client

    def test_stream_yields_tokens(self):
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=ctx_mgr)
        ctx_mgr.__exit__  = MagicMock(return_value=False)
        ctx_mgr.text_stream = iter(["Hello", " Claude"])
        self.mock_client.messages.stream.return_value = ctx_mgr
        tokens = list(self.p.stream_chat([{"role": "user", "content": "hi"}]))
        assert tokens == ["Hello", " Claude"]

    def test_stream_system_extracted(self):
        ctx_mgr = MagicMock()
        ctx_mgr.__enter__ = MagicMock(return_value=ctx_mgr)
        ctx_mgr.__exit__  = MagicMock(return_value=False)
        ctx_mgr.text_stream = iter([])
        self.mock_client.messages.stream.return_value = ctx_mgr
        list(self.p.stream_chat([
            {"role": "system", "content": "Be helpful."},
            {"role": "user",   "content": "hi"},
        ]))
        call = self.mock_client.messages.stream.call_args
        assert call.kwargs.get("system") == "Be helpful."


class TestAnthropicProviderEmbed:
    def test_embed_raises_without_openai(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        with pytest.raises(NotImplementedError, match="embeddings natively"):
            p.embed("hello")

    def test_embed_uses_openai_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        mock_openai_module = types.ModuleType("openai")
        mock_client_inst   = MagicMock()
        embedding_obj      = MagicMock(); embedding_obj.embedding = [0.1] * 1536
        mock_client_inst.embeddings.create.return_value = MagicMock(data=[embedding_obj])
        mock_openai_module.OpenAI = MagicMock(return_value=mock_client_inst)

        with patch.dict(sys.modules, {"openai": mock_openai_module}):
            from smartagent.llm.anthropic_provider import AnthropicProvider
            p = AnthropicProvider(api_key="sk-ant-test")
            vec = p.embed("hello world")
        assert len(vec) == 1536

    def test_embeddings_alias_raises_without_openai(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        with pytest.raises(NotImplementedError):
            p.embeddings("hello")


class TestAnthropicProviderListModels:
    def test_list_models_returns_known(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        models = p.list_models()
        assert len(models) > 0
        ids = [m["id"] for m in models]
        assert any("claude" in m_id for m_id in ids)

    def test_list_models_provider_field(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        for m in p.list_models():
            assert m["provider"] == "anthropic"

    def test_list_models_immutable(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p  = AnthropicProvider(api_key="sk-ant-test")
        m1 = p.list_models()
        m1.clear()
        m2 = p.list_models()
        assert len(m2) > 0  # original list not mutated


class TestAnthropicProviderHealth:
    def test_health_no_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="")
        h = p.health()
        assert h["healthy"] is False
        assert "ANTHROPIC_API_KEY" in h["message"]

    def test_health_ok(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        mock_client = MagicMock()
        p._client   = mock_client
        mock_client.messages.create.return_value = _make_anthropic_response()
        h = p.health()
        assert h["healthy"] is True
        assert "reachable" in h["message"].lower()

    def test_health_error(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-bad")
        mock_client = MagicMock()
        p._client   = mock_client
        mock_client.messages.create.side_effect = Exception("401 unauthorized")
        h = p.health()
        assert h["healthy"] is False
        assert "401" in h["message"]


class TestAnthropicProviderSwitchModel:
    def test_switch_model(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        orig = p._model
        p.switch_model("claude-3-opus-20240229")
        assert p._model == "claude-3-opus-20240229"
        assert p._model != orig

    def test_switch_model_no_reload(self):
        from smartagent.llm.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(api_key="sk-ant-test")
        mock_client = MagicMock()
        p._client = mock_client
        p.switch_model("claude-3-5-sonnet-20241022")
        assert p._client is mock_client


# ═══════════════════════════════════════════════════════════════════════════════
# Factory — OpenAI / Anthropic wiring
# ═══════════════════════════════════════════════════════════════════════════════

class TestFactoryOpenAIAnthropic:
    def test_auto_detect_prefers_github_over_openai(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN",    "ghp_test")
        monkeypatch.setenv("OPENAI_API_KEY",  "sk-test")
        assert fac._auto_default_provider() == "github"

    def test_auto_detect_openai_when_no_github(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN",    raising=False)
        monkeypatch.setenv("OPENAI_API_KEY",  "sk-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert fac._auto_default_provider() == "openai"

    def test_auto_detect_anthropic_when_no_github_or_openai(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.delenv("ACTIVE_PROVIDER",  raising=False)
        monkeypatch.delenv("GITHUB_TOKEN",     raising=False)
        monkeypatch.delenv("OPENAI_API_KEY",   raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert fac._auto_default_provider() == "anthropic"

    def test_auto_detect_falls_back_to_ollama(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.delenv("ACTIVE_PROVIDER",  raising=False)
        monkeypatch.delenv("GITHUB_TOKEN",     raising=False)
        monkeypatch.delenv("OPENAI_API_KEY",   raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert fac._auto_default_provider() == "ollama"

    def test_active_provider_env_overrides_all(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.setenv("ACTIVE_PROVIDER",  "anthropic")
        monkeypatch.setenv("GITHUB_TOKEN",     "ghp_test")
        monkeypatch.setenv("OPENAI_API_KEY",   "sk-test")
        assert fac._auto_default_provider() == "anthropic"

    def test_switch_provider_openai(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        settings = fac.switch_provider("openai", model="gpt-4o", model_manager=None)
        assert settings["provider"] == "openai"
        assert settings["model"]    == "gpt-4o"

    def test_switch_provider_anthropic(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        settings = fac.switch_provider("anthropic", model="claude-3-5-haiku-20241022", model_manager=None)
        assert settings["provider"] == "anthropic"
        assert settings["model"]    == "claude-3-5-haiku-20241022"

    def test_switch_provider_persists_openai_model_key(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        fac.switch_provider("openai", model="gpt-4o", model_manager=None)
        state = fac._load_state()
        assert state.get("openai_model") == "gpt-4o"
        # should NOT pollute the ollama model key
        assert state.get("ollama_model") != "gpt-4o"

    def test_switch_provider_persists_anthropic_model_key(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        fac.switch_provider("anthropic", model="claude-3-opus-20240229", model_manager=None)
        state = fac._load_state()
        assert state.get("anthropic_model") == "claude-3-opus-20240229"

    def test_get_llm_settings_openai_fields(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.setenv("OPENAI_API_KEY",  "sk-test")
        monkeypatch.delenv("GITHUB_TOKEN",    raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        fac.switch_provider("openai", model_manager=None)
        settings = fac.get_llm_settings()
        assert settings["provider"]          == "openai"
        assert settings["openai_available"]  is True
        assert "model" in settings

    def test_get_llm_settings_anthropic_fields(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        fac.switch_provider("anthropic", model_manager=None)
        settings = fac.get_llm_settings()
        assert settings["provider"]              == "anthropic"
        assert settings["anthropic_available"]   is True

    def test_get_llm_settings_availability_flags(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.setenv("GITHUB_TOKEN",      "ghp_t")
        monkeypatch.setenv("OPENAI_API_KEY",    "sk-t")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-t")
        fac.switch_provider("github", model_manager=None)
        settings = fac.get_llm_settings()
        assert settings["github_available"]    is True
        assert settings["openai_available"]    is True
        assert settings["anthropic_available"] is True

    def test_switch_provider_invalid_still_raises(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        with pytest.raises(ValueError, match="Unknown provider"):
            fac.switch_provider("gemini", model_manager=None)

    def test_all_four_providers_accepted(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        for provider in ("github", "ollama", "openai", "anthropic"):
            monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / f".state_{provider}.json")
            settings = fac.switch_provider(provider, model_manager=None)
            assert settings["provider"] == provider

    def test_default_model_openai(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)
        fac.switch_provider("openai", model_manager=None)
        settings = fac.get_llm_settings()
        assert settings["model"] == "gpt-4o-mini"

    def test_default_model_anthropic(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.delenv("ANTHROPIC_DEFAULT_MODEL", raising=False)
        fac.switch_provider("anthropic", model_manager=None)
        settings = fac.get_llm_settings()
        assert "claude" in settings["model"]

    def test_default_model_openai_from_env(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "gpt-4o")
        fac.switch_provider("openai", model_manager=None)
        settings = fac.get_llm_settings()
        assert settings["model"] == "gpt-4o"

    def test_wire_provider_openai_no_op_in_model_manager(self, monkeypatch, tmp_path):
        """OpenAI + Anthropic don't register in ModelManager — _wire_provider must not crash."""
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        mock_mm = MagicMock()
        # should not raise
        fac.switch_provider("openai",     model_manager=mock_mm)
        fac.switch_provider("anthropic",  model_manager=mock_mm)
        # ModelManager load/switch should NOT have been called for REST-only providers
        mock_mm.load_model.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Provider REST endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestProvidersEndpoints:
    @pytest.fixture(autouse=True)
    def client(self):
        from fastapi.testclient import TestClient
        from smartagent.server.app import app
        return TestClient(app, raise_server_exceptions=False)

    def test_get_providers_includes_four(self, client):
        resp = client.get("/providers")
        assert resp.status_code == 200
        data = resp.json()
        providers = data if isinstance(data, list) else data.get("providers", [])
        ids = [p["id"] for p in providers]
        for expected in ("github", "ollama", "openai", "anthropic"):
            assert expected in ids, f"Missing provider: {expected}"

    def test_get_providers_have_capabilities(self, client):
        resp = client.get("/providers")
        assert resp.status_code == 200
        data = resp.json()
        providers = data if isinstance(data, list) else data.get("providers", [])
        for p in providers:
            assert "capabilities" in p
            assert isinstance(p["capabilities"], list)

    def test_get_providers_have_token_env(self, client):
        resp = client.get("/providers")
        assert resp.status_code == 200
        data = resp.json()
        providers = data if isinstance(data, list) else data.get("providers", [])
        by_id = {p["id"]: p for p in providers}
        assert by_id["openai"]["token_env"]    == "OPENAI_API_KEY"
        assert by_id["anthropic"]["token_env"] == "ANTHROPIC_API_KEY"
        assert by_id["github"]["token_env"]    == "GITHUB_TOKEN"
        assert by_id["ollama"]["requires_token"] is False

    def test_get_current_provider_returns_provider_field(self, client):
        resp = client.get("/providers/current")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data

    def test_switch_provider_openai_via_api(self, client, monkeypatch, tmp_path):
        import smartagent.server.api_providers as apv
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        resp = client.post(
            "/providers/switch",
            json={"provider": "openai", "model": "gpt-4o-mini"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("provider") == "openai"

    def test_switch_provider_anthropic_via_api(self, client, monkeypatch, tmp_path):
        import smartagent.llm.factory as fac
        monkeypatch.setattr(fac, "_STATE_FILE", tmp_path / ".state.json")
        resp = client.post(
            "/providers/switch",
            json={"provider": "anthropic", "model": "claude-3-5-haiku-20241022"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("provider") == "anthropic"

    def test_switch_provider_invalid_returns_4xx(self, client):
        resp = client.post(
            "/providers/switch",
            json={"provider": "gemini"},
        )
        assert resp.status_code in (400, 422, 500)
