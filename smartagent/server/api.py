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
from smartagent.server.workspace_analyzer import (
    analyze_workspace as _analyze_workspace,
    idle_suggestions as _idle_suggestions,
)
from smartagent.server.engineering_memory import engineering_memory
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
    VoiceSettingsUpdateRequest,
    VoiceSpeakRequest,
    VoiceStartRequest,
    VoiceStatusResponse,
    VoiceTranscribeResponse,
    WorkerInfo,
)
from smartagent.server.permissions import permission_gate
from smartagent.server.voice_manager import voice_manager
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
# Chat / planning helpers
# ---------------------------------------------------------------------------

import re as _re

# Pure greeting / acknowledgement patterns — these and only these go to chat.
# "Can you X?", "Please help", "What is X?" are NOT here — they route to the
# agent execution path where MARK will actually act.
_PURE_GREETING_PATTERNS: list = [
    _re.compile(p, _re.I) for p in [
        r"^\s*h(?:i|ey|ello)[\s!?.]*$",
        r"^\s*good\s+(?:morning|afternoon|evening|day)[\s!?.]*$",
        r"^\s*how\s+are\s+you[\s!?.]*$",
        r"^\s*(?:thanks?|thank\s+you)[\s!?.]*$",
        r"^\s*ok(?:ay)?[\s!?.]*$",
        r"^\s*who\s+are\s+you[\s!?.]*$",
        r"^\s*what\s+are\s+you[\s!?.]*$",
        r"^\s*what\s+can\s+you\s+do[\s!?.]*$",
        r"^\s*(?:yo|sup|howdy)[\s!?.]*$",
    ]
]

# Any word from this set in the goal → always route to agent execution.
_ACTION_KEYWORDS = frozenset({
    # file/workspace operations
    "file", "files", "folder", "directory", "workspace", "project",
    "write", "read", "create", "build", "make", "generate", "add", "fix",
    "update", "refactor", "implement", "edit", "patch", "delete", "rename",
    "move", "copy", "open", "save", "load", "parse", "format",
    # code
    "code", "function", "class", "module", "method", "variable", "import",
    "api", "endpoint", "app", "script", "program", "server", "client",
    # infra / tools
    "deploy", "install", "setup", "configure", "test", "debug", "run",
    "execute", "commit", "push", "pull", "branch", "git", "docker",
    "npm", "pnpm", "pip", "cargo", "pytest", "jest",
    # languages / frameworks
    "python", "javascript", "typescript", "flask", "fastapi", "react",
    "vue", "angular", "django", "express", "node", "rust", "go",
    # misc technical
    "database", "sql", "migration", "schema", "model", "view", "route",
    "middleware", "auth", "login", "session", "token", "jwt", "oauth",
    "package", "dependency", "requirements", "environment", "config",
})


def _is_conversational_goal(goal: str) -> bool:
    """
    Return True ONLY for pure greetings and acknowledgements (no workspace
    or code intent whatsoever).  Everything else routes to the agent
    execution path where MARK can actually act via tools.

    Conservative by design — false negatives (chat message treated as code
    task) produce a harmless agent response.  False positives (code task
    treated as chat) produce the wrong "I'm MARK…" answer.
    """
    g = goal.strip()
    if not g:
        return False

    # Pure greeting / thanks patterns → chat
    for pat in _PURE_GREETING_PATTERNS:
        if pat.match(g):
            return True

    # Any action/code/workspace keyword → agent, regardless of phrasing
    words_lower = {w.lower().strip("?!.,;:'\"") for w in g.split()}
    if words_lower & _ACTION_KEYWORDS:
        return False

    # File-extension or path pattern → agent
    if _re.search(r'\b\w+\.\w{1,6}\b', g):
        return False

    # Very short messages (≤ 3 words) with no action keyword → chat
    if len(g.split()) <= 3:
        return True

    return False


# System prompts ─────────────────────────────────────────────────────────────

