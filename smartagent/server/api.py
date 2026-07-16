"""
MARK server — REST endpoints + WebSocket handler.

Endpoints
---------
GET  /health       — liveness probe
GET  /status       — current run state
GET  /workers      — active worker list
GET  /project      — workspace file listing (optional ?file=<path> for content)
POST /execute      — start a MARK software-engineering run
POST /cancel       — request cancellation of the current run
POST /approve      — approve a pending permission request
POST /deny         — deny a pending permission request
WS   /ws           — event stream (all MARK events as JSON)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse  # noqa: F401  (available for future use)

# Top-level imports make these patchable in tests.
try:
    from smartagent.brain.agent import SmartAgent
    from smartagent.brain.events import EventBus
    from smartagent.config.settings import Settings
    from smartagent.engineer.software_engineer import SoftwareEngineer
except ImportError:  # pragma: no cover
    SmartAgent = None       # type: ignore[assignment,misc]
    EventBus = None         # type: ignore[assignment,misc]
    Settings = None         # type: ignore[assignment,misc]
    SoftwareEngineer = None # type: ignore[assignment,misc]

from smartagent.server.events import ServerEvents, broadcaster, intercept_print
from smartagent.server.models import (
    ApproveRequest,
    DenyRequest,
    ExecuteRequest,
    HealthResponse,
    PendingPermissionInfo,
    PermissionsResponse,
    ProjectFile,
    ProjectResponse,
    StatusResponse,
    WorkerInfo,
)
from smartagent.server.permissions import permission_gate
from smartagent.server.websocket import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------

@dataclass
class RunState:
    """Tracks the current (or most recent) MARK build."""

    running: bool          = False
    goal: str              = ""
    workspace: str         = "."
    start_time: float      = 0.0
    cancel_requested: bool = False
    workers: list[dict]    = field(default_factory=list)
    _task: Any             = None       # asyncio.Task | None

    @property
    def elapsed(self) -> float:
        if not self.running or self.start_time == 0.0:
            return 0.0
        return time.monotonic() - self.start_time


_state = RunState()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe — always returns 200 when the server is up."""
    return HealthResponse()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    return StatusResponse(
        running=_state.running,
        goal=_state.goal,
        workspace=_state.workspace,
        elapsed=_state.elapsed,
        workers=[WorkerInfo(**w) for w in _state.workers],
        cancel_requested=_state.cancel_requested,
    )


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

@router.get("/workers")
async def workers() -> dict:
    return {"workers": _state.workers, "count": len(_state.workers)}


# ---------------------------------------------------------------------------
# Project / workspace
# ---------------------------------------------------------------------------

@router.get("/project", response_model=ProjectResponse)
async def project(file: str | None = None) -> ProjectResponse:
    """
    List files in the active workspace, or return the content of a single
    file when ``?file=<path>`` is provided.
    """
    workspace = os.path.abspath(_state.workspace)

    if file:
        # Reject absolute paths before attempting any join.
        if os.path.isabs(file):
            raise HTTPException(400, "Absolute paths are not allowed; use a relative path within the workspace")

        # Resolve both paths to canonical absolute paths (resolves symlinks,
        # eliminates ".." etc.) then verify strict containment.  This prevents
        # the sibling-prefix attack where startswith("/tmp/foo") would falsely
        # pass for "/tmp/foobar".  ValueError covers embedded null bytes and
        # other OS-level path rejections.
        try:
            resolved_workspace = Path(workspace).resolve()
            resolved_file = (resolved_workspace / file).resolve()
        except (ValueError, OSError) as exc:
            raise HTTPException(400, f"Invalid path: {exc}") from exc

        if not resolved_file.is_relative_to(resolved_workspace):
            raise HTTPException(400, "Path escapes the workspace boundary")

        if not resolved_file.is_file():
            raise HTTPException(404, f"File not found: {file}")

        try:
            content = resolved_file.read_text(errors="replace")
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

        rel = str(resolved_file.relative_to(resolved_workspace))
        return ProjectResponse(
            workspace=workspace,
            files=[ProjectFile(path=rel, name=resolved_file.name, size=len(content), content=content)],
        )

    # List all files (walk, skip hidden + __pycache__)
    file_list: list[ProjectFile] = []
    try:
        for dirpath, dirnames, filenames in os.walk(workspace):
            # Skip hidden dirs and __pycache__
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__" and d != "node_modules"]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                full = os.path.join(dirpath, fname)
                rel  = os.path.relpath(full, workspace)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                file_list.append(ProjectFile(path=rel, name=fname, size=size))
    except Exception:
        pass

    return ProjectResponse(workspace=workspace, files=file_list[:500])   # cap at 500 entries


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

