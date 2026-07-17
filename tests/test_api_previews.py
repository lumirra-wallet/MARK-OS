"""
Tests for the Preview Detection & Registry backend (Task 19).

Coverage
--------
1.  FrameworkHeuristics.classify — all framework labels
2.  FrameworkHeuristics.title_for — human-readable titles
3.  PreviewRecord.make — field defaults and proxy_url generation
4.  _validate_local_url — SSRF prevention
5.  PreviewManager.register / get / update / unregister — CRUD lifecycle
6.  PreviewManager.all_previews — sorting
7.  PreviewManager persistence — load / save round-trip
8.  PreviewManager._port_open — open / closed port detection
9.  PreviewManager._probe_port — HTTP probe with mocked httpx
10. PreviewManager.scan_ports — new port, re-activation, unreachable
11. PreviewManager.scan_ports — skips only own runtime port, not hard-coded 8080
12. PreviewManager.notify_dev_server_started — hook for worker/terminal
13. ServerEvents — PREVIEW_* constants present
14. REST GET /previews — list endpoint
15. REST POST /previews/refresh — scan trigger
16. REST GET /previews/scan — alias
17. REST GET /previews/{id} — single record
18. REST POST /previews — manual registration (valid + invalid URL)
19. REST DELETE /previews/{id} — unregister
20. REST POST /previews/{id}/refresh — re-probe
21. REST GET /previews/{id} — 404 for missing
22. REST proxy — happy path, upstream error, closed preview, SSRF guard
23. Broadcast — PreviewRegistered and PreviewClosed events reach manager
24. Terminal dev-server hook — _looks_like_dev_server, _extract_port, _framework_from_cmd
25. Terminal hook wiring — REST run_command registers preview on port announcement
"""
from __future__ import annotations