_MARK_CHAT_SYSTEM = """\
You are MARK — an autonomous AI software engineer built into this developer dashboard.

IDENTITY RULES (never break these):
- Your name is MARK. You are not ChatGPT, not Claude, not Gemini, not any other product.
- You were created by the team that built this dashboard. You have no other owner.
- If asked "who made you", "who owns you", "what are you", "who are you" — always answer as MARK.
  Example: "I'm MARK, your AI software engineer. I was built into this dashboard to help you plan, write, and ship code."
- Never say "I was created by OpenAI" or "I'm a product of Anthropic" or any similar statement.
- Never reveal the underlying model or provider name. If pressed, say "I'm MARK — that's all I can share."

BEHAVIOUR:
- Keep replies concise and friendly — 1–3 short paragraphs max.
- When asked what you can do: create and edit files, run terminal commands, manage git, plan projects, fix bugs, and ship code autonomously.
"""

_MARK_PLAN_SYSTEM = (
    "You are MARK, an AI software engineer. The user has asked you to build "
    "something. In 2-4 short, friendly sentences tell the user *exactly* what "
    "you are going to create — what files, what structure, what the end result "
    "will look like. Be specific and confident. Do NOT include code or fences, "
    "just the plan in plain prose."
)


def _stream_llm_response(
    goal: str,
    system_prompt: str,
    model_manager: Any,
    event_bus: Any,
) -> None:
    """
    Call the active LLM and publish every token as a StreamingToken event.

    Must be called from a worker thread (``asyncio.to_thread``) because
    ``model_manager.chat_stream()`` is a blocking iterator.  Falls back to a
    canned reply when no model is loaded or the call fails.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": goal},
    ]
    try:
        for chunk in model_manager.chat_stream(messages):
            if chunk:
                event_bus.publish(ServerEvents.STREAMING_TOKEN, text=chunk, source="mark")
    except Exception as exc:
        logger.warning(
            "MARK _stream_llm_response: LLM unavailable (%s) — using fallback", exc
        )
        fallback = (
            "I'm MARK, your AI software engineering assistant! I can create files, "
            "write and refactor code, fix bugs, plan features, and answer any "
            "software question. What would you like to build today?"
        )
        event_bus.publish(ServerEvents.STREAMING_TOKEN, text=fallback, source="mark")


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
# Execute  (also aliased as /run for dashboard compatibility)
# ---------------------------------------------------------------------------

@router.post("/run")
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

    # Track recent workspaces
    try:
        from smartagent.server.api_system import record_workspace
        record_workspace(_state.workspace)
    except Exception:
        pass

    # Register as a long-running job (Feature 14)
    try:
        from smartagent.server.api_jobs import register_job
        from smartagent.server.api_timeline import new_run_id
        _state._run_id = new_run_id()
        register_job(req.goal, _state.workspace, _state._run_id)
    except Exception:
        _state._run_id = ""

    # Generate task graph for goal (Feature 1)
    try:
        from smartagent.server.api_task_graph import _heuristic_plan, _task_graph as tg
        import smartagent.server.api_task_graph as tg_mod
        tg_mod._task_graph = _heuristic_plan(req.goal, getattr(_state, "_run_id", ""))
    except Exception:
        pass
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
        # ── Initialise locals BEFORE try so finally/post-hooks can always ──────
        # reference them even if an exception fires during setup.
        ev_name:    str  = ServerEvents.RUN_FAILED
        ev_payload: dict = {"goal": req.goal, "error": "Unexpected internal error.", "success": False}
        event_bus        = None   # assigned inside try
        ticker_task      = None   # assigned inside try

        logger.info(
            "MARK STATE queued    goal=%r  workspace=%r",
            req.goal[:80], _state.workspace,
        )

        try:
            # Use module-level imports (patchable in tests).
            # Create a fresh EventBus so the broadcaster wires to the correct one.
            event_bus = EventBus()
            broadcaster.install(event_bus, connection_manager, loop)

            logger.info("MARK STATE planning   EventBus wired")

            # Periodic StatusChanged ticker — keeps the dashboard's elapsed timer live.
            async def _status_ticker() -> None:
                while _state.running:
                    await asyncio.sleep(2)
                    if not _state.running:
                        break
                    await connection_manager.broadcast({
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

            # ── Initialise agent in a thread (SmartAgent does blocking network ──
            # calls to Ollama/GitHub at startup — keep the event loop free).
            def _init_agent() -> Any:
                s = Settings(workspace_path=_state.workspace)
                a = SmartAgent(s)
                a.events = event_bus
                return a

            agent = await asyncio.to_thread(_init_agent)
            logger.info(
                "MARK STATE agent-ready  active_model=%r",
                getattr(agent.model_manager, "_active_model_id", "none"),
            )

            # ── Route: conversational vs agent task ──────────────────────────
            if _is_conversational_goal(req.goal):
                # ── CHAT PATH — pure greetings / acknowledgements ─────────────
                logger.info("MARK STATE chat  goal=%r", req.goal[:60])

                def _do_chat() -> None:
                    _stream_llm_response(
                        req.goal, _MARK_CHAT_SYSTEM,
                        agent.model_manager, event_bus,
                    )

                await asyncio.to_thread(_do_chat)
                ev_name    = ServerEvents.RUN_COMPLETED
                ev_payload = {
                    "goal":           req.goal,
                    "success":        True,
                    "elapsed":        time.monotonic() - _state.start_time,
                    "files_created":  [],
                    "files_modified": [],
                    "summary":        "",
                }
                logger.info("MARK STATE chat-complete")

            else:
                # ── AGENT PATH — every non-chat request goes here ─────────────
                # MARK uses tool calling to read/write files, run terminal
                # commands, and manage git — never just generates text.
                # Complex multi-step goals → DevPipeline (Planner+Exec+Test+Review+Fix)
                # Simple file/command/query goals → agent_loop directly.
                ticker_task = asyncio.create_task(
                    _status_ticker(), name="mark-status-ticker"
                )

                if _state.cancel_requested:
                    ev_name    = ServerEvents.RUN_CANCELLED
                    ev_payload = {"goal": req.goal, "success": False}
                    logger.info("MARK STATE cancelled  (pre-agent cancel_requested)")
                    return

                from smartagent.engineer.agent_loop import run_agent_loop
                from smartagent.engineer.dev_pipeline import DevPipeline, is_complex_goal

                use_pipeline = is_complex_goal(req.goal)
                logger.info(
                    "MARK STATE routing  goal=%r  use_pipeline=%s",
                    req.goal[:60], use_pipeline,
                )

                if use_pipeline:
                    def _run_pipeline() -> Any:
                        pipeline = DevPipeline(
                            model_manager  = agent.model_manager,
                            event_bus      = event_bus,
                            workspace_path = _state.workspace,
                            test_cmd       = req.test_cmd or None,
                        )
                        return pipeline.run(req.goal)

                    logger.info("MARK STATE executing  dev-pipeline starting")
                    result = await asyncio.to_thread(_run_pipeline)
                else:
                    def _run_agent() -> Any:
                        return run_agent_loop(
                            goal           = req.goal,
                            model_manager  = agent.model_manager,
                            event_bus      = event_bus,
                            workspace_path = _state.workspace,
                        )

                    logger.info("MARK STATE executing  agent-loop starting")
                    result = await asyncio.to_thread(_run_agent)

                logger.info(
                    "MARK STATE executing→complete  success=%s  elapsed=%.1fs  "
                    "files_created=%d  files_modified=%d  stop=%r",
                    result.success,
                    result.total_elapsed,
                    len(result.files_created),
                    len(result.files_modified),
                    result.stop_reason,
                )

                ev_name    = ServerEvents.RUN_COMPLETED
                ev_payload = {
                    "goal":           result.goal or req.goal,
                    "success":        result.success,
                    "elapsed":        result.total_elapsed,
                    "files_created":  result.files_created,
                    "files_modified": result.files_modified,
                    "summary":        (result.final_summary or result.summary or "")[:500],
                }
                logger.info(
                    "MARK STATE completed  ev=%r  success=%s",
                    ev_name, result.success,
                )

        except asyncio.CancelledError:
            ev_name    = ServerEvents.RUN_CANCELLED
            ev_payload = {"goal": req.goal, "success": False}
            logger.info("MARK STATE cancelled  goal=%r", req.goal[:60])
            # Do NOT re-raise — post-run hooks (complete_job + WS broadcast)
            # must run.  The asyncio task will finish normally after the hooks.

        except Exception as exc:
            ev_name    = ServerEvents.RUN_FAILED
            ev_payload = {"goal": req.goal, "error": str(exc), "success": False}
            logger.exception("MARK STATE failed     exception during build: %s", exc)

        finally:
            _state.running = False
            _state._task   = None
            if ticker_task is not None:
                ticker_task.cancel()
            if event_bus is not None:
                try:
                    broadcaster.uninstall(event_bus)
                except Exception:
                    pass
            logger.info(
                "MARK STATE teardown   running=False  ev=%r", ev_name,
            )

        # ── Post-run hooks ────────────────────────────────────────────────────
        run_id   = getattr(_state, "_run_id", "")
        elapsed  = time.monotonic() - _state.start_time

        logger.info(
            "MARK STATE post-run   ev=%r  job_success=%s  run_id=%r",
            ev_name, ev_payload.get("success", False), run_id,
        )

        # Feature 14 — complete the long-running job
        # Use ev_payload["success"] rather than ev_name==RUN_COMPLETED so that
        # RunCompleted with success=False is correctly persisted as failed.
        _job_success = bool(ev_payload.get("success", False))
        try:
            from smartagent.server.api_jobs import complete_job
            complete_job(run_id, success=_job_success,
                         result={"summary": ev_payload.get("summary", "")[:200]})
        except Exception:
            pass

        # Feature 13 — token budget estimate (chars/4 ≈ tokens)
        try:
            goal_tokens   = len(req.goal) // 4
            budget_tokens = 8192
            await connection_manager.broadcast({
                "type":    "event",
                "name":    ServerEvents.TOKEN_BUDGET_UPDATE,
                "payload": {"used": goal_tokens, "window": budget_tokens,
                            "ratio": round(goal_tokens / budget_tokens, 3)},
                "timestamp": _now_iso(),
            })
        except Exception:
            pass

        # Feature 17 — auto-submit evaluation
        try:
            from smartagent.server.api_eval import score_run
            files_c  = len(ev_payload.get("files_created", []))
            files_m  = len(ev_payload.get("files_modified", []))
            score_run(
                run_id=run_id, goal=req.goal,
                success=_job_success,
                elapsed_s=elapsed,
                files_created=files_c, files_modified=files_m,
                tests_passed=0, tests_failed=0,
                tool_calls=0, tool_successes=0,
                workers_completed=len([w for w in _state.workers if w.get("status") == "success"]),
                workers_failed=len([w for w in _state.workers if w.get("status") == "failed"]),
            )
            await connection_manager.broadcast({
                "type":    "event",
                "name":    ServerEvents.EVALUATION_COMPLETE,
                "payload": {"run_id": run_id, "success": _job_success},
                "timestamp": _now_iso(),
            })
        except Exception:
            pass

        # Feature 8 — self-reflection
        try:
            reflection = {
                "succeeded": _job_success,
                "goal":      req.goal[:200],
                "elapsed_s": round(elapsed, 1),
                "lesson":    "Run completed successfully." if _job_success
                             else ("Run was cancelled." if ev_name == ServerEvents.RUN_CANCELLED
                                   else "Run finished with failures — check summary or error."),
            }
            await connection_manager.broadcast({
                "type":    "event",
                "name":    ServerEvents.REFLECTION_COMPLETE,
                "payload": reflection,
                "timestamp": _now_iso(),
            })
        except Exception:
            pass

        # Record in timeline
        try:
            from smartagent.server.api_timeline import record_event
            record_event(ev_name, ev_payload, run_id=run_id)
        except Exception:
            pass

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
# Voice
# ---------------------------------------------------------------------------

@router.get("/voice/status", response_model=VoiceStatusResponse)
async def voice_status() -> VoiceStatusResponse:
    """Return current voice pipeline state and settings."""
    d = voice_manager.status_dict()
    return VoiceStatusResponse(
        state=d["state"],
        running=d["running"],
        settings=d["settings"],
    )


@router.post("/voice/start")
async def voice_start(req: VoiceStartRequest) -> dict:
    """Start the voice pipeline."""
    loop = asyncio.get_running_loop()
    voice_manager.settings.mode = req.mode
    voice_manager.install(None, connection_manager, loop)  # re-wire to live connection_manager
    success, err = voice_manager.start()
    if not success:
        raise HTTPException(status_code=500, detail=err)
    return {"success": True, "state": voice_manager.state}


@router.post("/voice/stop")
async def voice_stop() -> dict:
    """Stop the voice pipeline."""
    voice_manager.stop()
    return {"success": True, "state": voice_manager.state}


@router.post("/voice/speak")
async def voice_speak(req: VoiceSpeakRequest) -> dict:
    """Synthesise text via Piper TTS (non-blocking)."""
    voice_manager.speak(req.text)
    return {"success": True}


@router.post("/voice/transcribe", response_model=VoiceTranscribeResponse)
async def voice_transcribe_endpoint(request: Any) -> VoiceTranscribeResponse:
    """
    Transcribe raw audio uploaded by the browser (push-to-talk).

    Accepts ``multipart/form-data`` with a single ``audio`` file field.
    The file may be:
    - Raw 16-bit PCM (16 kHz mono) — Content-Type: application/octet-stream
    - WAV — Content-Type: audio/wav  (browser MediaRecorder default on most platforms)
    - WebM / OGG — faster-whisper handles these via ffmpeg if available

    Returns JSON ``{ text, duration_ms }``.
    """
    from fastapi import UploadFile, Form
    # Read the raw body
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    t0 = time.monotonic()
    try:
        if "wav" in content_type or body[:4] == b"RIFF":
            text = await asyncio.to_thread(voice_manager.transcribe_wav_bytes, body)
        else:
            # Treat as raw PCM 16-bit 16 kHz mono
            text = await asyncio.to_thread(voice_manager.transcribe_bytes, body)
        duration_ms = (time.monotonic() - t0) * 1000
        if text:
            voice_manager._voice_event("VoiceTranscribed", text=text, source="push_to_talk")
        return VoiceTranscribeResponse(text=text, duration_ms=duration_ms)
    except Exception as exc:
        logger.error("voice_transcribe_endpoint: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/voice/settings")
async def voice_settings_update(req: VoiceSettingsUpdateRequest) -> dict:
    """Partially update voice settings."""
    s = voice_manager.settings
    if req.mode           is not None: s.mode           = req.mode
    if req.wake_phrase    is not None: s.wake_phrase     = req.wake_phrase
    if req.whisper_model  is not None: s.whisper_model   = req.whisper_model
    if req.language       is not None: s.language        = req.language
    if req.tts_voice      is not None: s.tts_voice       = req.tts_voice
    if req.tts_speed      is not None: s.tts_speed       = req.tts_speed
    if req.muted          is not None: s.muted           = req.muted
    if req.auto_submit    is not None: s.auto_submit      = req.auto_submit
    if req.vad_threshold  is not None: s.vad_threshold   = req.vad_threshold
    if req.silence_frames is not None: s.silence_frames  = req.silence_frames
    return {"success": True, "settings": voice_manager.status_dict()["settings"]}


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

    # Workspace analysis — send to this client once after connect
    async def _send_workspace_analysis() -> None:
        try:
            payload = await asyncio.to_thread(
                _analyze_workspace, _state.workspace or "."
            )
            await connection_manager.send_to(ws, {
                "type":      "event",
                "name":      ServerEvents.WORKSPACE_ANALYZED,
                "payload":   payload,
                "timestamp": _now_iso(),
            })
        except Exception as exc:
            logger.debug("workspace analysis failed: %s", exc)

    asyncio.create_task(_send_workspace_analysis())

    # Idle inspector — start once per server process
    _ensure_idle_inspector()

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
# Idle inspector
# ---------------------------------------------------------------------------

_idle_inspector_task: asyncio.Task | None = None


def _ensure_idle_inspector() -> None:
    global _idle_inspector_task
    try:
        loop = asyncio.get_event_loop()
        if _idle_inspector_task is None or _idle_inspector_task.done():
            _idle_inspector_task = loop.create_task(_idle_inspector_loop())
    except Exception:
        pass


async def _idle_inspector_loop() -> None:
    """Emit proactive workspace suggestions when MARK has been idle for 2 min."""
    import time as _t
    _last_notified: float = 0.0
    while True:
        await asyncio.sleep(30)
        try:
            idle_secs = _t.time() - _last_notified
            if not _state.running and idle_secs > 120 and connection_manager.active_connections:
                ws_path = _state.workspace or "."
                suggestions = await asyncio.to_thread(_idle_suggestions, ws_path)
                if suggestions:
                    for sug in suggestions[:4]:
                        await connection_manager.broadcast({
                            "type":      "event",
                            "name":      ServerEvents.IDLE_SUGGESTION,
                            "payload":   sug,
                            "timestamp": _now_iso(),
                        })
                    _last_notified = _t.time()
        except Exception as exc:
            logger.debug("idle inspector error: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
