"""
Tests for smartagent.tts — provider abstraction (factory + kokoro/piper/openai).

Concrete providers are mocked at the factory boundary for the selection-logic
tests; kokoro_provider/piper_provider/openai_provider get their own focused
unit tests with the underlying library/subprocess/API call mocked out —
no real inference, subprocess, or network call runs in this suite.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smartagent.tts import factory


# ── Factory: state persistence + selection ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect the factory's state file to a temp dir and clear the provider
    instance cache so tests don't leak state into each other."""
    monkeypatch.setattr(factory, "_STATE_FILE", tmp_path / ".mark_tts_state.json")
    factory._provider_cache.clear()
    yield
    factory._provider_cache.clear()


class TestProviderSelection:
    def test_default_is_kokoro(self):
        assert factory.get_active_provider_name() == "kokoro"

    def test_switch_persists(self):
        factory.switch_provider("piper")
        assert factory.get_active_provider_name() == "piper"

    def test_switch_rejects_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown TTS provider"):
            factory.switch_provider("nonexistent")

    def test_state_survives_reload(self, tmp_path):
        factory.switch_provider("openai")
        state_file = factory._STATE_FILE
        assert json.loads(state_file.read_text())["provider"] == "openai"

    def test_corrupt_state_file_falls_back_to_default(self):
        factory._STATE_FILE.write_text("{not valid json")
        assert factory.get_active_provider_name() == "kokoro"


class TestSynthesizeDispatch:
    def test_browser_provider_raises(self):
        factory.switch_provider("browser")
        with pytest.raises(RuntimeError, match="browser"):
            factory.synthesize("hello")

    def test_unavailable_provider_raises(self):
        factory.switch_provider("kokoro")
        mock_provider = MagicMock()
        mock_provider.available = False
        factory._provider_cache["kokoro"] = mock_provider
        with pytest.raises(RuntimeError, match="not available"):
            factory.synthesize("hello")

    def test_available_provider_called(self):
        factory.switch_provider("kokoro")
        mock_provider = MagicMock()
        mock_provider.available = True
        mock_provider.synthesize.return_value = b"WAVDATA"
        factory._provider_cache["kokoro"] = mock_provider
        result = factory.synthesize("hello", voice="af_sarah", speed=1.2)
        assert result == b"WAVDATA"
        mock_provider.synthesize.assert_called_once_with("hello", voice="af_sarah", speed=1.2)


class TestListVoices:
    def test_browser_has_no_voices(self):
        assert factory.list_voices("browser") == []

    def test_delegates_to_provider(self):
        mock_provider = MagicMock()
        mock_provider.available = True
        mock_provider.list_voices.return_value = ["af_sarah", "af_nova"]
        factory._provider_cache["kokoro"] = mock_provider
        assert factory.list_voices("kokoro") == ["af_sarah", "af_nova"]

    def test_unavailable_provider_returns_empty(self):
        mock_provider = MagicMock()
        mock_provider.available = False
        factory._provider_cache["kokoro"] = mock_provider
        assert factory.list_voices("kokoro") == []


class TestProviderStatus:
    def test_includes_all_four(self):
        status = factory.provider_status()
        assert set(status) == {"kokoro", "piper", "openai", "browser"}
        assert status["browser"] is True  # always available (client-side)


# ── KokoroProvider ───────────────────────────────────────────────────────────────

class TestKokoroProvider:
    def test_unavailable_without_model_files(self, tmp_path, monkeypatch):
        from smartagent.tts.kokoro_provider import KokoroProvider
        monkeypatch.setattr("smartagent.tts.kokoro_provider.MODEL_PATH", tmp_path / "missing.onnx")
        monkeypatch.setattr("smartagent.tts.kokoro_provider.VOICES_PATH", tmp_path / "missing.bin")
        assert KokoroProvider().available is False

    def test_synthesize_raises_when_unavailable(self, tmp_path, monkeypatch):
        from smartagent.tts.kokoro_provider import KokoroProvider
        monkeypatch.setattr("smartagent.tts.kokoro_provider.MODEL_PATH", tmp_path / "missing.onnx")
        monkeypatch.setattr("smartagent.tts.kokoro_provider.VOICES_PATH", tmp_path / "missing.bin")
        with pytest.raises(RuntimeError, match="model files not found"):
            KokoroProvider().synthesize("hi")

    def test_synthesize_wraps_samples_as_wav(self, tmp_path, monkeypatch):
        import numpy as np
        from smartagent.tts.kokoro_provider import KokoroProvider

        model_path  = tmp_path / "kokoro-v1.0.int8.onnx"
        voices_path = tmp_path / "voices-v1.0.bin"
        model_path.write_bytes(b"fake")
        voices_path.write_bytes(b"fake")
        monkeypatch.setattr("smartagent.tts.kokoro_provider.MODEL_PATH", model_path)
        monkeypatch.setattr("smartagent.tts.kokoro_provider.VOICES_PATH", voices_path)

        fake_kokoro = MagicMock()
        fake_kokoro.create.return_value = (np.zeros(1000, dtype=np.float32), 24000)
        with patch("kokoro_onnx.Kokoro", return_value=fake_kokoro):
            provider = KokoroProvider()
            audio = provider.synthesize("hello", voice="af_sarah")

        assert audio[:4] == b"RIFF"  # WAV header
        fake_kokoro.create.assert_called_once()

    def test_list_voices_sorted(self, tmp_path, monkeypatch):
        from smartagent.tts.kokoro_provider import KokoroProvider
        model_path  = tmp_path / "m.onnx"
        voices_path = tmp_path / "v.bin"
        model_path.write_bytes(b"fake")
        voices_path.write_bytes(b"fake")
        monkeypatch.setattr("smartagent.tts.kokoro_provider.MODEL_PATH", model_path)
        monkeypatch.setattr("smartagent.tts.kokoro_provider.VOICES_PATH", voices_path)

        fake_kokoro = MagicMock()
        fake_kokoro.get_voices.return_value = ["af_sarah", "af_bella"]
        with patch("kokoro_onnx.Kokoro", return_value=fake_kokoro):
            voices = KokoroProvider().list_voices()
        assert voices == ["af_bella", "af_sarah"]


