"""
tests/test_integration.py — Task #10: Integration Tests: UI + Backend Together

Exercises the *full* FastAPI application (all routers, no mocked subsystems)
via a single TestClient mounted once per session.  Every test checks HTTP
contracts — status codes and required response field names — not values that
depend on runtime environment (LLM provider reachability, git state, etc.).

Covered flows
─────────────
 1. Health            GET /health            → 200, "status" field
 2. Diagnostics       GET /diagnostics       → 200, required check names, overall status
 3. Jobs lifecycle    register→list→get→pause→resume→DELETE→gone
 4. Provider listing  GET /providers         → 200, list of providers with name+active
 5. Models listing    GET /models            → 200, "models" or "error" key
 6. Workspace detect  GET /workspace/detect  → 200, "workspace" + "cwd" fields
 7. Memory list       GET /memory            → 200, "exists" + "files" fields
 8. Git status        GET /git/status        → 200, "branch" or "error" field
 9. System metrics    GET /metrics           → 200, "cpu_pct" + "mem_pct" fields
10. Model switch      POST /models/switch    → 200, "success" + "model" fields

Cross-test pollution
────────────────────
Each test class or function that touches the jobs store gets a fresh _jobs
dict and a tmp_path-backed _JOBS_FILE so no state leaks between tests.
The session-scoped client shares everything else (routers, state); that is
intentional — it mirrors the real server.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# Session fixture — full app, mounted once
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def full_client(tmp_path_factory):
    """
    Full FastAPI app wrapped in a TestClient.

    We import *after* patching the jobs store so the module-level
    _load_jobs() sees a clean temp file instead of .mark_jobs.json.
    """
    jobs_dir = tmp_path_factory.mktemp("integration_jobs")
    jobs_file = jobs_dir / ".mark_jobs.json"

    # Patch _JOBS_FILE and _jobs before the module runs _load_jobs()
    import smartagent.server.api_jobs as _jobs_mod
    _jobs_mod._JOBS_FILE = jobs_file
    _jobs_mod._jobs = {}

    from smartagent.server.app import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture()
def clean_jobs(tmp_path, full_client):
    """Reset the in-memory jobs store + disk file before each test that uses it."""
    import smartagent.server.api_jobs as _jobs_mod
    _jobs_mod._jobs = {}
    _jobs_mod._JOBS_FILE = tmp_path / ".mark_jobs.json"
    yield _jobs_mod


# ─────────────────────────────────────────────────────────────────────────────
# Flow 1 — Health
# ─────────────────────────────────────────────────────────────────────────────

class TestHealthFlow:
    def test_health_returns_200(self, full_client):
        r = full_client.get("/health")
        assert r.status_code == 200

    def test_health_has_status_field(self, full_client):
        data = full_client.get("/health").json()
        assert "status" in data

    def test_health_status_is_string(self, full_client):
        data = full_client.get("/health").json()
        assert isinstance(data["status"], str)


# ─────────────────────────────────────────────────────────────────────────────
# Flow 2 — Diagnostics
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_CHECK_NAMES = {
    "backend", "database", "llm_provider", "embeddings",
    "vector_db", "git", "workspace", "memory", "websocket", "system",
}

class TestDiagnosticsFlow:
    def test_diagnostics_returns_200(self, full_client):
        r = full_client.get("/diagnostics")
        assert r.status_code == 200

    def test_diagnostics_has_status_field(self, full_client):
        data = full_client.get("/diagnostics").json()
        assert "status" in data

    def test_diagnostics_overall_status_is_valid(self, full_client):
        data = full_client.get("/diagnostics").json()
        assert data["status"] in ("ok", "warn", "error")

    def test_diagnostics_has_checks_list(self, full_client):
        data = full_client.get("/diagnostics").json()
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_diagnostics_all_required_checks_present(self, full_client):
        data = full_client.get("/diagnostics").json()
        names = {c["name"] for c in data["checks"]}
        assert REQUIRED_CHECK_NAMES.issubset(names), (
            f"Missing checks: {REQUIRED_CHECK_NAMES - names}"
        )

    def test_diagnostics_each_check_has_status_and_message(self, full_client):
        data = full_client.get("/diagnostics").json()
        for check in data["checks"]:
            assert "status" in check,  f"check {check.get('name')} missing 'status'"
            assert "message" in check, f"check {check.get('name')} missing 'message'"

    def test_diagnostics_backend_check_always_ok(self, full_client):
        data = full_client.get("/diagnostics").json()
        backend = next(c for c in data["checks"] if c["name"] == "backend")
        assert backend["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Flow 3 — Jobs lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class TestJobsLifecycleFlow:
    def _register(self, mod, goal="integration test goal") -> str:
        return mod.register_job(goal=goal, workspace="/tmp/integration")

    def test_jobs_list_empty_on_fresh_store(self, full_client, clean_jobs):
        r = full_client.get("/jobs")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["jobs"] == []

    def test_register_job_appears_in_list(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        r = full_client.get("/jobs")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["jobs"][0]["id"] == job_id

    def test_get_job_by_id_returns_200(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        r = full_client.get(f"/jobs/{job_id}")
        assert r.status_code == 200

    def test_get_job_has_required_fields(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        data = full_client.get(f"/jobs/{job_id}").json()
        for field in ("id", "goal", "status", "created_at", "progress"):
            assert field in data, f"job missing field: {field}"

    def test_get_job_id_matches(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        data = full_client.get(f"/jobs/{job_id}").json()
        assert data["id"] == job_id

    def test_get_unknown_job_returns_404(self, full_client, clean_jobs):
        r = full_client.get(f"/jobs/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_pause_running_job_returns_200(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        r = full_client.post(f"/jobs/{job_id}/pause")
        assert r.status_code == 200

    def test_pause_sets_status_paused(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        full_client.post(f"/jobs/{job_id}/pause")
        data = full_client.get(f"/jobs/{job_id}").json()
        assert data["status"] == "paused"

    def test_pause_response_has_success_field(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        data = full_client.post(f"/jobs/{job_id}/pause").json()
        assert data.get("success") is True

    def test_pause_unknown_job_returns_404(self, full_client, clean_jobs):
        r = full_client.post(f"/jobs/{uuid.uuid4()}/pause")
        assert r.status_code == 404

    def test_pause_already_paused_returns_400(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        full_client.post(f"/jobs/{job_id}/pause")
        r = full_client.post(f"/jobs/{job_id}/pause")
        assert r.status_code == 400

    def test_resume_paused_job_returns_200(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        full_client.post(f"/jobs/{job_id}/pause")
        r = full_client.post(f"/jobs/{job_id}/resume")
        assert r.status_code == 200

    def test_resume_sets_status_running(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        full_client.post(f"/jobs/{job_id}/pause")
        full_client.post(f"/jobs/{job_id}/resume")
        data = full_client.get(f"/jobs/{job_id}").json()
        assert data["status"] == "running"

    def test_resume_unknown_job_returns_404(self, full_client, clean_jobs):
        r = full_client.post(f"/jobs/{uuid.uuid4()}/resume")
        assert r.status_code == 404

    def test_delete_job_returns_200(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        r = full_client.delete(f"/jobs/{job_id}")
        assert r.status_code == 200

    def test_delete_response_has_success_field(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        data = full_client.delete(f"/jobs/{job_id}").json()
        assert data.get("success") is True

    def test_delete_removes_job_from_list(self, full_client, clean_jobs):
        job_id = self._register(clean_jobs)
        full_client.delete(f"/jobs/{job_id}")
        r = full_client.get("/jobs")
        ids = [j["id"] for j in r.json()["jobs"]]
        assert job_id not in ids

    def test_delete_unknown_job_returns_404(self, full_client, clean_jobs):
        r = full_client.delete(f"/jobs/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_no_cross_test_pollution(self, full_client, clean_jobs):
        """Deleting a job leaves the store completely empty."""
        job_id = self._register(clean_jobs)
        full_client.delete(f"/jobs/{job_id}")
        data = full_client.get("/jobs").json()
        assert data["count"] == 0

    def test_list_has_count_field(self, full_client, clean_jobs):
        self._register(clean_jobs)
        data = full_client.get("/jobs").json()
        assert "count" in data
        assert data["count"] == len(data["jobs"])


# ─────────────────────────────────────────────────────────────────────────────
# Flow 4 — Provider listing
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderListingFlow:
    def test_providers_returns_200(self, full_client):
        r = full_client.get("/providers")
        assert r.status_code == 200

    def test_providers_has_providers_list(self, full_client):
        data = full_client.get("/providers").json()
        assert "providers" in data
        assert isinstance(data["providers"], list)

    def test_providers_list_not_empty(self, full_client):
        data = full_client.get("/providers").json()
        assert len(data["providers"]) >= 1

    def test_each_provider_has_name_field(self, full_client):
        data = full_client.get("/providers").json()
        for p in data["providers"]:
            assert "name" in p, f"provider {p} missing 'name'"

    def test_each_provider_has_active_field(self, full_client):
        data = full_client.get("/providers").json()
        for p in data["providers"]:
            assert "active" in p, f"provider {p} missing 'active'"

    def test_exactly_one_provider_is_active(self, full_client):
        data = full_client.get("/providers").json()
        active = [p for p in data["providers"] if p["active"]]
        assert len(active) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Flow 5 — Models listing
# ─────────────────────────────────────────────────────────────────────────────

class TestModelsListingFlow:
    def test_models_returns_200(self, full_client):
        r = full_client.get("/models")
        assert r.status_code == 200

    def test_models_has_models_or_error_key(self, full_client):
        data = full_client.get("/models").json()
        assert "models" in data or "error" in data

    def test_models_has_provider_field(self, full_client):
        data = full_client.get("/models").json()
        assert "provider" in data

    def test_models_list_is_list_when_present(self, full_client):
        data = full_client.get("/models").json()
        if "models" in data:
            assert isinstance(data["models"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Flow 6 — Workspace detect
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkspaceDetectFlow:
    def test_workspace_detect_returns_200(self, full_client):
        r = full_client.get("/workspace/detect")
        assert r.status_code == 200

    def test_workspace_detect_has_workspace_field(self, full_client):
        data = full_client.get("/workspace/detect").json()
        assert "workspace" in data

    def test_workspace_detect_has_cwd_field(self, full_client):
        data = full_client.get("/workspace/detect").json()
        assert "cwd" in data

    def test_workspace_detect_cwd_is_string(self, full_client):
        data = full_client.get("/workspace/detect").json()
        assert isinstance(data["cwd"], str)

    def test_workspace_detect_has_candidates_list(self, full_client):
        data = full_client.get("/workspace/detect").json()
        assert "candidates" in data
        assert isinstance(data["candidates"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Flow 7 — Memory file list
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryListFlow:
    def test_memory_returns_200(self, full_client):
        r = full_client.get("/memory")
        assert r.status_code == 200

    def test_memory_has_exists_field(self, full_client):
        data = full_client.get("/memory").json()
        assert "exists" in data

    def test_memory_has_files_field(self, full_client):
        data = full_client.get("/memory").json()
        assert "files" in data

    def test_memory_files_is_list(self, full_client):
        data = full_client.get("/memory").json()
        assert isinstance(data["files"], list)

    def test_memory_exists_is_bool(self, full_client):
        data = full_client.get("/memory").json()
        assert isinstance(data["exists"], bool)


# ─────────────────────────────────────────────────────────────────────────────
# Flow 8 — Git status
# ─────────────────────────────────────────────────────────────────────────────

class TestGitStatusFlow:
    def test_git_status_returns_200(self, full_client):
        r = full_client.get("/git/status")
        assert r.status_code == 200

    def test_git_status_has_branch_or_error(self, full_client):
        data = full_client.get("/git/status").json()
        assert "branch" in data or "error" in data

    def test_git_status_workspace_field_present(self, full_client):
        data = full_client.get("/git/status").json()
        assert "workspace" in data

    def test_git_status_clean_field_when_in_repo(self, full_client):
        data = full_client.get("/git/status").json()
        # If we're in a repo, "clean" must be present
        if "branch" in data:
            assert "clean" in data


# ─────────────────────────────────────────────────────────────────────────────
# Flow 9 — System metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemMetricsFlow:
    def test_metrics_returns_200(self, full_client):
        r = full_client.get("/metrics")
        assert r.status_code == 200

    def test_metrics_has_cpu_pct(self, full_client):
        data = full_client.get("/metrics").json()
        assert "cpu_pct" in data

    def test_metrics_has_mem_pct(self, full_client):
        data = full_client.get("/metrics").json()
        assert "mem_pct" in data

    def test_metrics_cpu_pct_is_numeric(self, full_client):
        data = full_client.get("/metrics").json()
        assert isinstance(data["cpu_pct"], (int, float))

    def test_metrics_mem_pct_is_numeric(self, full_client):
        data = full_client.get("/metrics").json()
        assert isinstance(data["mem_pct"], (int, float))


# ─────────────────────────────────────────────────────────────────────────────
# Flow 10 — Model switch
# ─────────────────────────────────────────────────────────────────────────────

class TestModelSwitchFlow:
    def test_model_switch_returns_200(self, full_client):
        r = full_client.post("/models/switch", json={"model": "test-model"})
        assert r.status_code == 200

    def test_model_switch_has_success_field(self, full_client):
        data = full_client.post("/models/switch", json={"model": "test-model"}).json()
        assert "success" in data

    def test_model_switch_success_is_bool(self, full_client):
        data = full_client.post("/models/switch", json={"model": "test-model"}).json()
        assert isinstance(data["success"], bool)

    def test_model_switch_has_model_field(self, full_client):
        data = full_client.post("/models/switch", json={"model": "test-model"}).json()
        assert "model" in data

    def test_model_switch_model_reflects_request(self, full_client):
        data = full_client.post("/models/switch", json={"model": "my-model"}).json()
        assert data["model"] == "my-model"
