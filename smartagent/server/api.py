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
GET  /settings/autonomy  — current Level-4 autonomy mode ("manual" | "auto")
POST /settings/autonomy  — set the Level-4 autonomy mode
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

from smartagent.identity.mark_identity import (
    build_system_prompt,
    CHAT_FALLBACK_TEXT,
    CHAT_SURFACE_NOTES,
    IDLE_SURFACE_NOTES,
    OPENING_SURFACE_NOTES,
    PLAN_SURFACE_NOTES,
)
from smartagent.engineer.agent_tools import execute_tool, git_unpushed_count
from smartagent.engineer.dev_pipeline import classify_intent
from smartagent.llm.factory import is_llm_error_text
from smartagent.server import conversation_store, deploy_awareness
from smartagent.server.events import ServerEvents, broadcaster, intercept_print
from smartagent.server.reflection import reflect_on_run
from smartagent.server.workspace_analyzer import (
    analyze_workspace as _analyze_workspace,
    idle_suggestions as _idle_suggestions,
)
from smartagent.server.engineering_memory import engineering_memory
from smartagent.server.models import (
    ApproveRequest,
    AutonomyModeRequest,
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
from smartagent.server.permissions import APPROVED, permission_gate
from smartagent.server.websocket import connection_manager
from smartagent.storage.factory import get_storage

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
#
# Intent classification lives in smartagent.engineer.dev_pipeline.classify_intent
# — the single Conversation Manager decision point (see B2 plan note). This
# used to be two independent, ad-hoc classifiers (_is_conversational_goal
# here + is_complex_goal in dev_pipeline.py); consolidating them fixed a real
# bug where ambiguous, non-action phrasing ("what do you think?") defaulted
# to the agent path instead of staying conversational.

# System prompts ─────────────────────────────────────────────────────────────

_MARK_CHAT_SYSTEM    = build_system_prompt(CHAT_SURFACE_NOTES)
_MARK_PLAN_SYSTEM    = build_system_prompt(PLAN_SURFACE_NOTES)
_MARK_OPENING_SYSTEM = build_system_prompt(OPENING_SURFACE_NOTES)
_MARK_IDLE_SYSTEM    = build_system_prompt(IDLE_SURFACE_NOTES)


def _build_model_manager(workspace: str | None) -> Any:
    """
    Construct a fresh SmartAgent for *workspace* and return its
    ``model_manager``. SmartAgent does blocking network calls at
    construction (NVIDIA/GitHub) — call this via ``asyncio.to_thread``.
    """
    s = Settings(workspace_path=workspace)
    a = SmartAgent(s)
    return a.model_manager


def _stream_llm_response(
    goal: str,
    system_prompt: str,
    model_manager: Any,
    event_bus: Any,
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    Call the active LLM and publish every token as a StreamingToken event.

    Must be called from a worker thread (``asyncio.to_thread``) because
    ``model_manager.chat_stream()`` is a blocking iterator.  Falls back to a
    canned reply when no model is loaded or the call fails.

    *history* (oldest first) is inserted between the system message and the
    current turn — this is what makes chat stateful across turns; omit it
    (or pass ``None``) for a one-off completion with no prior context.

    Returns the full composed text (or the fallback text on failure) so
    callers can persist it as a turn in conversation_store.
    """
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": goal})
    chunks: list[str] = []
    try:
        for chunk in model_manager.chat_stream(messages):
            if chunk and is_llm_error_text(chunk):
                raise RuntimeError(chunk)
            if chunk:
                chunks.append(chunk)
                event_bus.publish(ServerEvents.STREAMING_TOKEN, text=chunk, source="mark")
        return "".join(chunks)
    except Exception as exc:
        logger.warning(
            "MARK _stream_llm_response: LLM unavailable (%s) — using fallback", exc
        )
        event_bus.publish(ServerEvents.STREAMING_TOKEN, text=CHAT_FALLBACK_TEXT, source="mark")
        return CHAT_FALLBACK_TEXT


def _workspace_preamble(ctx: dict[str, Any]) -> str:
    """
    Compact 2-4 line project-state summary for injection into the chat
    system prompt — built from a cached analyze_workspace() payload
    (conversation_store.get_cached_workspace_context), never recomputed
    per chat turn.
    """
    frameworks_text = ", ".join(ctx.get("frameworks") or []) or "no detected framework"
    return (
        f"{ctx.get('project_type') or 'a'} project on branch "
        f"{ctx.get('git_branch') or 'unknown'}, using {frameworks_text}. "
        f"{ctx.get('todo_count', 0)} open TODOs. Tests via "
        f"{ctx.get('test_framework') or 'none detected'}."
    )


async def _push_with_approval(workspace: str, ahead: int) -> None:
    """
    Request approval to push *ahead* local commits to the remote, then push
    if approved — Level 4 (engineering execution) per the four-level
    autonomy model. Skips the approval wait entirely when
    settings.autonomy_mode == "auto"; otherwise creates a real
    PermissionGate request and waits for a human to approve/deny it via
    POST /approve or /deny (same mechanism the dashboard already uses for
    delete_file — see permissions.py).

    Runs detached from any single /run call's lifecycle (see its one
    caller, in the post-run hooks section above) — broadcasts via
    connection_manager directly rather than a per-run EventBus, since the
    triggering run's own event_bus may already be torn down by the time a
    human actually responds.
    """
    try:
        autonomy_mode = get_storage().get_or_default("settings", "autonomy_mode", "manual")
        if autonomy_mode != "auto":
            perm = permission_gate.create_request(
                "git_push", workspace,
                diff=f"{ahead} local commit{'s' if ahead != 1 else ''} ready to push to origin.",
            )
            await connection_manager.broadcast({
                "type":    "event",
                "name":    ServerEvents.PERMISSION_REQUESTED,
                "payload": {
                    "request_id": perm.request_id,
                    "operation":  perm.operation,
                    "path":       perm.path,
                    "diff":       perm.diff,
                },
                "timestamp": _now_iso(),
            })
            outcome = await permission_gate.wait_for_approval(perm)
            if outcome != APPROVED:
                logger.info(
                    "MARK STATE push  denied/timeout  workspace=%r  result=%r",
                    workspace, outcome,
                )
                return

        def _push() -> str:
            return execute_tool("git_push", {}, workspace)
        push_result = await asyncio.to_thread(_push)
        logger.info("MARK STATE push  workspace=%r  result=%r", workspace, push_result[:200])
    except Exception as exc:
        logger.warning("_push_with_approval failed: %s", exc)


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
        agent: Any       = None   # assigned inside try — may stay None if init fails
        intent: Any      = None   # assigned inside try — may stay None if init fails

        logger.info(
            "MARK STATE queued    goal=%r  workspace=%r",
            req.goal[:80], _state.workspace,
        )

        from smartagent.server.rate_limiter import get_run_rate_limiter
        if not get_run_rate_limiter().allow(_state.workspace or "."):
            logger.warning("MARK STATE rate-limited  workspace=%r", _state.workspace)
            _state.running = False
            _state._task   = None
            await connection_manager.broadcast({
                "type": "event", "name": ServerEvents.RUN_FAILED,
                "payload": {
                    "goal": req.goal, "success": False,
                    "error": "Too many requests in a short window — please wait a moment and try again.",
                },
                "timestamp": _now_iso(),
            })
            return

        from smartagent.server.self_state import get_self_state_tracker
        get_self_state_tracker().task_started()

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
            # calls to NVIDIA/GitHub at startup — keep the event loop free).
            def _init_agent() -> Any:
                s = Settings(workspace_path=_state.workspace)
                a = SmartAgent(s)
                a.events = event_bus
                return a

            agent = await asyncio.to_thread(_init_agent)
            _active_model = getattr(agent.model_manager, "_active_model_id", None)
            logger.info(
                "MARK STATE agent-ready  active_model=%r", _active_model or "none",
            )
            get_self_state_tracker().set_model(_active_model)

            # ── Route: the single Conversation Manager decision point ────────
            intent = classify_intent(req.goal)
            logger.info(
                "MARK STATE intent  goal=%r  category=%s  route=%s",
                req.goal[:60], intent.category.value, intent.route,
            )

            if intent.route == "conversational":
                # ── CHAT PATH — greetings, questions, brainstorming; no ──────
                # worker dispatch at all.
                logger.info("MARK STATE chat  goal=%r", req.goal[:60])

                def _do_chat() -> str:
                    # Pure identity questions ("who are you?") are answered
                    # directly from MARK's own identity profile — no LLM
                    # call, no worker dispatch. Retrieved, not generated.
                    from smartagent.identity.profile import (
                        identity_chat_reply, is_identity_question,
                    )
                    if is_identity_question(req.goal):
                        reply = identity_chat_reply()
                        event_bus.publish(ServerEvents.STREAMING_TOKEN, text=reply, source="mark")
                        return reply

                    history = conversation_store.recent_turns(_state.workspace)
                    system_prompt = _MARK_CHAT_SYSTEM
                    ctx = conversation_store.get_cached_workspace_context(_state.workspace)
                    if ctx:
                        preamble = _workspace_preamble(ctx)
                        system_prompt = f"{_MARK_CHAT_SYSTEM}\n\nCurrent project: {preamble}"
                    return _stream_llm_response(
                        req.goal, system_prompt,
                        agent.model_manager, event_bus,
                        history=history,
                    )

                reply_text = await asyncio.to_thread(_do_chat)
                conversation_store.append_turn(_state.workspace, "user", req.goal)
                conversation_store.append_turn(_state.workspace, "assistant", reply_text)
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

            elif intent.route == "needs_clarification":
                # ── CLARIFICATION PATH — goal is real but too vague to hand ──
                # a worker without guessing. Ask, don't auto-plan. Composed
                # directly in Python from the classifier's own options — no
                # LLM call, no worker dispatch, same as the identity fast path.
                logger.info("MARK STATE clarify  goal=%r", req.goal[:60])
                options = intent.clarification_options or ("this",)
                numbered = "\n".join(f"{i}. {opt}" for i, opt in enumerate(options, start=1))
                reply_text = f"Do you want me to improve:\n{numbered}\n\nOr something else?"
                event_bus.publish(ServerEvents.STREAMING_TOKEN, text=reply_text, source="mark")
                conversation_store.append_turn(_state.workspace, "user", req.goal)
                conversation_store.append_turn(_state.workspace, "assistant", reply_text)
                ev_name    = ServerEvents.RUN_COMPLETED
                ev_payload = {
                    "goal":           req.goal,
                    "success":        True,
                    "elapsed":        time.monotonic() - _state.start_time,
                    "files_created":  [],
                    "files_modified": [],
                    "summary":        "asked for clarification",
                }
                logger.info("MARK STATE clarify-complete")

            else:
                # ── AGENT PATH — every non-conversational request goes here ──
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
                from smartagent.engineer.dev_pipeline import DevPipeline

                use_pipeline = intent.route == "complex_pipeline"
                logger.info(
                    "MARK STATE routing  goal=%r  use_pipeline=%s  complexity=%s",
                    req.goal[:60], use_pipeline,
                    intent.complexity.value if intent.complexity else None,
                )

                if use_pipeline:
                    # Bigger, multi-milestone builds get a short heads-up of
                    # what MARK is about to do before dispatch — gives
                    # _MARK_PLAN_SYSTEM its only live call site. Skipped for
                    # simple_agent tasks to avoid latency/noise on quick asks.
                    def _do_plan_announcement() -> None:
                        _stream_llm_response(
                            req.goal, _MARK_PLAN_SYSTEM,
                            agent.model_manager, event_bus,
                        )
                    await asyncio.to_thread(_do_plan_announcement)

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
            get_self_state_tracker().task_finished()
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
            outcome_summary = ev_payload.get("summary") or ev_payload.get("error", "")

            def _do_reflect() -> Any:
                return reflect_on_run(
                    req.goal, outcome_summary, _job_success,
                    ev_name == ServerEvents.RUN_CANCELLED,
                    agent.model_manager if agent is not None else None,
                )

            reflection_result = await asyncio.to_thread(_do_reflect)
            reflection = {
                "succeeded": _job_success,
                "goal":      req.goal[:200],
                "elapsed_s": round(elapsed, 1),
                "lesson":    reflection_result.lesson,
            }
            await connection_manager.broadcast({
                "type":    "event",
                "name":    ServerEvents.REFLECTION_COMPLETE,
                "payload": reflection,
                "timestamp": _now_iso(),
            })
            if reflection_result.should_ask_user and reflection_result.ask_user_message:
                await connection_manager.broadcast({
                    "type":    "event",
                    "name":    ServerEvents.MARK_PROACTIVE,
                    "payload": {"text": reflection_result.ask_user_message},
                    "timestamp": _now_iso(),
                })
        except Exception:
            pass

        # Feature: auto-push after a successful engineering run — Level 4
        # (engineering execution) per the four-level autonomy model: gated
        # behind PermissionGate approval unless autonomy_mode="auto".
        # Scheduled as a detached background task (not awaited) so a
        # pending approval — up to 5 minutes — never delays RunCompleted or
        # blocks the next run; it uses connection_manager directly rather
        # than the per-run event_bus, since event_bus is torn down in the
        # `finally` block above and won't outlive this function.
        try:
            if (
                intent is not None
                and intent.route == "complex_pipeline"
                and ev_payload.get("success")
            ):
                def _count() -> int:
                    return git_unpushed_count(_state.workspace)
                ahead = await asyncio.to_thread(_count)
                if ahead > 0:
                    asyncio.create_task(
                        _push_with_approval(_state.workspace, ahead),
                        name="mark-push-approval",
                    )
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
# Autonomy mode
# ---------------------------------------------------------------------------

@router.get("/settings/autonomy")
async def get_autonomy_mode() -> dict:
    """
    Current Level-4 (engineering execution) autonomy mode.

    "manual" (default) pauses for explicit approval on gated operations
    (currently: pushing commits after a successful engineering run).
    "auto" skips the approval wait entirely — opt-in unattended execution.
    """
    mode = get_storage().get_or_default("settings", "autonomy_mode", "manual")
    return {"autonomy_mode": mode}


@router.post("/settings/autonomy")
async def set_autonomy_mode(req: AutonomyModeRequest) -> dict:
    if req.mode not in ("manual", "auto"):
        raise HTTPException(400, "mode must be 'manual' or 'auto'")
    get_storage().set("settings", "autonomy_mode", req.mode)
    return {"autonomy_mode": req.mode}


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

    # Workspace analysis — send to this client once after connect, then let
    # MARK open the conversation with a short observation composed from it
    # (a real first exchange, not just a silent Repository Summary update).
    async def _send_workspace_analysis() -> None:
        try:
            payload = await asyncio.to_thread(
                _analyze_workspace, _state.workspace or "."
            )
            conversation_store.cache_workspace_context(_state.workspace, payload)
            await connection_manager.send_to(ws, {
                "type":      "event",
                "name":      ServerEvents.WORKSPACE_ANALYZED,
                "payload":   payload,
                "timestamp": _now_iso(),
            })
        except Exception as exc:
            logger.debug("workspace analysis failed: %s", exc)
            return

        frameworks_text = ", ".join(payload.get("frameworks") or []) or "no detected framework"
        fallback_opening = (
            f"I've looked over this {payload.get('project_type') or 'repository'} — "
            f"on branch {payload.get('git_branch') or 'unknown'}, using {frameworks_text}, "
            f"with {payload.get('todo_count', 0)} open TODOs. "
            "Tell me what you'd like built or fixed and I'll get the team on it."
        )

        # "Remember and check if changes were made" — compares the current
        # git HEAD against what MARK last saw running here (persisted via
        # get_storage(), so it survives a restart/redeploy) and feeds any
        # summary into the opening prompt as another fact for MARK's own
        # LLM to weave in naturally, the same way _workspace_preamble()'s
        # project facts are injected below.
        #
        # Resolved to an absolute path (matching os.path.abspath(req.workspace)
        # in the /run handler) rather than using _state.workspace as-is: it
        # defaults to the literal string "." until the first /run call, which
        # would hash to a different workspace_id() than engineering_memory's
        # key for the same project once a run does set an absolute path.
        try:
            change_summary = await asyncio.to_thread(
                deploy_awareness.check_for_new_commits,
                os.path.abspath(_state.workspace or "."),
            )
        except Exception:
            change_summary = None

        def _compose_opening() -> str:
            mm = _build_model_manager(_state.workspace)
            facts = _workspace_preamble(payload)
            if change_summary:
                facts = f"{facts}\n\n{change_summary}"
            messages = [
                {"role": "system", "content": _MARK_OPENING_SYSTEM},
                {"role": "user",   "content": facts},
            ]
            chunks: list[str] = []
            for chunk in mm.chat_stream(messages, max_tokens=200):
                if chunk and is_llm_error_text(chunk):
                    raise RuntimeError(chunk)
                if chunk:
                    chunks.append(chunk)
            return "".join(chunks).strip()

        try:
            opening_text = await asyncio.to_thread(_compose_opening)
        except Exception as exc:
            logger.debug("MARK opening message LLM call failed, using fallback: %s", exc)
            opening_text = ""

        try:
            await connection_manager.send_to(ws, {
                "type":      "event",
                "name":      ServerEvents.MARK_OPENING,
                "payload":   {"text": opening_text or fallback_opening},
                "timestamp": _now_iso(),
            })
        except Exception as exc:
            logger.debug("MARK opening message send failed: %s", exc)

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
                    await _broadcast_idle_chat_message(ws_path, suggestions)
                    _last_notified = _t.time()
        except Exception as exc:
            logger.debug("idle inspector error: %s", exc)


async def _broadcast_idle_chat_message(workspace: str, suggestions: list[dict[str, str]]) -> None:
    """
    Turn idle_suggestions() findings into a real, unprompted MARK chat
    message — this is what makes MARK actually speak up on its own instead
    of only populating the passive Idle Suggestions list. Same
    "one LLM call, deterministic fallback on failure" shape as the opening
    message, so a run never goes silent even if the LLM call fails.
    """
    top = suggestions[0]
    fallback = (
        f"While you were away, I noticed something: {top['title']}. "
        f"{top['description']} Want me to take care of it?"
    )

    def _compose() -> str:
        mm = _build_model_manager(workspace)
        facts = "\n".join(
            f"- [{s.get('priority', 'low')}] {s['title']}: {s['description']}"
            + (f" ({s['file']})" if s.get("file") else "")
            for s in suggestions[:3]
        )
        messages = [
            {"role": "system", "content": _MARK_IDLE_SYSTEM},
            {"role": "user",   "content": f"Findings from reviewing the repository while idle:\n{facts}"},
        ]
        chunks: list[str] = []
        for chunk in mm.chat_stream(messages, max_tokens=200):
            if chunk and is_llm_error_text(chunk):
                raise RuntimeError(chunk)
            if chunk:
                chunks.append(chunk)
        return "".join(chunks).strip()

    try:
        text = await asyncio.to_thread(_compose)
    except Exception as exc:
        logger.debug("idle chat message LLM call failed, using fallback: %s", exc)
        text = ""

    try:
        await connection_manager.broadcast({
            "type":      "event",
            "name":      ServerEvents.MARK_PROACTIVE,
            "payload":   {"text": text or fallback},
            "timestamp": _now_iso(),
        })
    except Exception as exc:
        logger.debug("idle chat message broadcast failed: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