# ── PiperProvider ────────────────────────────────────────────────────────────────

class TestPiperProvider:
    def test_unavailable_without_binary_or_package(self, monkeypatch):
        from smartagent.tts.piper_provider import PiperProvider
        monkeypatch.setattr("shutil.which", lambda name: None)
        provider = PiperProvider()
        with patch.dict("sys.modules", {"piper": None, "piper.voice": None}):
            assert provider.available is False

    def test_synthesize_via_binary_wraps_raw_pcm(self, monkeypatch):
        from smartagent.tts.piper_provider import PiperProvider
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/piper")
        provider = PiperProvider()

        fake_proc = MagicMock(returncode=0, stdout=b"\x00\x01" * 100, stderr=b"")
        with patch("subprocess.run", return_value=fake_proc):
            audio = provider.synthesize("hello")
        assert audio[:4] == b"RIFF"

    def test_synthesize_raises_on_nonzero_exit(self, monkeypatch):
        from smartagent.tts.piper_provider import PiperProvider
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/piper")
        provider = PiperProvider()

        fake_proc = MagicMock(returncode=1, stdout=b"", stderr=b"model not found")
        with patch("subprocess.run", return_value=fake_proc):
            with pytest.raises(RuntimeError, match="piper returned"):
                provider.synthesize("hello")


# ── OpenAIProvider ───────────────────────────────────────────────────────────────

class TestOpenAIProvider:
    def test_unavailable_without_api_key(self, monkeypatch):
        from smartagent.tts.openai_provider import OpenAIProvider
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert OpenAIProvider().available is False

    def test_available_with_api_key(self, monkeypatch):
        from smartagent.tts.openai_provider import OpenAIProvider
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert OpenAIProvider().available is True

    def test_synthesize_raises_without_key(self, monkeypatch):
        from smartagent.tts.openai_provider import OpenAIProvider
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            OpenAIProvider().synthesize("hi")

    def test_invalid_voice_falls_back_to_default(self, monkeypatch):
        import sys
        import types
        from smartagent.tts.openai_provider import OpenAIProvider, DEFAULT_VOICE
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_client = MagicMock()
        mock_client.audio.speech.create.return_value = MagicMock(content=b"MP3DATA")
        fake_openai_module = types.ModuleType("openai")
        fake_openai_module.OpenAI = MagicMock(return_value=mock_client)  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"openai": fake_openai_module}):
            audio = OpenAIProvider().synthesize("hi", voice="not-a-real-voice")

        assert audio == b"MP3DATA"
        assert mock_client.audio.speech.create.call_args.kwargs["voice"] == DEFAULT_VOICE


# ── REST endpoints — /tts/* ──────────────────────────────────────────────────────

class TestTtsEndpoints:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from smartagent.server.app import app
        with TestClient(app) as c:
            yield c

    def test_status(self, client):
        resp = client.get("/tts/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["active"] == "kokoro"
        assert set(body["providers"]) == {"kokoro", "piper", "openai", "browser"}

    def test_switch_provider(self, client):
        resp = client.post("/tts/provider", json={"provider": "piper"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "provider": "piper"}
        factory.switch_provider("kokoro")  # reset for other tests

    def test_switch_provider_rejects_unknown(self, client):
        resp = client.post("/tts/provider", json={"provider": "nonexistent"})
        assert resp.status_code == 400

    def test_voices(self, client):
        with patch("smartagent.tts.factory.list_voices", return_value=["af_sarah"]):
            resp = client.get("/tts/voices")
        assert resp.status_code == 200
        assert resp.json() == {"voices": ["af_sarah"]}

    def test_speak_success(self, client):
        with patch("smartagent.tts.factory.synthesize", return_value=b"RIFFdata"):
            resp = client.post("/tts/speak", json={"text": "hello"})
        assert resp.status_code == 200
        assert resp.content == b"RIFFdata"
        assert resp.headers["content-type"] == "audio/wav"

    def test_speak_unavailable_returns_503(self, client):
        with patch("smartagent.tts.factory.synthesize", side_effect=RuntimeError("not available")):
            resp = client.post("/tts/speak", json={"text": "hello"})
        assert resp.status_code == 503