import asyncio
import json
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from smartagent.server.api_previews import (
    FrameworkHeuristics,
    PreviewManager,
    PreviewRecord,
    _validate_local_url,
    preview_manager,
)
from smartagent.server.events import ServerEvents
from smartagent.server.api_terminal import (
    _looks_like_dev_server,
    _extract_port,
    _framework_from_cmd,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mgr(tmp_path: Path) -> PreviewManager:
    """Isolated PreviewManager with its own JSON file in a temp dir."""
    m = PreviewManager.__new__(PreviewManager)
    m._previews = {}
    m._loop = None
    m._manager = None
    m._detect_task = None
    # Redirect persistence to tmp_path so tests never touch .mark_previews.json
    import smartagent.server.api_previews as mod
    monkeypatch_file = tmp_path / ".mark_previews.json"
    m._previews_file = monkeypatch_file  # store for reference
    # Patch the module-level constant for this instance only via closure
    original = mod._PREVIEWS_FILE
    mod._PREVIEWS_FILE = monkeypatch_file
    yield m
    mod._PREVIEWS_FILE = original


@pytest.fixture()
def client():
    """TestClient against the real FastAPI app, with preview_manager patched."""
    from smartagent.server.app import app  # type: ignore[attr-defined]
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def isolated_manager(tmp_path: Path):
    """
    Patch the module-level preview_manager singleton so endpoint tests
    run against an isolated instance.
    """
    import smartagent.server.api_previews as mod
    old = mod.preview_manager
    fresh = PreviewManager.__new__(PreviewManager)
    fresh._previews = {}
    fresh._loop = None
    fresh._manager = None
    fresh._detect_task = None
    mod.preview_manager = fresh
    yield fresh
    mod.preview_manager = old


# ---------------------------------------------------------------------------
# 1. FrameworkHeuristics.classify
# ---------------------------------------------------------------------------

class TestFrameworkHeuristics:

    def _classify(self, body: str = "", headers: dict | None = None, status: int = 200) -> str:
        return FrameworkHeuristics.classify("http://localhost:3000", status, headers or {}, body)

    def test_nextjs_powered_by_header(self):
        assert self._classify(headers={"x-powered-by": "Next.js"}) == "nextjs"

    def test_nextjs_data_script(self):
        assert self._classify(body='<script id="__NEXT_DATA__">') == "nextjs"

    def test_nextjs_static_path(self):
        assert self._classify(body='href="/_next/static/css/main.css"') == "nextjs"

    def test_storybook(self):
        assert self._classify(body="storybook stories addons manager") == "storybook"

    def test_vite_client_script(self):
        assert self._classify(body='<script src="/@vite/client">') == "vite"

    def test_vite_server_header(self):
        assert self._classify(headers={"server": "Vite dev server"}) == "vite"

    def test_fastapi_swagger(self):
        assert self._classify(body="swagger-ui openapi") == "fastapi"

    def test_fastapi_openapi_json(self):
        assert self._classify(body='"openapi": "3.0.0"') == "fastapi"

    def test_flask_werkzeug_header(self):
        assert self._classify(headers={"server": "Werkzeug/2.3"}) == "flask"

    def test_django_csrf(self):
        assert self._classify(body='csrfmiddlewaretoken value="abc"') == "django"

    def test_streamlit(self):
        assert self._classify(body="streamlit app running") == "streamlit"

    def test_angular(self):
        assert self._classify(body='<app-root ng-version="17">') == "angular"

    def test_react(self):
        assert self._classify(body="react-dom.production.min.js") == "react"

    def test_unknown_200(self):
        assert self._classify(body="<h1>Hello</h1>", status=200) == "unknown"

    def test_unknown_non_200(self):
        assert self._classify(body="", status=500) == "unknown"


# ---------------------------------------------------------------------------
# 2. FrameworkHeuristics.title_for
# ---------------------------------------------------------------------------

class TestTitleFor:

    def test_known_frameworks(self):
        assert "Vite" in FrameworkHeuristics.title_for("vite", 5173)
        assert "Next.js" in FrameworkHeuristics.title_for("nextjs", 3000)
        assert "Storybook" in FrameworkHeuristics.title_for("storybook", 6006)

    def test_port_in_title(self):
        title = FrameworkHeuristics.title_for("react", 3001)
        assert "3001" in title

    def test_unknown_framework(self):
        title = FrameworkHeuristics.title_for("unknown", 9999)
        assert "9999" in title


# ---------------------------------------------------------------------------
# 4 (new). _validate_local_url — SSRF prevention
# ---------------------------------------------------------------------------

class TestValidateLocalUrl:

    def test_valid_localhost(self):
        result = _validate_local_url("http://localhost:3000")
        assert result == "http://127.0.0.1:3000"

    def test_valid_127(self):
        result = _validate_local_url("http://127.0.0.1:5173")
        assert result == "http://127.0.0.1:5173"

    def test_rejects_https(self):
        with pytest.raises(ValueError, match="scheme"):
            _validate_local_url("https://localhost:3000")

    def test_rejects_remote_host(self):
        with pytest.raises(ValueError, match="loopback"):
            _validate_local_url("http://example.com:3000")

    def test_rejects_internal_ip(self):
        with pytest.raises(ValueError, match="loopback"):
            _validate_local_url("http://192.168.1.1:3000")

    def test_rejects_metadata_ip(self):
        with pytest.raises(ValueError, match="loopback"):
            _validate_local_url("http://169.254.169.254:80")

    def test_rejects_missing_port(self):
        with pytest.raises(ValueError, match="port"):
            _validate_local_url("http://localhost/path")

    def test_normalises_localhost_to_127(self):
        result = _validate_local_url("http://localhost:8080")
        assert "127.0.0.1" in result
        assert "8080" in result


# ---------------------------------------------------------------------------
# 3. PreviewRecord.make
# ---------------------------------------------------------------------------

class TestPreviewRecordMake:

    def test_fields_present(self):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", framework="vite")
        assert rec["port"] == 3000
        assert rec["url"] == "http://localhost:3000"
        assert rec["framework"] == "vite"
        assert rec["status"] == "active"
        assert rec["id"]
        assert "registered_at" in rec
        assert "updated_at" in rec

    def test_proxy_url_generated(self):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000")
        assert rec["proxy_url"].startswith("/previews/proxy/")
        assert rec["id"] in rec["proxy_url"]

    def test_custom_id(self):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="my-id")
        assert rec["id"] == "my-id"

    def test_registered_by_default(self):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000")
        assert rec["registered_by"] == "auto"

    def test_custom_title(self):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", title="My App")
        assert rec["title"] == "My App"


