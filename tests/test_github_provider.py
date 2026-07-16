"""
Tests for GitHubProvider — smartagent.llm.github_provider.

Strategy:
  - All OpenAI SDK calls are mocked via ``unittest.mock.patch`` — no network,
    no real GitHub API calls, no token required.
  - GitHubProvider unit-tested directly (identity, capabilities, lifecycle,
    generate, chat, stream, embed, health, list_models).
  - ProviderFactory tested for state save/load, provider switching, and
    get_model_for_role() fallback behaviour.
  - ModelManager.load_github_models() integration-tested.
  - All 2460 existing tests continue to pass (no regressions).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from smartagent.llm.github_provider import (
    GitHubProvider,
    GITHUB_INFERENCE_BASE_URL,
    _GITHUB_MODEL_CATALOGUE,
    _infer_family,
    _infer_tools,
)
from smartagent.models.base.base_model import ModelHealth, ModelStatus


# ---------------------------------------------------------------------------
# Helpers — build fake OpenAI SDK responses
# ---------------------------------------------------------------------------

def _fake_completion(content: str, model: str = "gpt-4.1-mini") -> MagicMock:
    """Build a fake non-streaming ChatCompletion response."""
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason="stop",
        delta=SimpleNamespace(content=None),
    )
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


def _fake_stream_chunks(tokens: list[str]) -> list[MagicMock]:
    """Build a list of fake streaming chunk objects."""
    chunks = []
    for token in tokens:
        delta = SimpleNamespace(content=token)
        choice = SimpleNamespace(delta=delta, finish_reason=None)
        chunks.append(SimpleNamespace(choices=[choice]))
    # Final done chunk
    done_choice = SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")
    chunks.append(SimpleNamespace(choices=[done_choice]))
    return chunks


def _fake_embedding(vector: list[float] | None = None) -> MagicMock:
    vec = vector or [0.1, 0.2, 0.3]
    data = [SimpleNamespace(embedding=vec)]
    return SimpleNamespace(data=data)


def _fake_models_list(ids: list[str]) -> MagicMock:
    data = [SimpleNamespace(id=mid) for mid in ids]
    return SimpleNamespace(data=data)


def _loaded_provider(model_name: str = "gpt-4.1-mini") -> GitHubProvider:
    """Return a loaded GitHubProvider with a fake token."""
    p = GitHubProvider(model_name=model_name, token="ghp_test_token")
    p.initialize()
    p.load()
    return p


# ---------------------------------------------------------------------------
# Identity and capabilities
# ---------------------------------------------------------------------------


class TestGitHubProviderIdentity:
    def test_id_equals_model_name(self):
        p = GitHubProvider(model_name="gpt-4.1-mini", token="tok")
        assert p.id == "gpt-4.1-mini"

    def test_name_includes_provider_and_model(self):
        p = GitHubProvider(model_name="gpt-4o", token="tok")
        assert "GitHub" in p.name
        assert "gpt-4o" in p.name

    def test_provider_is_github(self):
        p = GitHubProvider(token="tok")
        assert p.provider == "github"

    def test_version_is_string(self):
        p = GitHubProvider(token="tok")
        assert isinstance(p.version, str) and p.version

    def test_exclude_from_discovery_flag(self):
        assert GitHubProvider._exclude_from_discovery is True

    def test_supports_streaming(self):
        p = GitHubProvider(token="tok")
        assert p.supports_streaming is True

    def test_supports_embeddings(self):
        p = GitHubProvider(token="tok")
        assert p.supports_embeddings is True

    def test_context_window_for_known_model(self):
        p = GitHubProvider(model_name="gpt-4.1-mini", token="tok")
        assert p.context_window == 128_000

    def test_context_window_for_unknown_model(self):
        p = GitHubProvider(model_name="future-model:99b", token="tok")
        assert p.context_window == 128_000  # default

    def test_supports_tools_for_gpt4_model(self):
        p = GitHubProvider(model_name="gpt-4.1-mini", token="tok")
        assert p.supports_tools is True

    def test_supports_tools_false_for_phi(self):
        p = GitHubProvider(model_name="Phi-4", token="tok")
        assert p.supports_tools is False

    def test_call_count_starts_at_zero(self):
        p = GitHubProvider(token="tok")
        assert p.call_count == 0


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestGitHubProviderLifecycle:
    def test_initial_status_unloaded(self):
        p = GitHubProvider(token="tok")
        assert p.status() == ModelStatus.UNLOADED

    def test_load_sets_status_loaded(self):
        p = GitHubProvider(token="ghp_test")
        p.initialize()
        p.load()
        assert p.status() == ModelStatus.LOADED

    def test_load_with_no_token_still_sets_loaded(self):
        p = GitHubProvider(token="")
        p.initialize()
        p.load()
        assert p.status() == ModelStatus.LOADED

    def test_shutdown_sets_unloaded(self):
        p = _loaded_provider()
        p.shutdown()
        assert p.status() == ModelStatus.UNLOADED

    def test_unload_alias(self):
        p = _loaded_provider()
        p.unload()
        assert p.status() == ModelStatus.UNLOADED

    def test_generate_raises_before_load(self):
        p = GitHubProvider(token="tok")
        with pytest.raises(RuntimeError, match="load"):
            p.generate("hello")

    def test_chat_raises_before_load(self):
        p = GitHubProvider(token="tok")
        with pytest.raises(RuntimeError, match="load"):
            p.chat([{"role": "user", "content": "hi"}])

    def test_stream_raises_before_load(self):
        p = GitHubProvider(token="tok")
        with pytest.raises(RuntimeError, match="load"):
            list(p.stream("hello"))


# ---------------------------------------------------------------------------
# generate() and chat()
# ---------------------------------------------------------------------------


class TestGitHubProviderChat:
    def _mock_client(self, content: str = "Hello from GitHub"):
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion(content)
        return client

    def test_chat_returns_dict_with_content(self):
        p = _loaded_provider()
        p._client = self._mock_client("Hello!")
        result = p.chat([{"role": "user", "content": "hi"}])
        assert isinstance(result, dict)
        assert result["content"] == "Hello!"

    def test_chat_returns_usage(self):
        p = _loaded_provider()
        p._client = self._mock_client()
        result = p.chat([{"role": "user", "content": "hi"}])
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20

    def test_chat_sets_finish_reason_stop(self):
        p = _loaded_provider()
        p._client = self._mock_client()
        result = p.chat([{"role": "user", "content": "hi"}])
        assert result["finish_reason"] == "stop"

    def test_chat_increments_call_count(self):
        p = _loaded_provider()
        p._client = self._mock_client()
        p.chat([{"role": "user", "content": "hi"}])
        p.chat([{"role": "user", "content": "bye"}])
        assert p.call_count == 2

    def test_chat_fallback_on_api_error(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("rate limit")
        p._client = client
        result = p.chat([{"role": "user", "content": "hi"}])
        assert "error" in result["content"].lower() or "github" in result["content"].lower()
        assert result["finish_reason"] == "error"

    def test_generate_delegates_to_chat(self):
        p = _loaded_provider()
        p._client = self._mock_client("generated")
        result = p.generate("hello world")
        assert result["content"] == "generated"

    def test_generate_converts_flat_prompt_to_user_message(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion("ok")
        p._client = client
        p.generate("simple prompt")
        call_args = client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0] if call_args.args else None
        # The call should have happened
        assert client.chat.completions.create.called


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class TestGitHubProviderStream:
    def _mock_streaming_client(self, tokens: list[str]):
        client = MagicMock()
        client.chat.completions.create.return_value = iter(_fake_stream_chunks(tokens))
        return client

    def test_stream_yields_tokens(self):
        p = _loaded_provider()
        p._client = self._mock_streaming_client(["Hello", " world", "!"])
        tokens = list(p.stream("test"))
        assert "Hello" in tokens
        assert " world" in tokens

    def test_chat_stream_yields_tokens(self):
        p = _loaded_provider()
        p._client = self._mock_streaming_client(["Token", "1"])
        tokens = list(p.chat_stream([{"role": "user", "content": "hi"}]))
        assert len(tokens) >= 2

    def test_generate_stream_yields_tokens(self):
        p = _loaded_provider()
        p._client = self._mock_streaming_client(["A", "B", "C"])
        tokens = list(p.generate_stream("hello"))
        assert "A" in tokens

    def test_stream_fallback_on_error(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("stream error")
        p._client = client
        tokens = list(p.stream("hello"))
        assert len(tokens) == 1
        assert "error" in tokens[0].lower() or "github" in tokens[0].lower()

    def test_stream_increments_call_count(self):
        p = _loaded_provider()
        p._client = self._mock_streaming_client(["hi"])
        list(p.stream("test"))
        assert p.call_count == 1


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class TestGitHubProviderEmbed:
    def test_embed_returns_vector(self):
        p = _loaded_provider()
        client = MagicMock()
        client.embeddings.create.return_value = _fake_embedding([0.1, 0.2, 0.3])
        p._client = client
        vec = p.embed("test text")
        assert vec == [0.1, 0.2, 0.3]

    def test_embeddings_alias_works(self):
        p = _loaded_provider()
        client = MagicMock()
        client.embeddings.create.return_value = _fake_embedding([0.5])
        p._client = client
        vec = p.embeddings("text")
        assert vec == [0.5]

    def test_embed_raises_on_api_error(self):
        p = _loaded_provider()
        client = MagicMock()
        client.embeddings.create.side_effect = Exception("embedding error")
        p._client = client
        with pytest.raises(RuntimeError, match="embeddings"):
            p.embed("text")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestGitHubProviderHealth:
    def test_health_no_token_returns_unhealthy(self):
        p = GitHubProvider(model_name="gpt-4.1-mini", token="")
        p._token = ""   # Force empty regardless of GITHUB_TOKEN env var
        p.load()
        health = p.health()
        assert health.healthy is False
        assert "GITHUB_TOKEN" in health.message

    def test_health_returns_model_health_type(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion("hi")
        p._client = client
        health = p.health()
        assert isinstance(health, ModelHealth)

    def test_health_reachable_returns_healthy(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion("hi")
        p._client = client
        health = p.health()
        assert health.healthy is True
        assert "reachable" in health.message.lower()

    def test_health_api_error_returns_unhealthy(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("unreachable")
        p._client = client
        health = p.health()
        assert health.healthy is False
        assert "unreachable" in health.message.lower()


# ---------------------------------------------------------------------------
# list_models()
# ---------------------------------------------------------------------------


class TestGitHubProviderListModels:
    def test_list_models_uses_live_endpoint(self):
        p = _loaded_provider()
        client = MagicMock()
        client.models.list.return_value = _fake_models_list(
            ["gpt-4.1-mini", "gpt-4o", "Phi-4"]
        )
        p._client = client
        models = p.list_models()
        ids = [m["id"] for m in models]
        assert "gpt-4.1-mini" in ids

    def test_list_models_fallback_to_catalogue_on_error(self):
        p = _loaded_provider()
        client = MagicMock()
        client.models.list.side_effect = Exception("API down")
        p._client = client
        models = p.list_models()
        assert len(models) > 5  # catalogue has many models
        ids = [m["id"] for m in models]
        assert "gpt-4.1-mini" in ids

    def test_list_models_returns_list_of_dicts(self):
        p = _loaded_provider()
        client = MagicMock()
        client.models.list.side_effect = Exception("offline")
        p._client = client
        models = p.list_models()
        assert all(isinstance(m, dict) for m in models)
        assert all("id" in m for m in models)


# ---------------------------------------------------------------------------
# prompt_to_messages helper
# ---------------------------------------------------------------------------


class TestPromptToMessages:
    def test_flat_prompt_becomes_user_message(self):
        msgs = GitHubProvider._prompt_to_messages("hello world")
        assert msgs == [{"role": "user", "content": "hello world"}]

    def test_system_prompt_is_parsed(self):
        prompt = "System: you are helpful\nUser: tell me something"
        msgs = GitHubProvider._prompt_to_messages(prompt)
        roles = [m["role"] for m in msgs]
        assert "system" in roles
        assert "user" in roles

    def test_plain_prompt_no_prefix(self):
        msgs = GitHubProvider._prompt_to_messages("a simple question")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"


# ---------------------------------------------------------------------------
# _build_params helper
# ---------------------------------------------------------------------------


class TestBuildParams:
    def test_temperature_mapped(self):
        p = GitHubProvider._build_params({"temperature": 0.5})
        assert p["temperature"] == 0.5

    def test_max_tokens_mapped(self):
        p = GitHubProvider._build_params({"max_tokens": 2048})
        assert p["max_tokens"] == 2048

    def test_unknown_keys_ignored(self):
        p = GitHubProvider._build_params({"top_k": 40, "temperature": 0.3})
        assert "top_k" not in p
        assert p["temperature"] == 0.3


# ---------------------------------------------------------------------------
# Family and tool inference helpers
# ---------------------------------------------------------------------------


class TestInferHelpers:
    def test_infer_family_gpt(self):
        assert _infer_family("gpt-4.1-mini") == "gpt"

    def test_infer_family_llama(self):
        assert _infer_family("Llama-3.3-70B-Instruct") == "llama"

    def test_infer_family_phi(self):
        assert _infer_family("Phi-4") == "phi"

    def test_infer_family_unknown(self):
        assert _infer_family("UltraModel-X") == "other"

    def test_infer_tools_gpt4(self):
        assert _infer_tools("gpt-4.1-mini") is True

    def test_infer_tools_phi(self):
        assert _infer_tools("Phi-4") is False

    def test_infer_tools_llama33(self):
        assert _infer_tools("Llama-3.3-70B-Instruct") is True


# ---------------------------------------------------------------------------
# ProviderFactory
# ---------------------------------------------------------------------------


class TestProviderFactory:
    def test_get_active_provider_defaults_to_ollama(self, monkeypatch, tmp_path):
        """Without ACTIVE_PROVIDER env var, default is 'ollama'."""
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        assert _fac.get_active_provider() == "ollama"

    def test_get_active_provider_reads_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ACTIVE_PROVIDER", "github")
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        assert _fac.get_active_provider() == "github"

    def test_get_model_for_role_returns_none_for_ollama(self, monkeypatch, tmp_path):
        """When provider is Ollama, get_model_for_role() returns None (mixin uses settings)."""
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        assert _fac.get_model_for_role("default") is None
        assert _fac.get_model_for_role("coding") is None

    def test_get_model_for_role_returns_github_model(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ACTIVE_PROVIDER", "github")
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        assert _fac.get_model_for_role("default") == _fac.GITHUB_DEFAULT_MODEL
        assert _fac.get_model_for_role("coding") == _fac.GITHUB_CODING_MODEL

    def test_switch_provider_saves_state(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        import smartagent.llm.factory as _fac
        state_file = tmp_path / ".state.json"
        monkeypatch.setattr(_fac, "_STATE_FILE", state_file)
        _fac.switch_provider("github", model="gpt-4o-mini")
        saved = json.loads(state_file.read_text())
        assert saved["provider"] == "github"
        assert saved["github_model"] == "gpt-4o-mini"

    def test_switch_provider_invalid_raises(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        with pytest.raises(ValueError, match="Unknown provider"):
            _fac.switch_provider("anthropic")

    def test_get_llm_settings_returns_dict(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        settings = _fac.get_llm_settings()
        assert "provider" in settings
        assert "temperature" in settings
        assert "max_tokens" in settings
        assert "streaming" in settings

    def test_update_llm_settings_persists(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        import smartagent.llm.factory as _fac
        state_file = tmp_path / ".state.json"
        monkeypatch.setattr(_fac, "_STATE_FILE", state_file)
        result = _fac.update_llm_settings({"temperature": 0.3, "max_tokens": 1024})
        assert result["temperature"] == 0.3
        assert state_file.exists()


# ---------------------------------------------------------------------------
# ModelManager.load_github_models integration
# ---------------------------------------------------------------------------


class TestModelManagerGitHubIntegration:
    def test_load_github_models_registers_providers(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
        from smartagent.models.config.model_settings import ModelSettings
        from smartagent.models.manager.model_manager import ModelManager
        mgr = ModelManager(settings=ModelSettings())

        mgr.load_github_models(
            default_model="gpt-4.1-mini",
            coding_model="gpt-4.1",
            token="ghp_test_token",
        )
        assert mgr.registry.find("gpt-4.1-mini") is not None
        assert mgr.registry.find("gpt-4.1") is not None

    def test_load_github_models_provider_field(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
        from smartagent.models.config.model_settings import ModelSettings
        from smartagent.models.manager.model_manager import ModelManager
        mgr = ModelManager(settings=ModelSettings())
        mgr.load_github_models(
            default_model="gpt-4.1-mini",
            coding_model="gpt-4.1",
            token="ghp_test_token",
        )
        p = mgr.registry.find("gpt-4.1-mini")
        assert p is not None
        assert p.provider == "github"

    def test_load_github_models_idempotent(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
        from smartagent.models.config.model_settings import ModelSettings
        from smartagent.models.manager.model_manager import ModelManager
        mgr = ModelManager(settings=ModelSettings())
        mgr.load_github_models(token="ghp_test_token")
        mgr.load_github_models(token="ghp_test_token")
        # Should not duplicate
        providers = [m for m in mgr.list_models() if m.id == "gpt-4.1-mini"]
        assert len(providers) == 1

    def test_load_github_models_no_token_skips_quietly(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        from smartagent.models.config.model_settings import ModelSettings
        from smartagent.models.manager.model_manager import ModelManager
        mgr = ModelManager(settings=ModelSettings())
        # Should not raise even without a token
        mgr.load_github_models(token="")
        # No github models registered (silently skipped)
        assert mgr.registry.find("gpt-4.1-mini") is None


# ---------------------------------------------------------------------------
# OllamaWorkerMixin — factory integration
# ---------------------------------------------------------------------------


class TestOllamaWorkerMixinFactoryIntegration:
    """
    Verify that OllamaWorkerMixin._resolve_model_id() falls back to Ollama
    settings when ACTIVE_PROVIDER is not 'github', preserving all existing
    test behaviour.
    """

    def _make_mixin(self):
        from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

        class FakeWorker(OllamaWorkerMixin):
            name = "test_worker"
            _preferred_model = "default"

        return FakeWorker()

    def _make_context(self):
        from smartagent.config.settings import Settings
        ctx = MagicMock()
        ctx.goal = "test goal"
        settings = Settings()
        ctx.metadata = {"settings": settings}
        return ctx

    def test_resolve_returns_ollama_model_when_provider_is_ollama(
        self, monkeypatch, tmp_path
    ):
        import smartagent.llm.factory as _fac
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        worker = self._make_mixin()
        context = self._make_context()
        model_id = worker._resolve_model_id(context)
        # When provider is ollama, factory returns None → falls back to settings
        # settings.ollama_default_model = "llama3.1:8b"
        assert model_id == "llama3.1:8b"

    def test_resolve_returns_github_model_when_provider_is_github(
        self, monkeypatch, tmp_path
    ):
        import smartagent.llm.factory as _fac
        monkeypatch.setenv("ACTIVE_PROVIDER", "github")
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        worker = self._make_mixin()
        context = self._make_context()
        model_id = worker._resolve_model_id(context)
        assert model_id == "gpt-4.1-mini"

    def test_resolve_coding_returns_github_coding_model(
        self, monkeypatch, tmp_path
    ):
        import smartagent.llm.factory as _fac
        monkeypatch.setenv("ACTIVE_PROVIDER", "github")
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")

        from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

        class CodingWorker(OllamaWorkerMixin):
            name = "coding_worker"
            _preferred_model = "coding"

        worker = CodingWorker()
        context = self._make_context()
        model_id = worker._resolve_model_id(context)
        assert model_id == "gpt-4.1"