@router.post("/execute")
async def execute(req: ExecuteRequest) -> dict:
    """
    Start a MARK software-engineering run.

    Only one run may be active at a time — returns HTTP 409 if another is
    already in progress.
    """
    if _state.running:
        raise HTTPException(409, "A build is already running.  Call /cancel first.")

    _state.running          = True
    _state.goal             = req.goal
    _state.workspace        = os.path.abspath(req.workspace)
    _state.start_time       = time.monotonic()
    _state.cancel_requested = False
    _state.workers          = []

    loop = asyncio.get_running_loop()

    # Broadcast run-started event
    await connection_manager.broadcast({
        "type":      "event",
        "name":      ServerEvents.RUN_STARTED,
        "payload":   {"goal": req.goal, "workspace": _state.workspace},
        "timestamp": _now_iso(),
    })

    async def _run() -> None:
        # Use module-level imports (patchable in tests).
        # Create a fresh EventBus so the broadcaster wires to the correct one
        event_bus = EventBus()
        broadcaster.install(event_bus, connection_manager, loop)

        try:
            # Build a minimal agent that uses our event bus
            settings = Settings(workspace_path=_state.workspace)
            agent    = SmartAgent(settings)
            # Replace the agent's own bus with our broadcaster-wired bus so
            # workers that publish via agent.events are also captured.
            agent.events = event_bus

            eng = SoftwareEngineer.with_agent(agent)

            def _build() -> Any:
                with intercept_print(event_bus):
                    return eng.build(
                        goal=req.goal,
                        project_dir=_state.workspace,
                        test_cmd=req.test_cmd,
                        max_iterations=req.max_iterations,
                        run_quality=False,
                    )

            if _state.cancel_requested:
                return

            result = await asyncio.to_thread(_build)

            ev_name    = ServerEvents.RUN_COMPLETED if result.success else ServerEvents.RUN_FAILED
            ev_payload: dict = {
                "goal":           result.goal,
                "success":        result.success,
                "elapsed":        result.total_elapsed,
                "files_created":  result.files_created,
                "files_modified": result.files_modified,
                "summary":        result.summary[:500] if result.summary else "",
            }

        except asyncio.CancelledError:
            ev_name    = ServerEvents.RUN_CANCELLED
            ev_payload = {"goal": req.goal}
            raise
        except Exception as exc:
            ev_name    = ServerEvents.RUN_FAILED
            ev_payload = {"goal": req.goal, "error": str(exc)}
            logger.exception("MARK build failed: %s", exc)
        finally:
            _state.running = False
            _state._task   = None
            broadcaster.uninstall(event_bus)

        await connection_manager.broadcast({
            "type":      "event",
            "name":      ev_name,
            "payload":   ev_payload,
            "timestamp": _now_iso(),
        })

    task = asyncio.create_task(_run(), name="mark-build")
    _state._task = task

    return {"status": "started", "goal": req.goal, "workspace": _state.workspace}


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@router.post("/cancel")
async def cancel() -> dict:
    """Request cancellation of the active build."""
    if not _state.running:
        return {"status": "no_active_run"}

    _state.cancel_requested = True

    # Best-effort: cancel the asyncio task that wraps to_thread.
    if _state._task is not None and not _state._task.done():
        _state._task.cancel()

    await connection_manager.broadcast({
        "type":      "event",
        "name":      ServerEvents.RUN_CANCELLED,
        "payload":   {"goal": _state.goal},
        "timestamp": _now_iso(),
    })

    return {"status": "cancel_requested"}


# ---------------------------------------------------------------------------
# Approve / Deny
# ---------------------------------------------------------------------------

@router.post("/approve")
async def approve(req: ApproveRequest) -> dict:
    """Approve a pending permission request."""
    ok = permission_gate.approve(req.request_id, always=req.always)
    if not ok:
        raise HTTPException(404, "No matching pending permission request found.")

    await connection_manager.broadcast({
        "type":      "event",
        "name":      ServerEvents.PERMISSION_GRANTED,
        "payload":   {"request_id": req.request_id},
        "timestamp": _now_iso(),
    })
    return {"status": "approved", "request_id": req.request_id}


@router.post("/deny")
async def deny(req: DenyRequest) -> dict:
    """Deny a pending permission request."""
    ok = permission_gate.deny(req.request_id, reason=req.reason)
    if not ok:
        raise HTTPException(404, "No matching pending permission request found.")

    await connection_manager.broadcast({
        "type":      "event",
        "name":      ServerEvents.PERMISSION_DENIED,
        "payload":   {"request_id": req.request_id, "reason": req.reason},
        "timestamp": _now_iso(),
    })
    return {"status": "denied", "request_id": req.request_id}


# ---------------------------------------------------------------------------
# Permissions listing
# ---------------------------------------------------------------------------

@router.get("/permissions", response_model=PermissionsResponse)
async def list_permissions() -> PermissionsResponse:
    """Return all pending permission requests."""
    return PermissionsResponse(
        pending=[
            PendingPermissionInfo(
                request_id=p.request_id,
                operation=p.operation,
                path=p.path,
                diff=p.diff,
            )
            for p in permission_gate.list_pending()
        ]
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """
    Stream every MARK event to the connecting client as JSON.

    Clients may send any text frame (e.g. a ping) — we ignore the content
    and just keep the connection alive.
    """
    await connection_manager.connect(ws)

    # Send the current status immediately on connect so the client can
    # render the right initial state without waiting for the next event.
    await connection_manager.send_to(ws, {
        "type":      "event",
        "name":      ServerEvents.STATUS_CHANGED,
        "payload":   {
            "running":   _state.running,
            "goal":      _state.goal,
            "workspace": _state.workspace,
            "elapsed":   _state.elapsed,
        },
        "timestamp": _now_iso(),
    })

    try:
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send a keepalive ping
                await connection_manager.send_to(ws, {"type": "ping"})
    except (WebSocketDisconnect, Exception):
        connection_manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
