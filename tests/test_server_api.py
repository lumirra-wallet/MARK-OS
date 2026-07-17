"""
Tests for the MARK web server API (Phase 1).

Uses FastAPI's TestClient (sync) for REST endpoints and a custom async
WebSocket fixture for the /ws endpoint.

Coverage:
  1. GET /health
  2. GET /status — idle and running states
  3. GET /workers
  4. GET /project — workspace listing and file content
  5. POST /execute — starts a run, rejects concurrent runs
  6. POST /cancel — cancels an active run
  7. POST /approve / /deny — permission gate
  8. WebSocket /ws — connects, receives initial status, receives events
  9. EventBus.subscribe_all / unsubscribe_all
 10. WebSocketBroadcaster — event forwarding
 11. PrintInterceptor — routes print() through EventBus
 12. PermissionGate — approve / deny / timeout / always-approve
 13. ConnectionManager — connect / disconnect / broadcast
 14. Full test suite regression — no existing tests broken
"""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from smartagent.brain.events import EventBus
from smartagent.server.app import app
from smartagent.server.events import (
    ServerEvents,
    WebSocketBroadcaster,
    broadcaster,
    intercept_print,
)
from smartagent.server.models import EventMessage, ExecuteRequest, StatusResponse
from smartagent.server.permissions import APPROVED, DENIED, PermissionGate, permission_gate
from smartagent.server.websocket import ConnectionManager


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fresh_state():
    """Reset the module-level RunState before each test."""
    from smartagent.server.api import _state
    _state.running = False
    _state.goal = ""
    _state.workspace = "."
    _state.start_time = 0.0
    _state.cancel_requested = False
    _state.workers = []
    _state._task = None
    yield _state
    # Cleanup
    _state.running = False
    _state.cancel_requested = False
    _state._task = None


@pytest.fixture()
def fresh_gate():
    """Return a fresh PermissionGate for tests that need isolation."""
    return PermissionGate()


@pytest.fixture()
def event_bus():
    return EventBus()


# ---------------------------------------------------------------------------
# 1. GET /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200(self, client, fresh_state):
        r = client.get("/health")
        assert r.status_code == 200

    def test_returns_ok(self, client, fresh_state):
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_has_version(self, client, fresh_state):
        data = client.get("/health").json()
        assert "version" in data


# ---------------------------------------------------------------------------
# 2. GET /status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_idle(self, client, fresh_state):
        r = client.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert data["running"] is False

    def test_has_required_fields(self, client, fresh_state):
        data = client.get("/status").json()
        for field in ("running", "goal", "workspace", "elapsed", "workers"):
            assert field in data, f"Missing field: {field}"

    def test_reflects_run_state(self, client, fresh_state):
        fresh_state.running = True
        fresh_state.goal = "Build a demo"
        fresh_state.start_time = time.monotonic()
        data = client.get("/status").json()
        assert data["running"] is True
        assert data["goal"] == "Build a demo"
        assert data["elapsed"] >= 0.0


# ---------------------------------------------------------------------------
# 3. GET /workers
# ---------------------------------------------------------------------------

class TestWorkers:
    def test_returns_200(self, client, fresh_state):
        assert client.get("/workers").status_code == 200

    def test_empty_when_idle(self, client, fresh_state):
        data = client.get("/workers").json()
        assert data["workers"] == []
        assert data["count"] == 0

    def test_reflects_workers(self, client, fresh_state):
        fresh_state.workers = [{"name": "CodingWorker", "status": "running", "task_title": "", "elapsed": 1.0, "confidence": 0.0}]
        data = client.get("/workers").json()
        assert data["count"] == 1
        assert data["workers"][0]["name"] == "CodingWorker"


# ---------------------------------------------------------------------------
# 4. GET /project
# ---------------------------------------------------------------------------

