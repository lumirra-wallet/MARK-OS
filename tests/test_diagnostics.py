"""
Milestone 3 — Diagnostics tests.

Covers:
  api_diagnostics.py   — _check_backend, _check_database, _check_git,
                          _check_workspace, _check_vector_db, _check_memory,
                          _check_system (CPU/RAM), _check_llm_provider (all 4
                          providers), _check_embeddings (all 4 providers),
                          GET /diagnostics (structure + overall status logic)
  api_system.py        — GET /metrics (CPU/RAM/disk), workspace detect/recent,
                          record_workspace, GET /models (nvidia + github),
                          POST /models/switch, GET /memory, GET /memory/file
                          (path-traversal guard), GET /git/status, /git/log,
                          /git/diff

Mock strategy
-------------
* All network / filesystem / subprocess calls are mocked; tests run offline.
* psutil is patched at import path used by each module.
* async check functions are exercised via asyncio.run().
* Endpoint tests use FastAPI TestClient against a minimal test app that mounts
  only the two routers under test.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Minimal test application ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from smartagent.server import api_diagnostics, api_system
    _app = FastAPI()
    _app.include_router(api_diagnostics.router)
    _app.include_router(api_system.router)
    return _app


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════════════════
# _check_backend
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckBackend:
    def test_always_ok(self):
        from smartagent.server.api_diagnostics import _check_backend
        result = _check_backend()
        assert result["status"] == "ok"

    def test_has_message(self):
        from smartagent.server.api_diagnostics import _check_backend
        assert "message" in _check_backend()


# ═══════════════════════════════════════════════════════════════════════════════
# _check_database
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckDatabase:
    def _mock_store(self, status="ok", message="storage reachable"):
        store = MagicMock()
        store.health.return_value = {"status": status, "message": message, "provider": "local"}
        return store

    def test_ok_when_storage_healthy(self):
        from smartagent.server.api_diagnostics import _check_database
        with patch("smartagent.storage.factory.get_storage", return_value=self._mock_store()):
            result = _check_database()
        assert result["status"] == "ok"

    def test_includes_latency_ms(self):
        from smartagent.server.api_diagnostics import _check_database
        with patch("smartagent.storage.factory.get_storage", return_value=self._mock_store()):
            result = _check_database()
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], int)

    def test_error_when_storage_unhealthy(self):
        from smartagent.server.api_diagnostics import _check_database
        with patch("smartagent.storage.factory.get_storage", return_value=self._mock_store("error", "disk full")):
            result = _check_database()
        assert result["status"] == "error"

    def test_error_when_exception_raised(self):
        from smartagent.server.api_diagnostics import _check_database
        with patch("smartagent.storage.factory.get_storage", side_effect=RuntimeError("db down")):
            result = _check_database()
        assert result["status"] == "error"
        assert "db down" in result["message"]

    def test_passes_through_provider_field(self):
        from smartagent.server.api_diagnostics import _check_database
        store = MagicMock()
        store.health.return_value = {"status": "ok", "message": "ok", "provider": "postgres"}
        with patch("smartagent.storage.factory.get_storage", return_value=store):
            result = _check_database()
        assert result.get("provider") == "postgres"


# ═══════════════════════════════════════════════════════════════════════════════
# _check_git
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckGit:
    def _run_ok(self):
        r = MagicMock()
        r.returncode = 0
        r.stdout = "true\n"
        return r

    def _run_fail(self, rc=1):
        r = MagicMock()
        r.returncode = rc
        return r

    def test_ok_inside_repo(self):
        from smartagent.server.api_diagnostics import _check_git
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = _check_git()
        assert result["status"] == "ok"
        assert "git available" in result["message"]

    def test_warn_when_not_in_repo(self):
        from smartagent.server.api_diagnostics import _check_git
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", return_value=self._run_fail()):
            result = _check_git()
        assert result["status"] == "warn"

    def test_error_when_git_not_in_path(self):
        from smartagent.server.api_diagnostics import _check_git
        with patch("shutil.which", return_value=None):
            result = _check_git()
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_error_on_exception(self):
        from smartagent.server.api_diagnostics import _check_git
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=OSError("exec failed")):
            result = _check_git()
        assert result["status"] == "error"

    def test_latency_in_message_when_ok(self):
        from smartagent.server.api_diagnostics import _check_git
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = _check_git()
        assert "ms" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# _check_workspace
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckWorkspace:
    """
    _check_workspace() first checks _state.workspace from the API module.
    We patch that state to None so the function falls through to os.getcwd().
    """

    def _no_state(self):
        """Patch away _state so the function uses os.getcwd() as the fallback."""
        try:
            from smartagent.server import api as _api
            return patch.object(_api, "_state", None)
        except Exception:
            return patch("smartagent.server.api._state", None, create=True)

    def test_ok_when_dir_exists(self, tmp_path):
        from smartagent.server.api_diagnostics import _check_workspace
        with self._no_state(), \
             patch("smartagent.server.api_diagnostics.os.getcwd", return_value=str(tmp_path)), \
             patch("smartagent.server.api_diagnostics.os.path.isdir", return_value=True):
            result = _check_workspace()
        assert result["status"] == "ok"

    def test_warn_when_dir_missing(self, tmp_path):
        from smartagent.server.api_diagnostics import _check_workspace
        with self._no_state(), \
             patch("smartagent.server.api_diagnostics.os.getcwd", return_value=str(tmp_path)), \
             patch("smartagent.server.api_diagnostics.os.path.isdir", return_value=False):
            result = _check_workspace()
        assert result["status"] == "warn"

    def test_message_contains_path(self, tmp_path):
        from smartagent.server.api_diagnostics import _check_workspace
        ws = str(tmp_path)
        with self._no_state(), \
             patch("smartagent.server.api_diagnostics.os.getcwd", return_value=ws), \
             patch("smartagent.server.api_diagnostics.os.path.isdir", return_value=True):
            result = _check_workspace()
        assert ws in result["message"]

    def test_warn_on_exception(self, tmp_path):
        from smartagent.server.api_diagnostics import _check_workspace
        with self._no_state(), \
             patch("smartagent.server.api_diagnostics.os.getcwd", side_effect=OSError("no cwd")):
            result = _check_workspace()
        assert result["status"] in ("warn", "error")


# ═══════════════════════════════════════════════════════════════════════════════
# _check_vector_db
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckVectorDb:
    def _mock_vs(self, status="ok", count=0):
        vs = MagicMock()
        vs.health.return_value = {"status": status, "message": f"{status}", "count": count}
        return vs

    def test_ok(self):
        from smartagent.server.api_diagnostics import _check_vector_db
        with patch("smartagent.vector.factory.get_vector_store", return_value=self._mock_vs()):
            result = _check_vector_db()
        assert result["status"] == "ok"

    def test_latency_added(self):
        from smartagent.server.api_diagnostics import _check_vector_db
        with patch("smartagent.vector.factory.get_vector_store", return_value=self._mock_vs()):
            result = _check_vector_db()
        assert "latency_ms" in result

    def test_warn_on_exception(self):
        from smartagent.server.api_diagnostics import _check_vector_db
        with patch("smartagent.vector.factory.get_vector_store", side_effect=Exception("chroma down")):
            result = _check_vector_db()
        assert result["status"] == "warn"
        assert "chroma down" in result["message"]

    def test_passes_through_count(self):
        from smartagent.server.api_diagnostics import _check_vector_db
        with patch("smartagent.vector.factory.get_vector_store", return_value=self._mock_vs(count=42)):
            result = _check_vector_db()
        assert result.get("count") == 42


# ═══════════════════════════════════════════════════════════════════════════════
# _check_memory
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckMemory:
    def test_ok_when_importable_at_primary_path(self):
        from smartagent.server.api_diagnostics import _check_memory
        mock_mod = MagicMock()
        mock_mod.MemoryManager = MagicMock
        with patch("importlib.import_module", return_value=mock_mod):
            result = _check_memory()
        assert result["status"] == "ok"

    def test_ok_message_mentions_memory_manager(self):
        from smartagent.server.api_diagnostics import _check_memory
        mock_mod = MagicMock()
        mock_mod.MemoryManager = MagicMock
        with patch("importlib.import_module", return_value=mock_mod):
            result = _check_memory()
        assert "MemoryManager" in result["message"]

    def test_warn_when_not_importable(self):
        from smartagent.server.api_diagnostics import _check_memory
        with patch("importlib.import_module", side_effect=ImportError("no module")):
            result = _check_memory()
        assert result["status"] == "warn"

    def test_error_on_non_import_exception(self):
        from smartagent.server.api_diagnostics import _check_memory

        def bad_import(name):
            if "memory" in name:
                raise RuntimeError("internal error")
            raise ImportError

        with patch("importlib.import_module", side_effect=bad_import):
            result = _check_memory()
        assert result["status"] in ("error", "warn")


# ═══════════════════════════════════════════════════════════════════════════════
# _check_system  (CPU + RAM)
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_psutil(cpu: float = 30.0, ram_pct: float = 50.0,
                 ram_used: int = 4_000_000_000, ram_total: int = 8_000_000_000,
                 proc_cpu: float = 5.0, proc_rss: int = 100_000_000):
    vm = MagicMock()
    vm.percent = ram_pct
    vm.used    = ram_used
    vm.total   = ram_total
    proc = MagicMock()
    proc.pid = 12345
    proc.cpu_percent.return_value = proc_cpu
    proc.memory_info.return_value = MagicMock(rss=proc_rss)
    psutil_mock = MagicMock()
    psutil_mock.cpu_percent.return_value     = cpu
    psutil_mock.virtual_memory.return_value  = vm
    psutil_mock.Process.return_value         = proc
    return psutil_mock


class TestCheckSystem:
    def test_ok_when_cpu_and_ram_low(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(cpu=20, ram_pct=40)}):
            result = _check_system()
        assert result["status"] == "ok"

    def test_warn_when_cpu_high(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(cpu=90, ram_pct=40)}):
            result = _check_system()
        assert result["status"] == "warn"

    def test_warn_when_ram_high(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(cpu=10, ram_pct=90)}):
            result = _check_system()
        assert result["status"] == "warn"

    def test_cpu_pct_field_present(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(cpu=55.0)}):
            result = _check_system()
        assert "cpu_pct" in result
        assert result["cpu_pct"] == 55.0

    def test_ram_pct_field_present(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(ram_pct=62.0)}):
            result = _check_system()
        assert "ram_pct" in result
        assert result["ram_pct"] == 62.0

    def test_ram_gb_fields_present(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(
                ram_used=4_000_000_000, ram_total=16_000_000_000)}):
            result = _check_system()
        assert "ram_used_gb"  in result
        assert "ram_total_gb" in result
        assert result["ram_total_gb"] == 16.0

    def test_message_contains_cpu_and_ram(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(cpu=25, ram_pct=60)}):
            result = _check_system()
        msg = result["message"]
        assert "CPU" in msg or "cpu" in msg
        assert "RAM" in msg or "ram" in msg or "GB" in msg

    def test_warn_when_psutil_not_installed(self):
        from smartagent.server.api_diagnostics import _check_system
        # Remove psutil from sys.modules so ImportError is raised
        with patch.dict(sys.modules, {"psutil": None}):
            result = _check_system()
        assert result["status"] == "warn"
        assert "psutil" in result["message"].lower()

    def test_warn_on_exception(self):
        from smartagent.server.api_diagnostics import _check_system
        bad = MagicMock()
        bad.cpu_percent.side_effect = OSError("sensor error")
        with patch.dict(sys.modules, {"psutil": bad}):
            result = _check_system()
        assert result["status"] == "warn"

    def test_boundary_cpu_79_is_ok(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(cpu=79, ram_pct=40)}):
            result = _check_system()
        assert result["status"] == "ok"

    def test_boundary_ram_84_is_ok(self):
        from smartagent.server.api_diagnostics import _check_system
        with patch.dict(sys.modules, {"psutil": _mock_psutil(cpu=10, ram_pct=84)}):
            result = _check_system()
        assert result["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════════
# _check_llm_provider  (all 4 provider paths)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckLLMProvider:
    """Test the async _check_llm_provider() by running each branch."""

    def _run(self, coro):
        return asyncio.run(coro)

    # ── github ────────────────────────────────────────────────────────────────

    def test_github_ok(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = True; health.message = "GitHub OK"
        p = MagicMock(); p.health.return_value = health
        with patch("smartagent.llm.factory.get_active_provider", return_value="github"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "gpt-4o"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "tok" if k == "GITHUB_TOKEN" else d), \
             patch("smartagent.llm.github_provider.GitHubProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "ok"
        assert result["provider"] == "github"

    def test_github_no_token(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        with patch("smartagent.llm.factory.get_active_provider", return_value="github"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "gpt-4o"}), \
             patch("os.environ.get", return_value=""):
            result = self._run(_check_llm_provider())
        assert result["status"] == "error"
        assert "GITHUB_TOKEN" in result["message"]

    def test_github_unhealthy(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = False; health.message = "bad token"
        p = MagicMock(); p.health.return_value = health
        with patch("smartagent.llm.factory.get_active_provider", return_value="github"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "gpt-4o"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "tok" if k == "GITHUB_TOKEN" else d), \
             patch("smartagent.llm.github_provider.GitHubProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "error"

    # ── openai ────────────────────────────────────────────────────────────────

    def test_openai_ok(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        p = MagicMock(); p.health.return_value = {"healthy": True, "message": "OpenAI OK"}
        with patch("smartagent.llm.factory.get_active_provider", return_value="openai"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "gpt-4o-mini"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "sk-test" if k == "OPENAI_API_KEY" else d), \
             patch("smartagent.llm.openai_provider.OpenAIProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "ok"
        assert result["provider"] == "openai"

    def test_openai_no_key(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        with patch("smartagent.llm.factory.get_active_provider", return_value="openai"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "gpt-4o-mini"}), \
             patch("os.environ.get", return_value=""):
            result = self._run(_check_llm_provider())
        assert result["status"] == "error"
        assert "OPENAI_API_KEY" in result["message"]

    # ── anthropic ─────────────────────────────────────────────────────────────

    def test_anthropic_ok(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        p = MagicMock(); p.health.return_value = {"healthy": True, "message": "Anthropic OK"}
        with patch("smartagent.llm.factory.get_active_provider", return_value="anthropic"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "claude-3-5-haiku-20241022"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "sk-ant" if k == "ANTHROPIC_API_KEY" else d), \
             patch("smartagent.llm.anthropic_provider.AnthropicProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "ok"
        assert result["provider"] == "anthropic"

    def test_anthropic_no_key(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        with patch("smartagent.llm.factory.get_active_provider", return_value="anthropic"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "claude-3-5-haiku-20241022"}), \
             patch("os.environ.get", return_value=""):
            result = self._run(_check_llm_provider())
        assert result["status"] == "error"
        assert "ANTHROPIC_API_KEY" in result["message"]

    # ── nvidia ────────────────────────────────────────────────────────────────

    def test_nvidia_ok(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = True; health.message = "NVIDIA OK"
        p = MagicMock(); p.health.return_value = health
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "nvidia/nemotron-3-ultra-550b-a55b"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "nvapi-test" if k == "NVIDIA_API_KEY" else d), \
             patch("smartagent.llm.nvidia_provider.NvidiaProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "ok"
        assert result["provider"] == "nvidia"

    def test_nvidia_no_key(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "nvidia/nemotron-3-ultra-550b-a55b"}), \
             patch("os.environ.get", return_value=""):
            result = self._run(_check_llm_provider())
        assert result["status"] == "error"
        assert "NVIDIA_API_KEY" in result["message"]

    def test_result_has_model_field(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = True; health.message = "NVIDIA OK"
        p = MagicMock(); p.health.return_value = health
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "nvidia/nemotron-3-ultra-550b-a55b"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "nvapi-test" if k == "NVIDIA_API_KEY" else d), \
             patch("smartagent.llm.nvidia_provider.NvidiaProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["model"] == "nvidia/nemotron-3-ultra-550b-a55b"

    def test_nvidia_result_includes_endpoint_and_telemetry(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = True; health.message = "NVIDIA OK"
        p = MagicMock(); p.health.return_value = health
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "nvidia/nemotron-3-ultra-550b-a55b"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "nvapi-test" if k == "NVIDIA_API_KEY" else d), \
             patch("smartagent.llm.nvidia_provider.NvidiaProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["endpoint"] == "https://integrate.api.nvidia.com/v1"
        assert "request_count" in result
        assert "last_error" in result

    # ── probe=False must never construct/call a provider ────────────────────

    def test_probe_false_skips_real_call_for_every_provider(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        for provider, key_env in [
            ("github", "GITHUB_TOKEN"), ("nvidia", "NVIDIA_API_KEY"), ("ollama", ""),
            ("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"),
        ]:
            with patch("smartagent.llm.factory.get_active_provider", return_value=provider), \
                 patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "m"}), \
                 patch("os.environ.get", side_effect=lambda k, d="", _e=key_env: "present" if k == _e else d), \
                 patch("smartagent.llm.github_provider.GitHubProvider") as ghp, \
                 patch("smartagent.llm.nvidia_provider.NvidiaProvider") as nvp, \
                 patch("smartagent.models.providers.ollama_provider.OllamaProvider") as olp, \
                 patch("smartagent.llm.openai_provider.OpenAIProvider") as oap, \
                 patch("smartagent.llm.anthropic_provider.AnthropicProvider") as anp:
                result = self._run(_check_llm_provider(probe=False))
            assert result["status"] in ("ok", "warn"), f"{provider}: {result}"
            for mock_cls in (ghp, nvp, olp, oap, anp):
                mock_cls.assert_not_called()

    def test_probe_false_still_reports_no_key_as_error(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "m"}), \
             patch("os.environ.get", return_value=""):
            result = self._run(_check_llm_provider(probe=False))
        assert result["status"] == "error"
        assert "NVIDIA_API_KEY" in result["message"]

    # ── ollama (MARK's local core) ───────────────────────────────────────────

    def test_ollama_ok(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = True; health.message = "Ollama server reachable; llama3.2:3b is installed."
        p = MagicMock(); p.health.return_value = health; p.supports_tools = True
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "llama3.2:3b"}), \
             patch("smartagent.models.providers.ollama_provider.OllamaProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "ok"
        assert result["provider"] == "ollama"
        assert result["supports_tools"] is True

    def test_ollama_unreachable_with_nvidia_fallback_is_warn_not_error(self):
        """Degraded (falls back to NVIDIA), not down — status should be warn."""
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = False; health.message = "Ollama server unreachable"
        p = MagicMock(); p.health.return_value = health
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "llama3.2:3b"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "nvapi-test" if k == "NVIDIA_API_KEY" else d), \
             patch("smartagent.models.providers.ollama_provider.OllamaProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "warn"
        assert "NVIDIA fallback" in result["message"]

    def test_ollama_unreachable_without_fallback_is_error(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        health = MagicMock(); health.healthy = False; health.message = "Ollama server unreachable"
        p = MagicMock(); p.health.return_value = health
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "llama3.2:3b"}), \
             patch("os.environ.get", return_value=""), \
             patch("smartagent.models.providers.ollama_provider.OllamaProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert result["status"] == "error"

    def test_ollama_probe_false_skips_real_call(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "llama3.2:3b"}), \
             patch("smartagent.models.providers.ollama_provider.OllamaProvider") as op:
            result = self._run(_check_llm_provider(probe=False))
        assert result["status"] == "ok"
        op.assert_not_called()

    # ── unknown provider ─────────────────────────────────────────────────────
    # _check_llm_provider() still degrades gracefully instead of crashing for
    # any genuinely unrecognized value (defensive — get_active_provider()
    # only ever returns one of the five known providers in practice).

    def test_unknown_provider_returns_error(self):
        from smartagent.server.api_diagnostics import _check_llm_provider
        with patch("smartagent.llm.factory.get_active_provider", return_value="some_future_provider"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "x"}):
            result = self._run(_check_llm_provider())
        assert result["status"] == "error"
        assert result["provider"] == "some_future_provider"

    def test_result_has_latency_ms(self):
        # OpenAI/Anthropic paths add latency_ms; Ollama encodes it in the message.
        # Use OpenAI to verify the field is present.
        from smartagent.server.api_diagnostics import _check_llm_provider
        p = MagicMock(); p.health.return_value = {"healthy": True, "message": "OK"}
        with patch("smartagent.llm.factory.get_active_provider", return_value="openai"), \
             patch("smartagent.llm.factory.get_llm_settings", return_value={"model": "gpt-4o-mini"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "sk-x" if k == "OPENAI_API_KEY" else d), \
             patch("smartagent.llm.openai_provider.OpenAIProvider", return_value=p):
            result = self._run(_check_llm_provider())
        assert "latency_ms" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _check_embeddings
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckEmbeddings:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_github_ok(self):
        from smartagent.server.api_diagnostics import _check_embeddings
        p = MagicMock(); p.embed.return_value = [0.1] * 1536
        with patch("smartagent.llm.factory.get_active_provider", return_value="github"), \
             patch("os.environ.get", side_effect=lambda k, d="": "tok" if k == "GITHUB_TOKEN" else d), \
             patch("smartagent.llm.github_provider.GitHubProvider", return_value=p):
            result = self._run(_check_embeddings())
        assert result["status"] == "ok"
        assert "dim=1536" in result["message"]

    def test_github_no_token(self):
        from smartagent.server.api_diagnostics import _check_embeddings
        with patch("smartagent.llm.factory.get_active_provider", return_value="github"), \
             patch("os.environ.get", return_value=""):
            result = self._run(_check_embeddings())
        assert result["status"] == "error"

    def test_openai_ok(self):
        from smartagent.server.api_diagnostics import _check_embeddings
        p = MagicMock(); p.embed.return_value = [0.2] * 1536
        with patch("smartagent.llm.factory.get_active_provider", return_value="openai"), \
             patch("os.environ.get", side_effect=lambda k, d="": "sk-x" if k == "OPENAI_API_KEY" else d), \
             patch("smartagent.llm.openai_provider.OpenAIProvider", return_value=p):
            result = self._run(_check_embeddings())
        assert result["status"] == "ok"

    def test_openai_no_key(self):
        from smartagent.server.api_diagnostics import _check_embeddings
        with patch("smartagent.llm.factory.get_active_provider", return_value="openai"), \
             patch("os.environ.get", return_value=""):
            result = self._run(_check_embeddings())
        assert result["status"] == "error"

    def test_anthropic_warns_without_openai_fallback(self):
        from smartagent.server.api_diagnostics import _check_embeddings
        with patch("smartagent.llm.factory.get_active_provider", return_value="anthropic"), \
             patch("os.environ.get", return_value=""):   # no OPENAI_API_KEY
            result = self._run(_check_embeddings())
        assert result["status"] == "warn"
        assert "Anthropic" in result["message"] or "anthropic" in result["message"].lower()

    def test_nvidia_warns_no_embedding_endpoint(self):
        """nvidia/nemotron-* is a chat model with no embedding endpoint —
        this must be reported, never attempt a real network call."""
        from smartagent.server.api_diagnostics import _check_embeddings
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"):
            result = self._run(_check_embeddings())
        assert result["status"] == "warn"

    def test_ollama_warns_no_embedding_model(self):
        """Same situation as NVIDIA — the default local-core model is
        chat-only; never attempt a real network call for this check."""
        from smartagent.server.api_diagnostics import _check_embeddings
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"):
            result = self._run(_check_embeddings())
        assert result["status"] == "warn"

    def test_unknown_provider_returns_error(self):
        """_check_embeddings() still degrades gracefully instead of crashing
        for any genuinely unrecognized provider value."""
        from smartagent.server.api_diagnostics import _check_embeddings
        with patch("smartagent.llm.factory.get_active_provider", return_value="some_future_provider"):
            result = self._run(_check_embeddings())
        assert result["status"] == "error"


# ═══════════════════════════════════════════════════════════════════════════════
# GET /diagnostics  (endpoint-level)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticsEndpoint:
    """
    Test the full /diagnostics HTTP endpoint via TestClient.

    Patch strategy: patch each *check function* directly on the api_diagnostics
    module rather than their transitive deps.  This survives TestClient's thread
    pool and is immune to the patch-target resolution issues that arise when
    async gather tasks run in a separate context.
    """

    _OK  = {"status": "ok",   "message": "ok"}
    _ERR = {"status": "error", "message": "db down"}
    _WRN = {"status": "warn",  "message": "not in repo"}

    def _all_ok(self):
        """Patch every check function to return ok."""
        import smartagent.server.api_diagnostics as diag
        return [
            patch.object(diag, "_check_backend",    return_value=self._OK.copy()),
            patch.object(diag, "_check_database",   return_value=self._OK.copy()),
            patch.object(diag, "_check_vector_db",  return_value=self._OK.copy()),
            patch.object(diag, "_check_git",         return_value=self._OK.copy()),
            patch.object(diag, "_check_workspace",  return_value=self._OK.copy()),
            patch.object(diag, "_check_memory",     return_value=self._OK.copy()),
            patch.object(diag, "_check_websocket",  return_value=self._OK.copy()),
            patch.object(diag, "_check_system",     return_value=self._OK.copy()),
            patch.object(diag, "_check_llm_provider",
                         new=AsyncMock(return_value=self._OK.copy())),
            patch.object(diag, "_check_embeddings",
                         new=AsyncMock(return_value=self._OK.copy())),
        ]

    def test_response_200(self, client):
        with _nested(*self._all_ok()):
            assert client.get("/diagnostics").status_code == 200

    def test_response_has_status_and_checks(self, client):
        with _nested(*self._all_ok()):
            data = client.get("/diagnostics").json()
        assert "status" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_checks_list_has_expected_names(self, client):
        with _nested(*self._all_ok()):
            data = client.get("/diagnostics").json()
        names = {c["name"] for c in data["checks"]}
        for expected in ("backend", "database", "llm_provider", "embeddings",
                         "vector_db", "git", "workspace", "memory", "system"):
            assert expected in names, f"missing check: {expected}"

    def test_overall_ok_when_all_ok(self, client):
        with _nested(*self._all_ok()):
            data = client.get("/diagnostics").json()
        assert data["status"] == "ok"

    def test_overall_error_when_any_error(self, client):
        import smartagent.server.api_diagnostics as diag
        patches = self._all_ok()
        # Override database with an error
        patches[1] = patch.object(diag, "_check_database", return_value=self._ERR.copy())
        with _nested(*patches):
            data = client.get("/diagnostics").json()
        assert data["status"] == "error"

    def test_overall_warn_when_no_error_but_warn(self, client):
        import smartagent.server.api_diagnostics as diag
        patches = self._all_ok()
        # Override git with a warn (no errors)
        patches[3] = patch.object(diag, "_check_git", return_value=self._WRN.copy())
        with _nested(*patches):
            data = client.get("/diagnostics").json()
        assert data["status"] == "warn"

    def test_each_check_has_name_field(self, client):
        with _nested(*self._all_ok()):
            data = client.get("/diagnostics").json()
        for check in data["checks"]:
            assert "name"   in check
            assert "status" in check
            assert "message" in check

    def test_each_check_status_is_valid(self, client):
        with _nested(*self._all_ok()):
            data = client.get("/diagnostics").json()
        valid = {"ok", "warn", "error"}
        for check in data["checks"]:
            assert check["status"] in valid, f"invalid status in: {check}"


def _nested(*cms):
    """Enter multiple context managers (like contextlib.ExitStack)."""
    import contextlib
    stack = contextlib.ExitStack()
    for cm in cms:
        stack.enter_context(cm)
    return stack


# ═══════════════════════════════════════════════════════════════════════════════
# GET /metrics  (CPU / RAM / disk)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSystemMetricsEndpoint:
    def _psutil_mock(self, cpu=30.0, mem_pct=55.0, disk_pct=70.0):
        vm = MagicMock(); vm.percent = mem_pct; vm.used  = 4_000_000_000; vm.total = 8_000_000_000
        disk = MagicMock(); disk.percent = disk_pct; disk.free = 30_000_000_000
        ps = MagicMock()
        ps.cpu_percent.return_value    = cpu
        ps.virtual_memory.return_value = vm
        ps.disk_usage.return_value     = disk
        return ps

    def test_response_200(self, client):
        with patch.dict(sys.modules, {"psutil": self._psutil_mock()}):
            resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_has_cpu_pct(self, client):
        with patch.dict(sys.modules, {"psutil": self._psutil_mock(cpu=42.5)}):
            data = client.get("/metrics").json()
        assert "cpu_pct" in data
        assert data["cpu_pct"] == 42.5

    def test_has_mem_pct(self, client):
        with patch.dict(sys.modules, {"psutil": self._psutil_mock(mem_pct=65.0)}):
            data = client.get("/metrics").json()
        assert "mem_pct" in data
        assert data["mem_pct"] == 65.0

    def test_has_mem_mb_fields(self, client):
        with patch.dict(sys.modules, {"psutil": self._psutil_mock()}):
            data = client.get("/metrics").json()
        assert "mem_used_mb"  in data
        assert "mem_total_mb" in data

    def test_has_disk_fields(self, client):
        with patch.dict(sys.modules, {"psutil": self._psutil_mock(disk_pct=72.0)}):
            data = client.get("/metrics").json()
        assert "disk_pct"     in data
        assert "disk_free_gb" in data
        assert data["disk_pct"] == 72.0

    def test_no_error_key_when_psutil_ok(self, client):
        with patch.dict(sys.modules, {"psutil": self._psutil_mock()}):
            data = client.get("/metrics").json()
        assert "error" not in data

    def test_error_key_when_psutil_missing(self, client):
        with patch.dict(sys.modules, {"psutil": None}):
            data = client.get("/metrics").json()
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
# GET /workspace/detect  and  GET /workspace/recent
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkspaceEndpoints:
    def _git_stub(self, stdout="", rc=0):
        r = MagicMock(); r.stdout = stdout; r.stderr = ""; r.returncode = rc
        return r

    def test_detect_200(self, client):
        with patch("subprocess.run", return_value=self._git_stub("/repo", 0)):
            resp = client.get("/workspace/detect")
        assert resp.status_code == 200

    def test_detect_has_workspace_and_cwd(self, client):
        with patch("subprocess.run", return_value=self._git_stub("", rc=1)):
            data = client.get("/workspace/detect").json()
        assert "workspace" in data
        assert "cwd"       in data

    def test_detect_has_candidates_list(self, client):
        with patch("subprocess.run", return_value=self._git_stub("/repo\n", 0)):
            data = client.get("/workspace/detect").json()
        assert isinstance(data["candidates"], list)
        assert len(data["candidates"]) >= 1

    def test_recent_starts_empty(self, client):
        # Reset the module-level list before testing
        from smartagent.server import api_system
        api_system._recent_workspaces.clear()
        data = client.get("/workspace/recent").json()
        assert "recent" in data
        assert isinstance(data["recent"], list)

    def test_record_workspace_appears_in_recent(self, client):
        from smartagent.server.api_system import record_workspace, _recent_workspaces
        _recent_workspaces.clear()
        record_workspace("/tmp/my-project")
        data = client.get("/workspace/recent").json()
        paths = [r for r in data["recent"] if "my-project" in r]
        assert len(paths) >= 1

    def test_record_workspace_deduplicates(self):
        from smartagent.server.api_system import record_workspace, _recent_workspaces
        _recent_workspaces.clear()
        record_workspace("/tmp/proj")
        record_workspace("/tmp/proj")   # add same path twice
        assert _recent_workspaces.count("/tmp/proj") <= 1

    def test_record_workspace_capped_at_20(self):
        from smartagent.server.api_system import record_workspace, _recent_workspaces
        _recent_workspaces.clear()
        for i in range(25):
            record_workspace(f"/tmp/proj{i}")
        assert len(_recent_workspaces) <= 20

    def test_recent_returns_reversed_list(self, client):
        from smartagent.server.api_system import record_workspace, _recent_workspaces
        _recent_workspaces.clear()
        record_workspace("/tmp/first")
        record_workspace("/tmp/second")
        record_workspace("/tmp/third")
        data = client.get("/workspace/recent").json()
        # Most recent should be first
        assert data["recent"][0].endswith("third")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /models  and  POST /models/switch
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelsEndpoints:
    # ── nvidia path ───────────────────────────────────────────────────────────

    def test_models_nvidia_returns_list(self, client):
        raw = [{"id": "nvidia/nemotron-3-ultra-550b-a55b", "family": "nemotron", "context": 128000}]
        p = MagicMock(); p.list_models.return_value = raw
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"), \
             patch("smartagent.llm.factory.get_llm_settings",    return_value={"model": "nvidia/nemotron-3-ultra-550b-a55b"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "nvapi-test" if k == "NVIDIA_API_KEY" else d), \
             patch("smartagent.llm.nvidia_provider.NvidiaProvider", return_value=p):
            data = client.get("/models").json()
        assert data["provider"] == "nvidia"
        assert len(data["models"]) == 1
        m = data["models"][0]
        for field in ("name", "id", "size_gb", "family", "provider"):
            assert field in m, f"missing field: {field}"

    def test_models_nvidia_no_key_error(self, client):
        with patch("smartagent.llm.factory.get_active_provider", return_value="nvidia"), \
             patch("smartagent.llm.factory.get_llm_settings",    return_value={"model": "nvidia/nemotron-3-ultra-550b-a55b"}), \
             patch("os.environ.get", return_value=""):
            data = client.get("/models").json()
        assert "error" in data
        assert data["models"] == []

    # ── unknown provider ─────────────────────────────────────────────────────
    # Ollama is not supported — get_active_provider() never returns it in
    # practice, but /models still degrades gracefully instead of 500ing.

    def test_models_unknown_provider_returns_error_key(self, client):
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"), \
             patch("smartagent.llm.factory.get_llm_settings",    return_value={}):
            data = client.get("/models").json()
        assert "error" in data
        assert data["models"] == []

    # ── github path ───────────────────────────────────────────────────────────

    def test_models_github_returns_list(self, client):
        raw = [{"id": "gpt-4o", "family": "gpt", "context": 128000},
               {"id": "gpt-4o-mini", "family": "gpt", "context": 128000}]
        p = MagicMock(); p.list_models.return_value = raw
        with patch("smartagent.llm.factory.get_active_provider", return_value="github"), \
             patch("smartagent.llm.factory.get_llm_settings",    return_value={"model": "gpt-4o"}), \
             patch("os.environ.get", side_effect=lambda k, d="": "tok" if k == "GITHUB_TOKEN" else d), \
             patch("smartagent.llm.github_provider.GitHubProvider", return_value=p):
            data = client.get("/models").json()
        assert data["provider"] == "github"
        assert len(data["models"]) == 2

    def test_models_github_no_token_error(self, client):
        with patch("smartagent.llm.factory.get_active_provider", return_value="github"), \
             patch("smartagent.llm.factory.get_llm_settings",    return_value={"model": "gpt-4o"}), \
             patch("os.environ.get", return_value=""):
            data = client.get("/models").json()
        assert "error" in data
        assert data["models"] == []

    # ── switch model ──────────────────────────────────────────────────────────

    def test_switch_model_success(self, client):
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"), \
             patch("smartagent.llm.factory.switch_provider"):
            resp = client.post("/models/switch", json={"model": "codellama:7b"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["model"]   == "codellama:7b"

    def test_switch_model_records_active_model(self, client):
        from smartagent.server import api_system
        with patch("smartagent.llm.factory.get_active_provider", return_value="ollama"), \
             patch("smartagent.llm.factory.switch_provider"):
            client.post("/models/switch", json={"model": "mistral:7b"})
        assert api_system._active_model == "mistral:7b"


# ═══════════════════════════════════════════════════════════════════════════════
# GET /memory  and  GET /memory/file
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryEndpoints:
    @pytest.fixture
    def workspace_with_memory(self, tmp_path):
        mem_dir = tmp_path / ".agents" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("# Memory\n- [Entry](detail.md) — some note")
        (mem_dir / "detail.md").write_text("---\nname: Detail\n---\nDetail content here.")
        return tmp_path, mem_dir

    def test_memory_list_exists_true(self, client, workspace_with_memory):
        ws, _ = workspace_with_memory
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            data = client.get("/memory").json()
        assert data["exists"] is True

    def test_memory_list_has_files(self, client, workspace_with_memory):
        ws, _ = workspace_with_memory
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            data = client.get("/memory").json()
        names = {f["name"] for f in data["files"]}
        assert "MEMORY.md" in names
        assert "detail.md" in names

    def test_memory_list_no_dir(self, client, tmp_path):
        ws = tmp_path / "no_memory_here"
        ws.mkdir()
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            data = client.get("/memory").json()
        assert data["exists"] is False
        assert data["files"]  == []

    def test_memory_file_read(self, client, workspace_with_memory):
        ws, _ = workspace_with_memory
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            data = client.get("/memory/file", params={"path": "MEMORY.md"}).json()
        assert "content"  in data
        assert "# Memory" in data["content"]

    def test_memory_file_404_for_missing(self, client, workspace_with_memory):
        ws, _ = workspace_with_memory
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            resp = client.get("/memory/file", params={"path": "nonexistent.md"})
        assert resp.status_code == 404

    def test_memory_file_path_traversal_blocked(self, client, workspace_with_memory):
        ws, _ = workspace_with_memory
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            resp = client.get("/memory/file", params={"path": "../../etc/passwd"})
        assert resp.status_code in (400, 404)

    def test_memory_file_has_size(self, client, workspace_with_memory):
        ws, _ = workspace_with_memory
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            data = client.get("/memory/file", params={"path": "MEMORY.md"}).json()
        assert "size" in data
        assert data["size"] > 0

    def test_memory_list_has_preview(self, client, workspace_with_memory):
        ws, _ = workspace_with_memory
        with patch("smartagent.server.api_system._active_workspace", return_value=str(ws)):
            data = client.get("/memory").json()
        for f in data["files"]:
            assert "preview" in f


# ═══════════════════════════════════════════════════════════════════════════════
# GET /git/status  /git/log  /git/diff
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitEndpoints:
    def _run(self, stdout="", stderr="", rc=0):
        r = MagicMock(); r.stdout = stdout; r.stderr = stderr; r.returncode = rc
        return r

    def test_git_status_200(self, client, tmp_path):
        seq = iter([
            self._run("main\n"),       # rev-parse --abbrev-ref
            self._run("0\t0\n"),       # rev-list ahead/behind
            self._run(""),             # status --porcelain
        ])
        with patch("subprocess.run", side_effect=seq):
            resp = client.get("/git/status", params={"workspace": str(tmp_path)})
        assert resp.status_code == 200

    def test_git_status_has_branch(self, client, tmp_path):
        seq = iter([
            self._run("main\n"),
            self._run("0\t2\n"),
            self._run(""),
        ])
        with patch("subprocess.run", side_effect=seq):
            data = client.get("/git/status", params={"workspace": str(tmp_path)}).json()
        assert data.get("branch") == "main"

    def test_git_status_not_git_repo(self, client, tmp_path):
        with patch("subprocess.run", return_value=self._run("", "not a repo", rc=128)):
            data = client.get("/git/status", params={"workspace": str(tmp_path)}).json()
        assert "error" in data

    def test_git_status_changed_files(self, client, tmp_path):
        seq = iter([
            self._run("feature\n"),
            self._run(""),
            self._run(" M src/app.py\n?? new_file.txt\n"),
        ])
        with patch("subprocess.run", side_effect=seq):
            data = client.get("/git/status", params={"workspace": str(tmp_path)}).json()
        assert data["clean"] is False
        assert len(data["changes"]) == 2

    def test_git_status_workspace_not_found(self, client):
        resp = client.get("/git/status", params={"workspace": "/this/does/not/exist"})
        assert resp.status_code == 404

    def test_git_log_200(self, client, tmp_path):
        sep = "|||"
        log_line = sep.join(["abc123", "abc", "init", "Alice", "a@b.com", "2024-01-01", "main"])
        with patch("subprocess.run", return_value=self._run(log_line + "\n")):
            resp = client.get("/git/log", params={"workspace": str(tmp_path)})
        assert resp.status_code == 200

    def test_git_log_returns_commits(self, client, tmp_path):
        sep = "|||"
        log_line = sep.join(["abc123", "abc", "feat: add thing", "Alice", "a@b.com", "2024-01-01", ""])
        with patch("subprocess.run", return_value=self._run(log_line + "\n")):
            data = client.get("/git/log", params={"workspace": str(tmp_path)}).json()
        assert len(data["commits"]) == 1
        commit = data["commits"][0]
        assert commit["hash"]    == "abc123"
        assert commit["message"] == "feat: add thing"
        assert commit["author"]  == "Alice"

    def test_git_log_error(self, client, tmp_path):
        with patch("subprocess.run", return_value=self._run("", "not a repo", rc=1)):
            data = client.get("/git/log", params={"workspace": str(tmp_path)}).json()
        assert data["commits"] == []
        assert "error" in data

    def test_git_diff_200(self, client, tmp_path):
        diff_out = "commit abc123\ndiff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@ -old +new"
        with patch("subprocess.run", return_value=self._run(diff_out)):
            resp = client.get("/git/diff", params={"ref": "abc123", "workspace": str(tmp_path)})
        assert resp.status_code == 200

    def test_git_diff_returns_diff_text(self, client, tmp_path):
        diff_out = "diff --git a/file b/file"
        with patch("subprocess.run", return_value=self._run(diff_out)):
            data = client.get("/git/diff", params={"ref": "HEAD", "workspace": str(tmp_path)}).json()
        assert "diff" in data
        assert "diff --git" in data["diff"]

    def test_git_diff_bad_ref_400(self, client, tmp_path):
        with patch("subprocess.run", return_value=self._run("", "bad ref", rc=128)):
            resp = client.get("/git/diff", params={"ref": "BAD_REF", "workspace": str(tmp_path)})
        assert resp.status_code == 400