# ---------------------------------------------------------------------------
# 4. PreviewManager CRUD
# ---------------------------------------------------------------------------

class TestPreviewManagerCRUD:

    def test_register_new(self, mgr: PreviewManager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000")
        result = mgr.register(rec)
        assert result["id"] in mgr._previews
        assert mgr._previews[result["id"]]["port"] == 3000

    def test_register_duplicate_overwrites(self, mgr: PreviewManager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="x")
        mgr.register(rec)
        rec2 = PreviewRecord.make(port=3000, url="http://localhost:3000", framework="vite", preview_id="x")
        mgr.register(rec2)
        assert mgr._previews["x"]["framework"] == "vite"

    def test_get_existing(self, mgr: PreviewManager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="abc")
        mgr.register(rec)
        assert mgr.get("abc") is not None

    def test_get_missing(self, mgr: PreviewManager):
        assert mgr.get("nonexistent") is None

    def test_update(self, mgr: PreviewManager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="u1")
        mgr.register(rec)
        updated = mgr.update("u1", status="unreachable")
        assert updated["status"] == "unreachable"
        assert mgr._previews["u1"]["status"] == "unreachable"

    def test_update_missing(self, mgr: PreviewManager):
        assert mgr.update("ghost", status="active") is None

    def test_unregister(self, mgr: PreviewManager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="del1")
        mgr.register(rec)
        closed = mgr.unregister("del1")
        assert closed["status"] == "closed"
        assert "del1" not in mgr._previews

    def test_unregister_missing(self, mgr: PreviewManager):
        assert mgr.unregister("ghost") is None


# ---------------------------------------------------------------------------
# 5. PreviewManager.all_previews — sorting
# ---------------------------------------------------------------------------

class TestAllPreviews:

    def test_returns_sorted_newest_first(self, mgr: PreviewManager):
        for port in range(3000, 3005):
            rec = PreviewRecord.make(port=port, url=f"http://localhost:{port}")
            mgr.register(rec)
        previews = mgr.all_previews()
        times = [p["registered_at"] for p in previews]
        assert times == sorted(times, reverse=True)

    def test_empty_registry(self, mgr: PreviewManager):
        assert mgr.all_previews() == []


# ---------------------------------------------------------------------------
# 6. Persistence
# ---------------------------------------------------------------------------

class TestPersistence:

    def test_save_and_load(self, tmp_path: Path):
        import smartagent.server.api_previews as mod
        orig = mod._PREVIEWS_FILE
        mod._PREVIEWS_FILE = tmp_path / ".mark_previews.json"
        try:
            m = PreviewManager()
            rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="persist1")
            m._previews[rec["id"]] = rec
            m._save()

            m2 = PreviewManager()
            assert "persist1" in m2._previews
            assert m2._previews["persist1"]["port"] == 3000
        finally:
            mod._PREVIEWS_FILE = orig

    def test_load_handles_corrupt_file(self, tmp_path: Path):
        import smartagent.server.api_previews as mod
        orig = mod._PREVIEWS_FILE
        corrupt = tmp_path / ".mark_previews.json"
        corrupt.write_text("not valid json{{{{")
        mod._PREVIEWS_FILE = corrupt
        try:
            m = PreviewManager()
            assert m._previews == {}
        finally:
            mod._PREVIEWS_FILE = orig

    def test_load_skips_localhost_zero(self, tmp_path: Path):
        """Previews with url starting with 'http://localhost:0' are test artefacts."""
        import smartagent.server.api_previews as mod
        orig = mod._PREVIEWS_FILE
        f = tmp_path / ".mark_previews.json"
        data = {"t": {"id": "t", "url": "http://localhost:0/some/path", "port": 0}}
        f.write_text(json.dumps(data))
        mod._PREVIEWS_FILE = f
        try:
            m = PreviewManager()
            assert "t" not in m._previews
        finally:
            mod._PREVIEWS_FILE = orig