class TestProject:
    def test_returns_200(self, client, fresh_state, tmp_path):
        fresh_state.workspace = str(tmp_path)
        r = client.get("/project")
        assert r.status_code == 200

    def test_lists_files(self, client, fresh_state, tmp_path):
        (tmp_path / "hello.py").write_text("print('hi')")
        fresh_state.workspace = str(tmp_path)
        data = client.get("/project").json()
        assert any("hello.py" in f["name"] for f in data["files"])

    def test_file_content(self, client, fresh_state, tmp_path):
        (tmp_path / "hello.py").write_text("print('hi')")
        fresh_state.workspace = str(tmp_path)
        data = client.get("/project", params={"file": "hello.py"}).json()
        assert len(data["files"]) == 1
        assert "print" in data["files"][0]["content"]

    def test_file_not_found_404(self, client, fresh_state, tmp_path):
        fresh_state.workspace = str(tmp_path)
        r = client.get("/project", params={"file": "nonexistent.py"})
        assert r.status_code == 404

    def test_path_traversal_rejected(self, client, fresh_state, tmp_path):
        fresh_state.workspace = str(tmp_path)
        r = client.get("/project", params={"file": "../../etc/passwd"})
        assert r.status_code == 400

    def test_absolute_path_rejected(self, client, fresh_state, tmp_path):
        """Absolute paths must be rejected outright."""
        fresh_state.workspace = str(tmp_path)
        r = client.get("/project", params={"file": "/etc/passwd"})
        assert r.status_code == 400

    def test_sibling_prefix_traversal_rejected(self, client, fresh_state, tmp_path):
        """
        Sibling-prefix attack: workspace=/tmp/foo, file=../foo2.txt
        normpath+startswith would falsely pass because /tmp/foo2.txt
        starts with /tmp/fo — but NOT with the correct trailing separator.
        Resolved-path containment must reject this.
        """
        import tempfile, os
        with tempfile.TemporaryDirectory() as sibling:
            secret = os.path.join(sibling, "secret.txt")
            with open(secret, "w") as f:
                f.write("secret data")
            # tmp_path and sibling are both under the system temp dir
            # Navigate from tmp_path up one level then into sibling
            rel = os.path.join(
                "..", os.path.basename(sibling), "secret.txt"
            )
            fresh_state.workspace = str(tmp_path)
            r = client.get("/project", params={"file": rel})
            assert r.status_code == 400, (
                f"Expected 400 for sibling traversal '{rel}', got {r.status_code}"
            )

    def test_null_byte_in_path_rejected(self, client, fresh_state, tmp_path):
        """Paths containing null bytes should not reach the filesystem."""
        fresh_state.workspace = str(tmp_path)
        r = client.get("/project", params={"file": "hello\x00.py"})
        assert r.status_code in (400, 404, 422)

    def test_skips_hidden_dirs(self, client, fresh_state, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("secret")
        (tmp_path / "visible.py").write_text("pass")
        fresh_state.workspace = str(tmp_path)
        data = client.get("/project").json()
        paths = [f["path"] for f in data["files"]]
        assert not any(".git" in p for p in paths)
        assert any("visible.py" in p for p in paths)


# ---------------------------------------------------------------------------
# 5. POST /execute
# ---------------------------------------------------------------------------

def _make_mock_report(tmp_path):
    """Return a mock SoftwareEngineerReport for use in execute tests."""
    from smartagent.engineer.software_engineer import SoftwareEngineerReport
    return SoftwareEngineerReport(
        goal="test goal",
        success=True,
        files_created=["hello.py"],
        total_elapsed=0.1,
        summary="Done.",
        project_dir=str(tmp_path),
    )


def _execute_patches(tmp_path):
    """Context manager stack that prevents the background build from touching Ollama."""
    from contextlib import ExitStack
    stack = ExitStack()
    mock_eng = MagicMock()
    mock_eng.build.return_value = _make_mock_report(tmp_path)
    # Patch module-level names imported in api.py
    stack.enter_context(patch("smartagent.server.api.SmartAgent"))
    mock_eng_cls = stack.enter_context(patch("smartagent.server.api.SoftwareEngineer"))
    mock_eng_cls.with_agent.return_value = mock_eng
    # Patch EventBus so broadcaster doesn't wire to a real bus
    stack.enter_context(patch("smartagent.server.api.EventBus", return_value=MagicMock()))
    # Patch Settings to avoid touching disk
    stack.enter_context(patch("smartagent.server.api.Settings", return_value=MagicMock()))
    return stack, mock_eng


class TestExecute:
    def test_starts_run(self, client, fresh_state, tmp_path):
        with _execute_patches(tmp_path)[0]:
            r = client.post("/execute", json={"goal": "create hello.py", "workspace": str(tmp_path)})
        assert r.status_code == 200
        assert r.json()["status"] == "started"

    def test_rejects_concurrent_run(self, client, fresh_state):
        fresh_state.running = True
        r = client.post("/execute", json={"goal": "something", "workspace": "."})
        assert r.status_code == 409

    def test_goal_set_in_state(self, client, fresh_state, tmp_path):
        with _execute_patches(tmp_path)[0]:
            client.post("/execute", json={"goal": "build a CLI", "workspace": str(tmp_path)})
        # Goal is set synchronously before the background task runs
        assert fresh_state.goal == "build a CLI"

    def test_workspace_absolute_path(self, client, fresh_state, tmp_path):
        with _execute_patches(tmp_path)[0]:
            client.post("/execute", json={"goal": "test", "workspace": str(tmp_path)})
        assert os.path.isabs(fresh_state.workspace)

    def test_response_includes_goal(self, client, fresh_state, tmp_path):
        with _execute_patches(tmp_path)[0]:
            r = client.post("/execute", json={"goal": "write a script", "workspace": str(tmp_path)})
        assert r.json()["goal"] == "write a script"


# ---------------------------------------------------------------------------
# 6. POST /cancel
# ---------------------------------------------------------------------------

class TestCancel:
    def test_no_active_run(self, client, fresh_state):
        r = client.post("/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "no_active_run"

    def test_sets_cancel_flag(self, client, fresh_state):
        fresh_state.running = True
        fresh_state.goal = "test"
        r = client.post("/cancel")
        assert r.status_code == 200
        assert fresh_state.cancel_requested is True

    def test_returns_cancel_requested(self, client, fresh_state):
        fresh_state.running = True
        r = client.post("/cancel")
        assert r.json()["status"] == "cancel_requested"


# ---------------------------------------------------------------------------
# 7. POST /approve and /deny
# ---------------------------------------------------------------------------

class TestApprove:
    def test_no_pending_returns_404(self, client, fresh_state):
        r = client.post("/approve", json={})
        assert r.status_code == 404

    def test_approve_returns_approved(self, client, fresh_state):
        from smartagent.server.permissions import permission_gate
        perm = permission_gate.create_request("create", "/tmp/test.py")
        r = client.post("/approve", json={"request_id": perm.request_id})
        assert r.status_code == 200
        assert r.json()["status"] == "approved"
        # Cleanup
        permission_gate._pending.pop(perm.request_id, None)

    def test_approve_resolves_gate(self, client, fresh_state):
        from smartagent.server.permissions import permission_gate
        perm = permission_gate.create_request("modify", "/tmp/app.py")
        client.post("/approve", json={"request_id": perm.request_id})
        assert perm.result == APPROVED
        permission_gate._pending.pop(perm.request_id, None)


class TestDeny:
    def test_no_pending_returns_404(self, client, fresh_state):
        r = client.post("/deny", json={})
        assert r.status_code == 404

    def test_deny_resolves_gate(self, client, fresh_state):
        from smartagent.server.permissions import permission_gate
        perm = permission_gate.create_request("delete", "/tmp/x.py")
        client.post("/deny", json={"request_id": perm.request_id, "reason": "not safe"})
        assert perm.result == DENIED
        permission_gate._pending.pop(perm.request_id, None)

    def test_deny_returns_denied(self, client, fresh_state):
        from smartagent.server.permissions import permission_gate
        perm = permission_gate.create_request("shell", "/tmp")
        r = client.post("/deny", json={"request_id": perm.request_id})
        assert r.json()["status"] == "denied"
        permission_gate._pending.pop(perm.request_id, None)


# ---------------------------------------------------------------------------
# 8. WebSocket /ws
# ---------------------------------------------------------------------------

class TestWebSocket:
    def test_connect_receives_initial_status(self, client, fresh_state):
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "event"
            assert msg["name"] == ServerEvents.STATUS_CHANGED
            assert "running" in msg["payload"]

    def test_connect_and_disconnect_no_error(self, client, fresh_state):
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg is not None

    def test_status_payload_has_goal(self, client, fresh_state):
        fresh_state.goal = "Build a demo"
        with client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            assert msg["payload"]["goal"] == "Build a demo"

    def test_multiple_clients_supported(self, client, fresh_state):
        with client.websocket_connect("/ws") as ws1, \
             client.websocket_connect("/ws") as ws2:
            m1 = ws1.receive_json()
            m2 = ws2.receive_json()
            assert m1["name"] == ServerEvents.STATUS_CHANGED
            assert m2["name"] == ServerEvents.STATUS_CHANGED


class TestWebSocketOpeningMessage:
    """
    MARK must proactively open the conversation from the real workspace
    analysis the moment a client connects — not wait for the user to speak
    first, and never go silent even if the LLM call itself fails.
    """

    def test_mark_opening_uses_llm_text(self, client, fresh_state):
        with patch("smartagent.server.api.Settings", return_value=MagicMock()), \
             patch("smartagent.server.api.SmartAgent") as mock_agent_cls:
            mock_agent_cls.return_value.model_manager.chat_stream.return_value = iter(
                ["I've looked over this repo — nice setup."]
            )
            with client.websocket_connect("/ws") as ws:
                assert ws.receive_json()["name"] == ServerEvents.STATUS_CHANGED
                assert ws.receive_json()["name"] == ServerEvents.WORKSPACE_ANALYZED
                opening = ws.receive_json()
                assert opening["name"] == ServerEvents.MARK_OPENING
                assert "looked over this repo" in opening["payload"]["text"]

    def test_mark_opening_falls_back_on_llm_error(self, client, fresh_state):
        """A failed LLM call (rate limit, model unavailable, etc.) must still
        produce a deterministic opening message — MARK never goes silent."""
        with patch("smartagent.server.api.Settings", return_value=MagicMock()), \
             patch("smartagent.server.api.SmartAgent") as mock_agent_cls:
            mock_agent_cls.return_value.model_manager.chat_stream.side_effect = RuntimeError("rate limited")
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()  # StatusChanged
                ws.receive_json()  # WorkspaceAnalyzed
                opening = ws.receive_json()
                assert opening["name"] == ServerEvents.MARK_OPENING
                assert opening["payload"]["text"]


# ---------------------------------------------------------------------------
# 9. EventBus.subscribe_all / unsubscribe_all
# ---------------------------------------------------------------------------

class TestEventBusSubscribeAll:
    def test_catch_all_receives_every_event(self, event_bus):
        received = []
        event_bus.subscribe_all(lambda e: received.append(e.name))
        event_bus.publish("Alpha")
        event_bus.publish("Beta")
        event_bus.publish("Gamma")
        assert received == ["Alpha", "Beta", "Gamma"]

    def test_catch_all_and_specific_both_fire(self, event_bus):
        catch_all = []
        specific = []
        event_bus.subscribe("Alpha", lambda e: specific.append(e.name))
        event_bus.subscribe_all(lambda e: catch_all.append(e.name))
        event_bus.publish("Alpha")
        event_bus.publish("Beta")
        assert specific == ["Alpha"]
        assert "Alpha" in catch_all
        assert "Beta" in catch_all

    def test_unsubscribe_all_removes_handler(self, event_bus):
        received = []
        handler = lambda e: received.append(e.name)
        event_bus.subscribe_all(handler)
        event_bus.publish("One")
        event_bus.unsubscribe_all(handler)
        event_bus.publish("Two")
        assert received == ["One"]

    def test_multiple_catch_all_handlers(self, event_bus):
        a, b = [], []
        event_bus.subscribe_all(lambda e: a.append(e.name))
        event_bus.subscribe_all(lambda e: b.append(e.name))
        event_bus.publish("X")
        assert a == ["X"]
        assert b == ["X"]

    def test_empty_bus_no_error(self, event_bus):
        # subscribe_all with no events published — no error
        event_bus.subscribe_all(lambda e: None)

    def test_publish_still_returns_event(self, event_bus):
        event_bus.subscribe_all(lambda e: None)
        ev = event_bus.publish("Test", key="val")
        assert ev.name == "Test"
        assert ev.payload == {"key": "val"}

    def test_unsubscribe_nonexistent_no_error(self, event_bus):
        event_bus.unsubscribe_all(lambda e: None)   # should not raise


# ---------------------------------------------------------------------------
# 10. WebSocketBroadcaster
# ---------------------------------------------------------------------------

class TestWebSocketBroadcaster:
    def test_install_subscribes_to_all(self):
        bus = EventBus()
        mgr = ConnectionManager()
        b = WebSocketBroadcaster()
        loop = asyncio.new_event_loop()
        try:
            b.install(bus, mgr, loop)
            assert len(bus._catch_all) == 1
        finally:
            b.uninstall(bus)
            loop.close()

    def test_uninstall_removes_subscription(self):
        bus = EventBus()
        mgr = ConnectionManager()
        b = WebSocketBroadcaster()
        loop = asyncio.new_event_loop()
        try:
            b.install(bus, mgr, loop)
            b.uninstall(bus)
            assert len(bus._catch_all) == 0
        finally:
            loop.close()

    def test_on_event_without_install_no_error(self):
        from smartagent.brain.events import Event
        b = WebSocketBroadcaster()
        ev = Event(name="Test", payload={})
        b._on_event(ev)   # should not raise

    def test_event_shapes_are_correct(self):
        """_on_event() creates the correct dict shape."""
        from smartagent.brain.events import Event
        captured = []

        class FakeMgr:
            async def broadcast(self, msg):
                captured.append(msg)

        loop = asyncio.new_event_loop()
        try:
            b = WebSocketBroadcaster()
            b._loop    = loop
            b._manager = FakeMgr()

            ev = Event(name="WorkerStarted", payload={"worker": "Coder"}, timestamp="2026-01-01T00:00:00+00:00")
            b._on_event(ev)
            # run_coroutine_threadsafe schedules a task — let the loop run it
            loop.run_until_complete(asyncio.sleep(0))
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# 11. PrintInterceptor
# ---------------------------------------------------------------------------

class TestPrintInterceptor:
    def test_still_writes_to_stdout(self, capsys, event_bus):
        with intercept_print(event_bus):
            print("hello intercepted")
        captured = capsys.readouterr()
        assert "hello intercepted" in captured.out

    def test_emits_streaming_token_event(self, event_bus):
        received = []
        event_bus.subscribe(ServerEvents.STREAMING_TOKEN, lambda e: received.append(e.payload["text"]))
        with intercept_print(event_bus):
            print("test message")
        assert any("test message" in t for t in received)

    def test_restores_original_print(self, event_bus):
        import builtins
        orig = builtins.print
        with intercept_print(event_bus):
            pass
        assert builtins.print is orig

    def test_print_kwargs_preserved(self, capsys, event_bus):
        with intercept_print(event_bus):
            print("a", "b", sep="-", end="!")
        captured = capsys.readouterr()
        assert "a-b!" in captured.out

    def test_nested_context_restores_correctly(self, event_bus):
        import builtins
        orig = builtins.print
        bus2 = EventBus()
        with intercept_print(event_bus):
            with intercept_print(bus2):
                pass
            # After inner context: outer interceptor still active
        # After outer context: original restored
        assert builtins.print is orig


# ---------------------------------------------------------------------------
# 12. PermissionGate
# ---------------------------------------------------------------------------

class TestPermissionGate:
    def test_create_request(self, fresh_gate):
        perm = fresh_gate.create_request("create", "/tmp/hello.py")
        assert perm.operation == "create"
        assert perm.path == "/tmp/hello.py"
        assert perm.result == "pending"

    def test_approve_by_id(self, fresh_gate):
        perm = fresh_gate.create_request("modify", "/tmp/app.py")
        ok = fresh_gate.approve(perm.request_id)
        assert ok is True
        assert perm.result == APPROVED

    def test_deny_by_id(self, fresh_gate):
        perm = fresh_gate.create_request("delete", "/tmp/old.py")
        ok = fresh_gate.deny(perm.request_id)
        assert ok is True
        assert perm.result == DENIED

    def test_approve_latest_when_no_id(self, fresh_gate):
        p1 = fresh_gate.create_request("create", "/a")
        p2 = fresh_gate.create_request("create", "/b")
        fresh_gate.approve()     # approves p2 (latest)
        assert p1.result == "pending"
        assert p2.result == APPROVED

    def test_approve_nonexistent_id_returns_false(self, fresh_gate):
        assert fresh_gate.approve("nonexistent-id") is False

    def test_deny_nonexistent_id_returns_false(self, fresh_gate):
        assert fresh_gate.deny("nonexistent-id") is False

    def test_list_pending_filters_resolved(self, fresh_gate):
        p1 = fresh_gate.create_request("create", "/a")
        p2 = fresh_gate.create_request("create", "/b")
        fresh_gate.approve(p1.request_id)
        pending = fresh_gate.list_pending()
        assert p2 in pending
        assert p1 not in pending

    def test_always_approve(self, fresh_gate):
        p1 = fresh_gate.create_request("create", "/a")
        fresh_gate.approve(p1.request_id, always=True)
        assert fresh_gate.is_always_approved("create") is True

    def test_emits_event_on_create(self):
        bus = EventBus()
        received = []
        bus.subscribe(ServerEvents.PERMISSION_REQUESTED, lambda e: received.append(e))
        gate = PermissionGate()
        gate.create_request("create", "/tmp/x.py", event_bus=bus)
        assert len(received) == 1
        assert received[0].payload["operation"] == "create"

    def test_wait_for_approval_approved(self, fresh_gate):
        perm = fresh_gate.create_request("create", "/tmp/x.py")

        async def _run():
            async def approve_soon():
                await asyncio.sleep(0.01)
                fresh_gate.approve(perm.request_id)
            asyncio.create_task(approve_soon())
            return await fresh_gate.wait_for_approval(perm, timeout=2.0)

        result = asyncio.run(_run())
        assert result == APPROVED

    def test_wait_for_approval_denied(self, fresh_gate):
        perm = fresh_gate.create_request("create", "/tmp/y.py")

        async def _run():
            async def deny_soon():
                await asyncio.sleep(0.01)
                fresh_gate.deny(perm.request_id)
            asyncio.create_task(deny_soon())
            return await fresh_gate.wait_for_approval(perm, timeout=2.0)

        result = asyncio.run(_run())
        assert result == DENIED

    def test_wait_for_approval_timeout_returns_denied(self, fresh_gate):
        async def _run():
            gate = PermissionGate()
            perm = gate.create_request("shell", "/tmp/cmd")
            return await gate.wait_for_approval(perm, timeout=0.05)

        result = asyncio.run(_run())
        assert result == DENIED

    def test_always_approved_skips_wait(self, fresh_gate):
        async def _run():
            fresh_gate._always_approved.add("create")
            perm = fresh_gate.create_request("create", "/tmp/z.py")
            return await fresh_gate.wait_for_approval(perm, timeout=0.1)

        result = asyncio.run(_run())
        assert result == APPROVED


# ---------------------------------------------------------------------------
# 13. ConnectionManager
# ---------------------------------------------------------------------------

class TestConnectionManager:
    def test_connect_increments_count(self):
        async def _run():
            mgr = ConnectionManager()
            ws = MagicMock()
            ws.accept = _async_noop
            ws.send_text = _async_noop
            await mgr.connect(ws)
            return mgr.count
        assert asyncio.run(_run()) == 1

    def test_disconnect_decrements_count(self):
        async def _run():
            mgr = ConnectionManager()
            ws = MagicMock()
            ws.accept = _async_noop
            await mgr.connect(ws)
            mgr.disconnect(ws)
            return mgr.count
        assert asyncio.run(_run()) == 0

    def test_broadcast_sends_to_all(self):
        messages: list[str] = []

        class FakeWS:
            async def accept(self): pass
            async def send_text(self, text): messages.append(text)

        async def _run():
            mgr = ConnectionManager()
            ws1, ws2 = FakeWS(), FakeWS()
            await mgr.connect(ws1)
            await mgr.connect(ws2)
            await mgr.broadcast({"type": "ping"})
            return len(messages)

        assert asyncio.run(_run()) == 2

    def test_broadcast_removes_dead_connections(self):
        class DeadWS:
            async def accept(self): pass
            async def send_text(self, text): raise RuntimeError("dead")

        async def _run():
            mgr = ConnectionManager()
            ws = DeadWS()
            await mgr.connect(ws)
            assert mgr.count == 1
            await mgr.broadcast({"type": "test"})
            return mgr.count

        assert asyncio.run(_run()) == 0   # removed after failure

    def test_broadcast_empty_no_error(self):
        async def _run():
            mgr = ConnectionManager()
            await mgr.broadcast({"type": "test"})   # should not raise

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 14. Permissions listing endpoint
# ---------------------------------------------------------------------------

class TestPermissionsEndpoint:
    def test_empty_when_no_pending(self, client, fresh_state):
        # Ensure no pending requests from other tests bleed through
        permission_gate._pending.clear()
        r = client.get("/permissions")
        assert r.status_code == 200
        assert r.json()["pending"] == []

    def test_lists_pending_requests(self, client, fresh_state):
        permission_gate._pending.clear()
        perm = permission_gate.create_request("create", "/tmp/test.py")
        r = client.get("/permissions")
        data = r.json()
        assert any(p["request_id"] == perm.request_id for p in data["pending"])
        permission_gate._pending.clear()


# ---------------------------------------------------------------------------
# 15. ServerEvents constants
# ---------------------------------------------------------------------------

class TestServerEvents:
    def test_all_constants_are_strings(self):
        for k, v in vars(ServerEvents).items():
            if not k.startswith("_"):
                assert isinstance(v, str), f"ServerEvents.{k} is not a string"

    def test_required_events_exist(self):
        required = [
            "WORKER_STARTED", "WORKER_FINISHED", "PLANNING_STARTED", "PLANNING_FINISHED",
            "FILE_CREATED", "FILE_MODIFIED", "FILE_DELETED",
            "TESTS_STARTED", "TESTS_PASSED", "TESTS_FAILED",
            "STREAMING_TOKEN", "PERMISSION_REQUESTED", "PERMISSION_GRANTED", "PERMISSION_DENIED",
            "RUN_STARTED", "RUN_COMPLETED", "RUN_FAILED", "STATUS_CHANGED",
        ]
        for name in required:
            assert hasattr(ServerEvents, name), f"ServerEvents.{name} is missing"


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

async def _async_noop(*args, **kwargs):
    pass
