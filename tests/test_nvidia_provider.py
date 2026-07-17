"""
Tests for NvidiaProvider — smartagent.llm.nvidia_provider.

Strategy mirrors test_github_provider.py:
  - All OpenAI SDK calls are mocked — no network, no real NVIDIA API calls,
    no key required.
  - NvidiaProvider unit-tested directly (identity, capabilities, lifecycle,
    chat, stream, chat_with_tools, embed, health, list_models).
  - ProviderFactory tested for nvidia auto-detection, state save/load,
    provider switching, and get_model_for_role() behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from smartagent.llm.nvidia_provider import (
    NvidiaProvider,
    NVIDIA_INFERENCE_BASE_URL,
    _NVIDIA_MODEL_CATALOGUE,
)
from smartagent.models.base.base_model import ModelHealth, ModelStatus


# ---------------------------------------------------------------------------
# Helpers — build fake OpenAI SDK responses
# ---------------------------------------------------------------------------

def _fake_completion(content: str) -> MagicMock:
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content),
        finish_reason="stop",
    )
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    return SimpleNamespace(choices=[choice], usage=usage)


def _fake_stream_chunks(tokens: list[str]) -> list[MagicMock]:
    chunks = []
    for token in tokens:
        delta = SimpleNamespace(content=token)
        choice = SimpleNamespace(delta=delta, finish_reason=None)
        chunks.append(SimpleNamespace(choices=[choice]))
    done_choice = SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="stop")
    chunks.append(SimpleNamespace(choices=[done_choice]))
    return chunks


def _loaded_provider(model_name: str = "nvidia/nemotron-3-ultra-550b-a55b") -> NvidiaProvider:
    p = NvidiaProvider(model_name=model_name, api_key="nvapi-test")
    p.load()
    return p


# ---------------------------------------------------------------------------
# Identity & capabilities
# ---------------------------------------------------------------------------

class TestNvidiaProviderIdentity:
    def test_id_is_model_name(self):
        p = NvidiaProvider(model_name="nvidia/nemotron-3-ultra-550b-a55b")
        assert p.id == "nvidia/nemotron-3-ultra-550b-a55b"

    def test_provider_name_is_nvidia(self):
        p = NvidiaProvider()
        assert p.provider == "nvidia"

    def test_context_window_for_known_model(self):
        p = NvidiaProvider(model_name="nvidia/nemotron-3-ultra-550b-a55b")
        assert p.context_window == 128_000

    def test_context_window_falls_back_for_unknown_model(self):
        p = NvidiaProvider(model_name="some/unknown-model")
        assert p.context_window == 128_000

    def test_supports_tools_true_for_known_model(self):
        p = NvidiaProvider(model_name="nvidia/nemotron-3-ultra-550b-a55b")
        assert p.supports_tools is True

    def test_supports_embeddings_false(self):
        p = NvidiaProvider()
        assert p.supports_embeddings is False

    def test_supports_streaming_true(self):
        p = NvidiaProvider()
        assert p.supports_streaming is True


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestNvidiaProviderLifecycle:
    def test_load_sets_status(self):
        p = NvidiaProvider(api_key="nvapi-test")
        assert p._status == ModelStatus.UNLOADED
        p.load()
        assert p._status == ModelStatus.LOADED

    def test_load_without_key_still_loads(self):
        p = NvidiaProvider(api_key="")
        p.load()
        assert p._status == ModelStatus.LOADED

    def test_shutdown_unloads(self):
        p = _loaded_provider()
        p.shutdown()
        assert p._status == ModelStatus.UNLOADED

    def test_chat_requires_loaded(self):
        p = NvidiaProvider(api_key="nvapi-test")
        with pytest.raises(RuntimeError, match="must be load"):
            p.chat([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Chat (non-streaming)
# ---------------------------------------------------------------------------

class TestNvidiaProviderChat:
    def test_chat_returns_content(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion("Hello there.")
        p._client = client
        result = p.chat([{"role": "user", "content": "hi"}])
        assert result["content"] == "Hello there."
        assert result["finish_reason"] == "stop"

    def test_chat_passes_reasoning_extra_body(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion("ok")
        p._client = client
        p.chat([{"role": "user", "content": "hi"}])
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"]["reasoning_budget"] == 16384
        assert call_kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True

    def test_chat_fallback_on_api_error(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("rate limit")
        p._client = client
        result = p.chat([{"role": "user", "content": "hi"}])
        assert "error" in result["content"].lower() or "nvidia" in result["content"].lower()
        assert result["finish_reason"] == "error"

    def test_chat_increments_call_count(self):
        p = _loaded_provider()
        p._client = MagicMock(chat=MagicMock(
            completions=MagicMock(create=MagicMock(return_value=_fake_completion("x")))
        ))
        p.chat([{"role": "user", "content": "hi"}])
        p.chat([{"role": "user", "content": "bye"}])
        assert p.call_count == 2


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

class TestNvidiaProviderStream:
    def _mock_streaming_client(self, tokens: list[str]):
        client = MagicMock()
        client.chat.completions.create.return_value = iter(_fake_stream_chunks(tokens))
        return client

    def test_chat_stream_yields_tokens(self):
        p = _loaded_provider()
        p._client = self._mock_streaming_client(["Hello", " world"])
        tokens = list(p.chat_stream([{"role": "user", "content": "hi"}]))
        assert "Hello" in tokens
        assert " world" in tokens

    def test_stream_ignores_reasoning_content(self):
        """reasoning_content deltas must never be yielded — only real content."""
        p = _loaded_provider()
        reasoning_chunk = SimpleNamespace(
            choices=[SimpleNamespace(
                delta=SimpleNamespace(content=None, reasoning_content="thinking..."),
                finish_reason=None,
            )]
        )
        content_chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="answer"), finish_reason=None)]
        )
        client = MagicMock()
        client.chat.completions.create.return_value = iter([reasoning_chunk, content_chunk])
        p._client = client
        tokens = list(p.chat_stream([{"role": "user", "content": "hi"}]))
        assert tokens == ["answer"]

    def test_stream_fallback_on_error(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("stream error")
        p._client = client
        tokens = list(p.chat_stream([{"role": "user", "content": "hi"}]))
        assert len(tokens) == 1
        assert "nvidia" in tokens[0].lower()


# ---------------------------------------------------------------------------
# Tool calling
# ---------------------------------------------------------------------------

class TestNvidiaProviderChatWithTools:
    def test_chat_with_tools_returns_message(self):
        p = _loaded_provider()
        msg = SimpleNamespace(content="done", tool_calls=[])
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        p._client = client
        result = p.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])
        assert result.content == "done"

    def test_chat_with_tools_raises_on_error(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("boom")
        p._client = client
        with pytest.raises(Exception, match="boom"):
            p.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])


# ---------------------------------------------------------------------------
# Embeddings (unsupported)
# ---------------------------------------------------------------------------

class TestNvidiaProviderEmbed:
    def test_embed_raises_not_implemented(self):
        p = _loaded_provider()
        with pytest.raises(NotImplementedError):
            p.embed("some text")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestNvidiaProviderHealth:
    def test_health_no_key_returns_unhealthy(self, monkeypatch):
        # api_key="" alone isn't enough to isolate this test — the
        # constructor falls back to the real NVIDIA_API_KEY env var (same
        # pattern as GitHubProvider), which would otherwise make a real
        # network call if a key happens to be present in the environment.
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        p = NvidiaProvider(api_key="")
        p.load()
        health = p.health()
        assert health.healthy is False
        assert "NVIDIA_API_KEY" in health.message

    def test_health_api_error_returns_unhealthy(self):
        p = _loaded_provider()
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("down")
        p._client = client
        health = p.health()
        assert health.healthy is False


# ---------------------------------------------------------------------------
# ProviderFactory integration
# ---------------------------------------------------------------------------

class TestProviderFactoryNvidiaIntegration:
    def test_auto_default_prefers_nvidia_over_github(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        assert _fac.get_active_provider() == "nvidia"

    def test_get_model_for_role_returns_nvidia_model(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ACTIVE_PROVIDER", "nvidia")
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        assert _fac.get_model_for_role("default") == _fac.NVIDIA_DEFAULT_MODEL
        assert _fac.get_model_for_role("coding") == _fac.NVIDIA_DEFAULT_MODEL

    def test_switch_provider_to_nvidia_saves_state(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ACTIVE_PROVIDER", raising=False)
        import smartagent.llm.factory as _fac
        state_file = tmp_path / ".state.json"
        monkeypatch.setattr(_fac, "_STATE_FILE", state_file)
        _fac.switch_provider("nvidia", model="nvidia/nemotron-3-ultra-550b-a55b")
        saved = json.loads(state_file.read_text())
        assert saved["provider"] == "nvidia"
        assert saved["nvidia_model"] == "nvidia/nemotron-3-ultra-550b-a55b"

    def test_invalid_nvidia_model_on_disk_is_healed_and_persisted(self, monkeypatch, tmp_path):
        import smartagent.llm.factory as _fac
        state_file = tmp_path / ".state.json"
        state_file.write_text(json.dumps({
            "provider": "nvidia", "nvidia_model": "not-a-real-model",
        }))
        monkeypatch.setattr(_fac, "_STATE_FILE", state_file)
        state = _fac._load_state()
        assert state["nvidia_model"] == _fac.NVIDIA_DEFAULT_MODEL
        on_disk = json.loads(state_file.read_text())
        assert on_disk["nvidia_model"] == _fac.NVIDIA_DEFAULT_MODEL

    def test_is_llm_error_text_detects_nvidia_sentinel(self):
        import smartagent.llm.factory as _fac
        assert _fac.is_llm_error_text("NVIDIA API error: Too many requests.")
        assert not _fac.is_llm_error_text("Here's my analysis of the repo.")

    def test_get_llm_settings_nvidia_branch(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ACTIVE_PROVIDER", "nvidia")
        import smartagent.llm.factory as _fac
        monkeypatch.setattr(_fac, "_STATE_FILE", tmp_path / ".state.json")
        settings = _fac.get_llm_settings()
        assert settings["provider"] == "nvidia"
        assert settings["model"] == _fac.NVIDIA_DEFAULT_MODEL
        assert "nvidia_available" in settings