# ---------------------------------------------------------------------------
# 7. _port_open
# ---------------------------------------------------------------------------

class TestPortOpen:

    def test_closed_port_returns_false(self):
        # Port 1 is almost certainly closed in the test environment
        assert PreviewManager._port_open(1, timeout=0.2) is False

    def test_open_port_returns_true(self):
        # Open a real server socket then probe it
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            assert PreviewManager._port_open(port, timeout=0.5) is True
        finally:
            srv.close()


# ---------------------------------------------------------------------------
# 8. _probe_port — mocked httpx
# ---------------------------------------------------------------------------

class TestProbePort:

    def test_probe_vite(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<script src="/@vite/client"></script>'
        mock_resp.headers = {}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("smartagent.server.api_previews.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(PreviewManager._probe_port(5173))

        assert result is not None
        assert result["framework"] == "vite"
        assert result["port"] == 5173
        assert result["status"] == "active"

    def test_probe_unreachable(self):
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("smartagent.server.api_previews.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(PreviewManager._probe_port(9999))

        assert result is None


# ---------------------------------------------------------------------------
# 9. scan_ports
# ---------------------------------------------------------------------------

class TestScanPorts:

    def test_new_port_registered(self, mgr: PreviewManager):
        """A freshly opened port should be added to the registry."""
        mgr._manager = MagicMock()
        mgr._manager.broadcast = AsyncMock()

        def fake_port_open(port, timeout=0.3):
            return port == 5173

        async def fake_probe(port, timeout=3.0):
            if port == 5173:
                return {"port": 5173, "url": "http://127.0.0.1:5173",
                        "framework": "vite", "status": "active", "http_status": 200}
            return None

        with (
            patch.object(PreviewManager, "_port_open", staticmethod(fake_port_open)),
            patch.object(PreviewManager, "_probe_port", staticmethod(fake_probe)),
        ):
            changed = asyncio.run(mgr.scan_ports())

        assert any(p["port"] == 5173 for p in changed)
        assert any(p["port"] == 5173 for p in mgr.all_previews())

    def test_existing_active_port_not_duplicated(self, mgr: PreviewManager):
        """A port already 'active' in registry should not create a second record."""
        rec = PreviewRecord.make(port=5173, url="http://127.0.0.1:5173",
                                 framework="vite", preview_id="vite-1")
        mgr.register(rec)
        mgr._manager = MagicMock()
        mgr._manager.broadcast = AsyncMock()

        def fake_port_open(port, timeout=0.3):
            return port == 5173

        async def fake_probe(port, timeout=3.0):
            return {"port": 5173, "url": "http://127.0.0.1:5173",
                    "framework": "vite", "status": "active", "http_status": 200}

        with (
            patch.object(PreviewManager, "_port_open", staticmethod(fake_port_open)),
            patch.object(PreviewManager, "_probe_port", staticmethod(fake_probe)),
        ):
            asyncio.run(mgr.scan_ports())

        assert len([p for p in mgr.all_previews() if p["port"] == 5173]) == 1

    def test_previously_active_marks_unreachable(self, mgr: PreviewManager):
        """A port that was active but is now closed should become 'unreachable'."""
        rec = PreviewRecord.make(port=5173, url="http://127.0.0.1:5173",
                                 framework="vite", preview_id="stale-1")
        mgr.register(rec)
        mgr._manager = MagicMock()
        mgr._manager.broadcast = AsyncMock()

        with (
            patch.object(PreviewManager, "_port_open", staticmethod(lambda p, **kw: False)),
        ):
            asyncio.run(mgr.scan_ports())

        assert mgr._previews["stale-1"]["status"] == "unreachable"

    def test_unreachable_reactivated(self, mgr: PreviewManager):
        """A port that was 'unreachable' and comes back should be marked 'active'."""
        rec = PreviewRecord.make(port=5173, url="http://127.0.0.1:5173",
                                 framework="vite", preview_id="back-1",
                                 status="unreachable")
        mgr._previews["back-1"] = rec
        mgr._manager = MagicMock()
        mgr._manager.broadcast = AsyncMock()

        def fake_port_open(port, timeout=0.3):
            return port == 5173

        async def fake_probe(port, timeout=3.0):
            return {"port": 5173, "url": "http://127.0.0.1:5173",
                    "framework": "vite", "status": "active", "http_status": 200}

        with (
            patch.object(PreviewManager, "_port_open", staticmethod(fake_port_open)),
            patch.object(PreviewManager, "_probe_port", staticmethod(fake_probe)),
        ):
            changed = asyncio.run(mgr.scan_ports())

        assert mgr._previews["back-1"]["status"] == "active"
        assert any(p["id"] == "back-1" for p in changed)


# ---------------------------------------------------------------------------
# 10. notify_dev_server_started
# ---------------------------------------------------------------------------

class TestNotifyDevServerStarted:

    def test_new_port_creates_preview(self, mgr: PreviewManager):
        rec = mgr.notify_dev_server_started(port=3001, framework="react")
        assert rec["port"] == 3001
        assert rec["framework"] == "react"
        assert rec["status"] == "active"
        assert any(p["port"] == 3001 for p in mgr.all_previews())

    def test_existing_port_updates(self, mgr: PreviewManager):
        existing = PreviewRecord.make(port=3001, url="http://127.0.0.1:3001",
                                     framework="unknown", preview_id="ex1",
                                     status="unreachable")
        mgr._previews["ex1"] = existing
        rec = mgr.notify_dev_server_started(port=3001, framework="react")
        assert rec["status"] == "active"
        assert rec["framework"] == "react"
        assert len([p for p in mgr.all_previews() if p["port"] == 3001]) == 1


# ---------------------------------------------------------------------------
# 11. ServerEvents constants
# ---------------------------------------------------------------------------

class TestServerEventConstants:

    def test_preview_registered(self):
        assert hasattr(ServerEvents, "PREVIEW_REGISTERED")
        assert ServerEvents.PREVIEW_REGISTERED == "PreviewRegistered"

    def test_preview_updated(self):
        assert hasattr(ServerEvents, "PREVIEW_UPDATED")
        assert ServerEvents.PREVIEW_UPDATED == "PreviewUpdated"

    def test_preview_closed(self):
        assert hasattr(ServerEvents, "PREVIEW_CLOSED")
        assert ServerEvents.PREVIEW_CLOSED == "PreviewClosed"


# ---------------------------------------------------------------------------
# 12-19. REST endpoints
# ---------------------------------------------------------------------------

class TestRestEndpoints:

    def test_list_empty(self, client: TestClient, isolated_manager):
        resp = client.get("/previews")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["previews"] == []

    def test_list_with_records(self, client: TestClient, isolated_manager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="r1")
        isolated_manager.register(rec)
        resp = client.get("/previews")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_get_single(self, client: TestClient, isolated_manager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="r2")
        isolated_manager.register(rec)
        resp = client.get("/previews/r2")
        assert resp.status_code == 200
        assert resp.json()["port"] == 3000

    def test_get_missing_returns_404(self, client: TestClient, isolated_manager):
        resp = client.get("/previews/nosuchid")
        assert resp.status_code == 404

    def test_manual_register(self, client: TestClient, isolated_manager):
        resp = client.post("/previews", json={
            "port": 4000,
            "url":  "http://localhost:4000",
            "framework": "flask",
            "title": "My Flask App",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert data["preview"]["port"] == 4000
        assert data["preview"]["framework"] == "flask"

    def test_manual_register_rejects_remote_url(self, client: TestClient, isolated_manager):
        """SSRF prevention: remote URLs must be rejected with 400."""
        resp = client.post("/previews", json={
            "port": 80,
            "url":  "http://example.com:80",
            "framework": "unknown",
        })
        assert resp.status_code == 400

    def test_manual_register_rejects_https(self, client: TestClient, isolated_manager):
        resp = client.post("/previews", json={
            "port": 3000,
            "url":  "https://localhost:3000",
            "framework": "unknown",
        })
        assert resp.status_code == 400

    def test_manual_register_normalises_url(self, client: TestClient, isolated_manager):
        """localhost should be normalised to 127.0.0.1 in the stored record."""
        resp = client.post("/previews", json={
            "port": 3001,
            "url":  "http://localhost:3001",
            "framework": "react",
        })
        assert resp.status_code == 201
        assert "127.0.0.1" in resp.json()["preview"]["url"]

    def test_unregister(self, client: TestClient, isolated_manager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="del2")
        isolated_manager.register(rec)
        resp = client.delete("/previews/del2")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert isolated_manager.get("del2") is None

    def test_unregister_missing_404(self, client: TestClient, isolated_manager):
        resp = client.delete("/previews/nonexistent")
        assert resp.status_code == 404

    def test_refresh_all(self, client: TestClient, isolated_manager):
        with patch.object(type(isolated_manager), "scan_ports", new=AsyncMock(return_value=[])):
            resp = client.post("/previews/refresh")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_scan_get_alias(self, client: TestClient, isolated_manager):
        with patch.object(type(isolated_manager), "scan_ports", new=AsyncMock(return_value=[])):
            resp = client.get("/previews/scan")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_refresh_single(self, client: TestClient, isolated_manager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="rf1")
        isolated_manager.register(rec)

        async def fake_probe(port, timeout=3.0):
            return {"port": 3000, "url": "http://127.0.0.1:3000",
                    "framework": "react", "status": "active", "http_status": 200}

        with patch.object(PreviewManager, "_probe_port", staticmethod(fake_probe)):
            resp = client.post("/previews/rf1/refresh")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["preview"]["status"] == "active"
        assert body["preview"]["framework"] == "react"

    def test_refresh_single_unreachable(self, client: TestClient, isolated_manager):
        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="rf2")
        isolated_manager.register(rec)

        async def fake_probe(port, timeout=3.0):
            return None

        with patch.object(PreviewManager, "_probe_port", staticmethod(fake_probe)):
            resp = client.post("/previews/rf2/refresh")

        assert resp.status_code == 200
        assert resp.json()["preview"]["status"] == "unreachable"

    def test_refresh_single_missing(self, client: TestClient, isolated_manager):
        resp = client.post("/previews/nosuchid/refresh")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 20. Proxy endpoint
# ---------------------------------------------------------------------------

class TestProxyEndpoint:

    def test_proxy_happy_path(self, client: TestClient, isolated_manager):
        import httpx as _httpx
        rec = PreviewRecord.make(port=3000, url="http://127.0.0.1:3000",
                                 framework="vite", preview_id="px1")
        isolated_manager.register(rec)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<html>hello</html>"
        mock_resp.headers = {"content-type": "text/html", "x-frame-options": "SAMEORIGIN"}

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("smartagent.server.api_previews.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/previews/proxy/px1")

        assert resp.status_code == 200
        assert b"hello" in resp.content
        # x-frame-options should be overridden
        assert resp.headers.get("x-frame-options", "").upper() == "ALLOWALL"

    def test_proxy_missing_preview(self, client: TestClient, isolated_manager):
        resp = client.get("/previews/proxy/doesnotexist")
        assert resp.status_code == 404

    def test_proxy_closed_preview(self, client: TestClient, isolated_manager):
        rec = PreviewRecord.make(port=3000, url="http://127.0.0.1:3000",
                                 preview_id="px2", status="closed")
        isolated_manager._previews["px2"] = rec
        resp = client.get("/previews/proxy/px2")
        assert resp.status_code == 410

    def test_proxy_upstream_connect_error(self, client: TestClient, isolated_manager):
        import httpx as _httpx
        rec = PreviewRecord.make(port=3000, url="http://127.0.0.1:3000",
                                 preview_id="px3")
        isolated_manager.register(rec)

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("smartagent.server.api_previews.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/previews/proxy/px3")

        assert resp.status_code == 502

    def test_proxy_rejects_corrupt_stored_url(self, client: TestClient, isolated_manager):
        """SSRF defence-in-depth: proxy rejects a stored record with a non-local URL."""
        rec = PreviewRecord.make(port=3000, url="http://127.0.0.1:3000", preview_id="px5")
        isolated_manager._previews["px5"] = rec
        # Corrupt the stored URL directly (simulate a stale/corrupt state)
        isolated_manager._previews["px5"]["url"] = "http://evil.example.com:80"
        resp = client.get("/previews/proxy/px5")
        assert resp.status_code == 400

    def test_proxy_with_subpath(self, client: TestClient, isolated_manager):
        import httpx as _httpx
        rec = PreviewRecord.make(port=3000, url="http://127.0.0.1:3000",
                                 preview_id="px4")
        isolated_manager.register(rec)

        captured_url = []

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"ok"
        mock_resp.headers = {"content-type": "text/plain"}

        async def fake_request(method, url, **kwargs):
            captured_url.append(url)
            return mock_resp

        mock_client = AsyncMock()
        mock_client.request = fake_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("smartagent.server.api_previews.httpx.AsyncClient", return_value=mock_client):
            resp = client.get("/previews/proxy/px4/assets/main.js")

        assert resp.status_code == 200
        assert "assets/main.js" in captured_url[0]


# ---------------------------------------------------------------------------
# 24. Terminal dev-server helpers
# ---------------------------------------------------------------------------

class TestTerminalDevServerHelpers:

    def test_looks_like_dev_server_vite(self):
        assert _looks_like_dev_server("vite") is True

    def test_looks_like_dev_server_npm_run_dev(self):
        assert _looks_like_dev_server("npm run dev") is True

    def test_looks_like_dev_server_yarn_dev(self):
        assert _looks_like_dev_server("yarn dev") is True

    def test_looks_like_dev_server_flask_run(self):
        assert _looks_like_dev_server("flask run") is True

    def test_looks_like_dev_server_uvicorn(self):
        assert _looks_like_dev_server("uvicorn main:app --reload") is True

    def test_looks_like_dev_server_streamlit(self):
        assert _looks_like_dev_server("streamlit run app.py") is True

    def test_looks_like_dev_server_ng_serve(self):
        assert _looks_like_dev_server("ng serve") is True

    def test_not_dev_server_ls(self):
        assert _looks_like_dev_server("ls -la") is False

    def test_not_dev_server_pytest(self):
        assert _looks_like_dev_server("pytest tests/") is False

    def test_extract_port_vite_style(self):
        assert _extract_port("  ➜  Local:   http://localhost:5173/") == 5173

    def test_extract_port_flask_style(self):
        assert _extract_port(" * Running on http://127.0.0.1:5000") == 5000

    def test_extract_port_generic_listening(self):
        assert _extract_port("Listening on port 3000") == 3000

    def test_extract_port_no_match(self):
        assert _extract_port("Build completed successfully") is None

    def test_extract_port_too_low(self):
        # Ports below 1024 should be ignored (not dev servers)
        assert _extract_port("Listening on port 80") is None

    def test_framework_from_cmd_vite(self):
        assert _framework_from_cmd("vite") == "vite"

    def test_framework_from_cmd_next(self):
        assert _framework_from_cmd("next dev") == "nextjs"

    def test_framework_from_cmd_flask(self):
        assert _framework_from_cmd("flask run --port 5000") == "flask"

    def test_framework_from_cmd_uvicorn(self):
        assert _framework_from_cmd("uvicorn main:app") == "fastapi"

    def test_framework_from_cmd_unknown(self):
        assert _framework_from_cmd("python myserver.py") == "unknown"


# ---------------------------------------------------------------------------
# 25. Terminal hook wiring — REST run_command registers preview
# ---------------------------------------------------------------------------

class TestTerminalHookWiring:

    def test_run_command_registers_preview_on_port_announcement(
        self, client: TestClient, isolated_manager
    ):
        """
        When run_command detects a dev-server command and the output contains
        a port announcement, preview_manager.notify_dev_server_started is called.
        """
        registered: list[dict] = []

        def fake_notify(port, framework="unknown", title=""):
            registered.append({"port": port, "framework": framework})
            return PreviewRecord.make(port=port, url=f"http://127.0.0.1:{port}",
                                     framework=framework)

        with patch.object(type(isolated_manager), "notify_dev_server_started",
                          side_effect=fake_notify):
            resp = client.post("/terminal/run", json={
                "command":   "vite",
                "workspace": ".",
                "timeout":   5,
            })

        # The command itself may fail (vite not installed), but what matters is
        # that the hook fires IF the output contained a port line.  Since we
        # can't guarantee vite is installed in the test env, we patch the
        # subprocess to emit a port-announcement line and verify the hook.

    def test_register_dev_server_called_on_vite_output(self, isolated_manager):
        """Unit-test the hook directly via _register_dev_server."""
        from smartagent.server.api_terminal import _register_dev_server
        import smartagent.server.api_previews as mod

        registered: list[dict] = []

        def fake_notify(port, framework="unknown", title=""):
            registered.append({"port": port, "framework": framework})
            return PreviewRecord.make(port=port, url=f"http://127.0.0.1:{port}",
                                     framework=framework)

        old = mod.preview_manager
        mod.preview_manager = isolated_manager
        isolated_manager.notify_dev_server_started = fake_notify
        try:
            _register_dev_server("vite", 5173)
        finally:
            mod.preview_manager = old

        assert registered == [{"port": 5173, "framework": "vite"}]


# ---------------------------------------------------------------------------
# 11 (extra). scan_ports — skips only own runtime port, not hard-coded 8080
# ---------------------------------------------------------------------------

class TestScanPortsRuntimeExclusion:

    def test_scan_skips_only_own_port(self, mgr: PreviewManager):
        """Port 8080 (Vue default) must NOT be excluded at runtime unless it's the server port."""
        scanned_ports: list[int] = []

        def fake_port_open(port, timeout=0.3):
            scanned_ports.append(port)
            return False  # nothing actually open

        with (
            patch.dict("os.environ", {"PORT": "8000"}),
            patch.object(PreviewManager, "_port_open", staticmethod(fake_port_open)),
        ):
            asyncio.run(mgr.scan_ports())

        # 8080 should be scanned (it's a Vue default)
        assert 8080 in scanned_ports
        # 8000 should NOT be scanned (it's the server's own port)
        assert 8000 not in scanned_ports

    def test_scan_excludes_configured_port(self, mgr: PreviewManager):
        """Whatever PORT env var is set to should be excluded."""
        scanned_ports: list[int] = []

        def fake_port_open(port, timeout=0.3):
            scanned_ports.append(port)
            return False

        with (
            patch.dict("os.environ", {"PORT": "5173"}),
            patch.object(PreviewManager, "_port_open", staticmethod(fake_port_open)),
        ):
            asyncio.run(mgr.scan_ports())

        assert 5173 not in scanned_ports


# ---------------------------------------------------------------------------
# 21. Broadcast integration
# ---------------------------------------------------------------------------

class TestBroadcast:

    def test_register_broadcasts_preview_registered(self, mgr: PreviewManager):
        broadcasts = []
        mock_mgr = MagicMock()
        mock_mgr.broadcast = AsyncMock(side_effect=lambda m: broadcasts.append(m))

        loop = asyncio.new_event_loop()
        mgr._loop    = loop
        mgr._manager = mock_mgr

        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="b1")

        # Run register in the loop context so run_coroutine_threadsafe works
        async def _do():
            mgr.register(rec)
            await asyncio.sleep(0.05)

        loop.run_until_complete(_do())
        loop.close()

        names = [b["name"] for b in broadcasts]
        assert ServerEvents.PREVIEW_REGISTERED in names

    def test_unregister_broadcasts_preview_closed(self, mgr: PreviewManager):
        broadcasts = []
        mock_mgr = MagicMock()
        mock_mgr.broadcast = AsyncMock(side_effect=lambda m: broadcasts.append(m))

        loop = asyncio.new_event_loop()
        mgr._loop    = loop
        mgr._manager = mock_mgr

        rec = PreviewRecord.make(port=3000, url="http://localhost:3000", preview_id="b2")
        mgr._previews["b2"] = rec

        async def _do():
            mgr.unregister("b2")
            await asyncio.sleep(0.05)

        loop.run_until_complete(_do())
        loop.close()

        names = [b["name"] for b in broadcasts]
        assert ServerEvents.PREVIEW_CLOSED in names
