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
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
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
from smartagent.mind.response_planner import plan_response
from smartagent.llm.factory import is_llm_error_text
from smartagent.server import conversation_store, deploy_awareness, self_state
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
from smartagent.server.speech_runtime import speech_runtime
from smartagent.server import tts_engine
from smartagent.server.websocket import connection_manager
from smartagent.storage.factory import get_storage

# ── Brain Foundation (lazy-import — server starts cleanly if unavailable) ────
try:
    from smartagent.server import brain_events as _brain
    from smartagent.mind.emotion.emotional_state import emotional_state_engine as _emotion
except ImportError:  # pragma: no cover
    _brain = None   # type: ignore[assignment]
    _emotion = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------

class ConversationState:
    """Explicit conversation lifecycle states.

    The state machine advances linearly for each request:
        IDLE → LISTENING → UNDERSTANDING → RESPONDING
                                         ↘ BACKGROUND_PROCESSING (for pipeline runs)
    and returns to IDLE once the response is complete.

    Key invariant: the conversation state must NEVER wait for background
    processing to finish.  Once the user receives a response the state
    returns to IDLE, even if engineering workers are still running.
    """
    IDLE                = "idle"
    LISTENING           = "listening"           # request received, not yet classified
    UNDERSTANDING       = "understanding"       # executive decision in progress
    RESPONDING          = "responding"          # streaming tokens to the client
    BACKGROUND_PROCESSING = "background_processing"  # pipeline running (non-blocking)


# ---------------------------------------------------------------------------
# Latency Budgets — measurable targets; a WARNING is logged when exceeded.
# These are not hard limits; they're observable SLOs for tuning.
# ---------------------------------------------------------------------------

LATENCY_BUDGET_MS = {
    "voice_detection":   150,  # ms from user stops speaking to intent classified
    "intent_classify":    50,  # ms for classify_intent() call
    "memory_lookup":      50,  # ms for recent_turns() / context fetch
    "project_cache":      75,  # ms for cached workspace context lookup
    "first_token":       500,  # ms from request received to first streamed token
}


def _check_latency(label: str, elapsed_ms: float) -> None:
    budget = LATENCY_BUDGET_MS.get(label)
    if budget and elapsed_ms > budget:
        logger.warning(
            "LATENCY BUDGET EXCEEDED  %s: %.0f ms  (budget: %d ms)",
            label, elapsed_ms, budget,
        )
    else:
        logger.debug("latency %s: %.0f ms", label, elapsed_ms)


# ---------------------------------------------------------------------------
# Agent Activation Matrix — defines which components are engaged per route.
# This removes ambiguity about when specialist agents should activate.
# ---------------------------------------------------------------------------

ACTIVATION_MATRIX: dict[str, list[str]] = {
    # Conversational — no engineering specialists, no planning
    "conversational":       ["conversation_engine"],
    "needs_clarification":  ["conversation_engine"],
    # Lightweight engineering (single-shot, no DevPipeline)
    "simple_agent":         ["conversation_engine", "project_cache", "engineer"],
    # Full engineering organization
    "complex_pipeline":     ["planner", "engineer", "qa", "reviewer"],
}

# Convenience aliases — used for documentation; not loaded at runtime
_ACTIVATION_EXAMPLES = {
    "greeting":             ["conversation_engine"],
    "small_talk":           ["conversation_engine"],
    "repository_question":  ["conversation_engine", "project_cache"],
    "build_feature":        ["planner", "engineer"],
    "debug_failing_tests":  ["planner", "engineer", "qa"],
    "architecture_review":  ["planner", "reviewer"],
    "deployment":           ["planner", "engineer", "deployment_agent"],
}


def _log_activation(route: str) -> None:
    components = ACTIVATION_MATRIX.get(route, ["conversation_engine"])
    logger.info("ACTIVATION  route=%s  components=%s", route, components)


# ---------------------------------------------------------------------------
# Executive Decision Layer — 4-question tree run before any work begins.
#
# Q1: Can I answer immediately from conversation and memory?   → conversational
# Q2: Do I need project knowledge?                            → conversational + cache
# Q3: Do I need engineering specialists?                      → full pipeline
# Q4: Can this continue in the background?                    → background_processing
#
# Only if Q3 is YES should the engineering organization be activated.
# ---------------------------------------------------------------------------

def _executive_decision(goal: str) -> "tuple[Any, Any]":
    """Return (intent, plan) by running through the 4-question executive tree.

    The fast path (Q1) bypasses classify_intent entirely for clear conversational
    messages, keeping latency under the 50 ms intent budget for greetings, follow-
    ups, and questions.  All other goals flow through the full intent engine.
    """
    import time as _t
    from types import SimpleNamespace as _SN

    goal_lower = goal.lower().strip()

    _engineering_kws = (
        "create", "build", "write", "fix", "add ", "update",
        "delete", "install", "deploy", "run ", "implement",
        "generate", "make ", "refactor", "test ", "commit",
        "push", "pull ", "branch", "debug", "```",
        "def ", "class ", "import ", "function ", "select ",
        "from ", "insert ", "drop ", "migrate", "scaffold",
        "configure", "setup ", "set up", "review code",
        "code review", "analyse", "analyze", "optimis", "optim",
    )
    _conv_starters = (
        "hi", "hello", "hey", "thanks", "thank", "ok", "okay",
        "sure", "got it", "sounds good", "nice", "cool", "great",
        "what ", "who ", "why ", "how ", "when ", "where ",
        "can you ", "do you ", "is it ", "are you ", "what's",
        "tell me", "explain", "i think", "i feel", "i want",
        "i'm ", "sounds ", "makes sense", "understood",
        "no worries", "never mind", "forget it", "actually",
        "interesting", "yes", "no", "not really", "maybe",
        "hm", "hmm", "wait", "really", "seriously",
        "lgtm", "ship it", "approved",
    )

    has_engineering_kw = any(kw in goal_lower for kw in _engineering_kws)

    # Q1: Can I answer immediately from conversation and memory?
    if not has_engineering_kw and (
        len(goal) < 80
        or any(goal_lower.startswith(sw) for sw in _conv_starters)
    ):
        logger.info("EXECUTIVE Q1=YES  fast-path  goal=%r", goal[:60])
        intent = _SN(
            route="conversational",
            category=_SN(value="conversational"),
            complexity=None,
            clarification_options=None,
        )
        plan = _SN(action="chat", confidence=1.0, reasoning="executive: Q1 immediate answer")
        return intent, plan

    # Q2 / Q3: run the full intent engine
    _t0 = _t.perf_counter()
    intent = classify_intent(goal)
    _classify_ms = (_t.perf_counter() - _t0) * 1000
    _check_latency("intent_classify", _classify_ms)
    logger.info(
        "EXECUTIVE Q2/Q3  category=%s  route=%s  classify_ms=%.0f",
        intent.category.value, intent.route, _classify_ms,
    )
    _log_activation(intent.route)

    # Return a stub plan — the handler re-calls plan_response(agent, ...) with
    # the real agent for non-Q1 routes, so this value is always overridden.
    plan = _SN(action="route", confidence=0.8, reasoning="executive: Q2/Q3 routed")
    return intent, plan


@dataclass
class RunState:
    """Tracks the current (or most recent) MARK build."""

    running: bool          = False
    goal: str              = ""
    workspace: str         = "."
    start_time: float      = 0.0
    cancel_requested: bool = False
    workers: list[dict]    = field(default_factory=list)
    conv_state: str        = ConversationState.IDLE
    _task: Any             = None       # asyncio.Task | None

    @property
    def elapsed(self) -> float:
        if not self.running or self.start_time == 0.0:
            return 0.0
        return time.monotonic() - self.start_time


_state = RunState()

# Tracks the running chat inference asyncio.Task so voice_websocket can cancel
# it the moment the user starts speaking — stops generation, not just playback.
_current_inference_task: "asyncio.Task[Any] | None" = None
# Mutable 2-element list [last_text, last_timestamp] used by the voice dedup
# guard inside _voice_chat_response.  A list (not a tuple) so the function can
# mutate it without a `global` declaration.
_voice_last_text: list = ["", 0.0]
# Mutex that makes the "check running → set running" transition in
# _voice_chat_response atomic.  Without this, two concurrent coroutines
# (one from a second rapid POST, one from a WS reconnect) can both see
# _state.running = False before either sets it to True, causing the same
# utterance to be processed twice.
_voice_chat_lock: "asyncio.Lock | None" = None


def _get_voice_chat_lock() -> "asyncio.Lock":
    """Return (creating on first call) the per-event-loop voice chat lock.

    asyncio.Lock must be created in the same event loop it is used from.
    Lazy creation here avoids issues with import-time event-loop state.
    """
    global _voice_chat_lock  # noqa: PLW0603
    if _voice_chat_lock is None:
        _voice_chat_lock = asyncio.Lock()
    return _voice_chat_lock


async def _set_conv_state(new_state: str) -> None:
    """Advance the conversation state machine and broadcast the transition."""
    _state.conv_state = new_state
    try:
        await connection_manager.broadcast({
            "type":      "event",
            "name":      "CONV_STATE",
            "payload":   {"state": new_state},
            "timestamp": _now_iso(),
        })
    except Exception:
        pass  # never crash the run because of a state broadcast failure


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


# ── The one persistent MARK ──────────────────────────────────────────────
#
# SmartAgent used to be constructed fresh on every /run call — a new mind,
# a new executive, a new reflection engine, discarded the moment the
# response was sent. That's the opposite of "MARK is one persistent
# intelligence": it's an identity rebuilt from scratch on every message.
# _get_mark_agent() is the fix — one SmartAgent, constructed once, reused
# for the life of the server process. Only memory/knowledge are rescoped
# when the workspace changes (what MARK knows ABOUT a given project);
# identity, mind, executive, reflection, skills, tools, and model_manager
# stay the same continuous instance regardless of which project MARK is
# pointed at, matching "one persistent identity", not one identity per
# project.
#
# In-place memory/knowledge rescoping relies on this server's existing
# single-flight assumption (/run rejects a second concurrent request with
# 409 — see the `_state.running` check above). If that assumption ever
# changes, this would need real per-request isolation instead.
_mark_agent: Any = None
_mark_agent_lock = threading.Lock()
_mark_agent_memory_cache: dict[str, Any] = {}
_mark_agent_knowledge_cache: dict[str, Any] = {}


async def _get_mark_agent(workspace: str | None) -> Any:
    """Return THE SmartAgent for this server process, constructing it on
    first use. SmartAgent does blocking network calls at construction
    (NVIDIA/GitHub) — kept off the event loop via asyncio.to_thread."""
    global _mark_agent
    if _mark_agent is None:
        def _construct() -> Any:
            s = Settings(workspace_path=workspace)
            a = SmartAgent(s)
            _mark_agent_memory_cache[workspace or ""] = a.memory
            _mark_agent_knowledge_cache[workspace or ""] = a.knowledge
            return a
        with _mark_agent_lock:
            if _mark_agent is None:
                _mark_agent = await asyncio.to_thread(_construct)
        return _mark_agent

    if workspace and workspace not in _mark_agent_memory_cache:
        def _scope() -> None:
            from smartagent.knowledge.knowledge_manager import KnowledgeManager
            from smartagent.memory.memory_manager import MemoryManager
            s = Settings(workspace_path=workspace)
            _mark_agent_memory_cache[workspace] = MemoryManager(
                backend=s.memory_backend, vault_path=s.vault_path,
                categories=s.memory_categories, event_bus=_mark_agent.events,
            )
            _mark_agent_knowledge_cache[workspace] = KnowledgeManager(
                knowledge_path=getattr(s, "knowledge_path", "knowledge"),
            )
        with _mark_agent_lock:
            if workspace not in _mark_agent_memory_cache:
                await asyncio.to_thread(_scope)

    if workspace:
        _mark_agent.memory = _mark_agent_memory_cache[workspace]
        _mark_agent.knowledge = _mark_agent_knowledge_cache[workspace]
    return _mark_agent


def _peek_mark_agent() -> Any:
    """The persistent agent if one has been constructed yet, else None —
    never triggers construction. For passive reads (e.g. /self-state)
    that shouldn't force a slow SmartAgent startup just to answer a poll."""
    return _mark_agent


def _reset_mark_agent_for_tests() -> None:
    """Test-only: drop the persistent agent so the next call to
    _get_mark_agent constructs a fresh one — otherwise a test's
    ``patch("smartagent.server.api.SmartAgent")`` would have no effect
    once a real (or previously-mocked) instance is already cached."""
    global _mark_agent
    _mark_agent = None
    _mark_agent_memory_cache.clear()
    _mark_agent_knowledge_cache.clear()


def _outcome_summary(ev_payload: dict, ev_name: str) -> str:
    """The one deterministic description of what a run actually did —
    shared by every post-run consumer (mind's self-model, the quick
    reflect_on_run lesson) so they reason about the same facts instead of
    each deriving their own summary of the same event."""
    return str(ev_payload.get("summary") or ev_payload.get("error") or ev_name or "")


async def _broadcast_self_state(agent: Any) -> None:
    """Push MARK's current self-state to every connected client — called at
    the two real transition points (a task starting, a task finishing), not
    on a timer. The frontend's Presence Engine is driven by this, plus its
    own one-time fetch on connect; it never polls."""
    try:
        await connection_manager.broadcast({
            "type": "event",
            "name": ServerEvents.SELF_STATE_CHANGED,
            "payload": self_state.snapshot(agent),
            "timestamp": _now_iso(),
        })
    except Exception:
        pass


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
        # Publish fallback via a dedicated NO-TTS event so speech_runtime
        # does NOT speak it aloud.  Speaking the fallback through TTS is what
        # causes the self-message feedback loop: mic picks up the speaker
        # output, STT transcribes it, and it arrives as a new "user" message.
        # The frontend still displays it as a chat bubble; it just won't be
        # spoken.  STREAMING_TOKEN is reserved for real LLM tokens that the
        # user specifically asked for — not for error/fallback messages.
        event_bus.publish("CHAT_MESSAGE", text=CHAT_FALLBACK_TEXT, source="mark", tts=False)
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


@router.get("/healthz")
async def healthz() -> dict:
    """Kubernetes-style liveness alias — also used by the retired Node.js
    api-server to confirm the combined server absorbed its only endpoint."""
    return {"status": "ok"}


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
# Workspace refresh — explicit cache invalidation (Cache Invalidation Rule #4)
# ---------------------------------------------------------------------------

@router.post("/workspace/refresh")
async def workspace_refresh() -> dict:
    """Force a fresh workspace scan on the next connection event.

    Cache Invalidation Rules — the project cache refreshes automatically when:
      1. A git commit changes (HEAD hash differs)
      2. Files are added, modified, or removed (dirty-file count changes)
      3. The active branch changes
      4. The user explicitly calls this endpoint  ← you are here
      5. MARK starts for the first time (no cache exists yet)

    This endpoint covers rule #4. It clears the in-memory analysis cache and
    the git-HEAD record so the next WebSocket connect runs a full scan.
    """
    ws_path = os.path.abspath(_state.workspace or ".")
    conversation_store.invalidate_workspace_cache(ws_path)
    logger.info("workspace/refresh: cache invalidated for %s", ws_path)
    await connection_manager.broadcast({
        "type":      "event",
        "name":      "WORKSPACE_CACHE_CLEARED",
        "payload":   {"workspace": ws_path, "reason": "explicit_refresh"},
        "timestamp": _now_iso(),
    })
    return {"status": "ok", "workspace": ws_path, "message": "Cache cleared — next connect will rescan"}


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
        # Allow the new run through if the current inference task was
        # already cancelled by a voice interrupt — there is a narrow race
        # where speech_start fires, _current_inference_task.cancel() runs,
        # but the finally block in _run() hasn't cleared _state.running yet
        # by the time the voice transcript arrives and calls /run again.
        # Resetting here lets the new turn start immediately instead of
        # dropping the user's spoken message with a 409.
        _task = _current_inference_task
        if _task is not None and (_task.done() or _task.cancelled()):
            _state.running = False   # stale flag — clear and fall through
        else:
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
        reply_text: str  = ""     # set in the conversational/clarification paths
        global _current_inference_task

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

        try:
            # Use module-level imports (patchable in tests).
            # Create a fresh EventBus so the broadcaster wires to the correct one.
            event_bus = EventBus()
            broadcaster.install(event_bus, connection_manager, loop)

            # MARK's real voice — subscribes to the same StreamingToken
            # events the dashboard reads, synthesizes+broadcasts real audio
            # sentence-by-sentence as MARK's reply is generated. See
            # speech_runtime.py; flushed/reset around this run below.
            speech_runtime.attach(connection_manager, loop)
            speech_runtime.reset()
            event_bus.subscribe(ServerEvents.STREAMING_TOKEN, speech_runtime.on_token)

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

            # ── The one persistent MARK, not a fresh one per message ──────────
            agent = await _get_mark_agent(_state.workspace)
            agent.events = event_bus
            _active_model = getattr(agent.model_manager, "_active_model_id", None)
            logger.info(
                "MARK STATE agent-ready  active_model=%r", _active_model or "none",
            )
            self_state.task_started(agent, req.goal)
            await _broadcast_self_state(agent)

            # ── Executive Decision Layer ──────────────────────────────────
            # State: LISTENING → UNDERSTANDING
            # The 4-question executive tree decides which components activate.
            # It runs BEFORE any worker dispatch or LLM call.  See
            # _executive_decision() for the full decision logic and the
            # ACTIVATION_MATRIX for which agents each route engages.
            await _set_conv_state(ConversationState.LISTENING)

            # Measure memory lookup latency (Tier 1 — short-term context)
            _mem_t0 = time.perf_counter()
            _recent_history = conversation_store.recent_turns(_state.workspace)
            _check_latency("memory_lookup", (time.perf_counter() - _mem_t0) * 1000)

            await _set_conv_state(ConversationState.UNDERSTANDING)
            intent, plan = _executive_decision(req.goal)

            # Let agent.mind score confidence for non-fast-path routes
            if plan.reasoning.startswith("executive: Q1"):
                pass  # fast path — plan already set
            else:
                plan = plan_response(agent, req.goal, intent)

            if intent.route == "conversational":
                # ── CHAT PATH — greetings, questions, brainstorming; no ──────
                # worker dispatch at all.
                await _set_conv_state(ConversationState.RESPONDING)
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

                    # ── Presence-aware context injection ─────────────────────
                    # The base _MARK_CHAT_SYSTEM is built from CHAT_SURFACE_NOTES
                    # and frames MARK as a project-management orchestrator, which
                    # makes every casual exchange feel like a help-desk script
                    # ("I'm MARK — I plan engineering work…"). For conversational
                    # replies we prepend a short directive that overrides that
                    # framing so MARK responds as a present, self-aware colleague
                    # rather than a task router.
                    _presence_prefix = (
                        "You are speaking directly with the person you work alongside. "
                        "Respond naturally — as a present, curious colleague who knows them. "
                        "Don't introduce yourself as a project-management tool unless directly "
                        "asked. Be warm, brief, and genuine. If you don't know something, say so. "
                        "Skip the corporate framing."
                    )
                    system_prompt = f"{_presence_prefix}\n\n{_MARK_CHAT_SYSTEM}"
                    ctx = conversation_store.get_cached_workspace_context(_state.workspace)
                    if ctx:
                        preamble = _workspace_preamble(ctx)
                        system_prompt = f"{system_prompt}\n\nCurrent project context: {preamble}"
                    return _stream_llm_response(
                        req.goal, system_prompt,
                        agent.model_manager, event_bus,
                        history=history,
                    )

                # ── Brain Foundation: emit cognitive events; track the task so
                # voice_websocket can cancel inference when the user speaks ──
                if _brain is not None:
                    await _brain.thinking_started(req.goal)
                try:
                    _current_inference_task = asyncio.ensure_future(
                        asyncio.to_thread(_do_chat)
                    )
                    reply_text = await _current_inference_task
                except asyncio.CancelledError:
                    reply_text = ""   # user interrupted — no reply to send
                finally:
                    _current_inference_task = None
                _chat_ms = int((time.monotonic() - _state.start_time) * 1000)
                if _brain is not None:
                    await _brain.thinking_finished(_chat_ms)
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
                await _set_conv_state(ConversationState.RESPONDING)
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

                    # Q4: Can this continue in the background?
                    # Pipeline work IS background — conversation returns to IDLE
                    # as soon as the plan announcement completes.  Workers run
                    # asynchronously and never block the next user message.
                    await _set_conv_state(ConversationState.BACKGROUND_PROCESSING)
                    logger.info("MARK STATE executing  dev-pipeline starting")
                    result = await asyncio.to_thread(_run_pipeline)

                    # Reflect on the mission in the background — never
                    # delays the response, never breaks it if it fails
                    # (see reflection_bridge.py for why this only runs
                    # for pipeline missions, not single-shot agent tasks).
                    # The quick, synchronous lesson (Feature 8, below) and
                    # mind.complete_task() already recorded what happened
                    # from the deterministic outcome; once this deeper,
                    # slower analysis finishes, it feeds its own conclusion
                    # back into the SAME persistent self-model instead of
                    # being a write-only side channel nothing else reads.
                    def _reflect() -> None:
                        from smartagent.server.reflection_bridge import reflect_on_pipeline_result
                        deep = reflect_on_pipeline_result(result, agent)
                        if deep is not None:
                            top_issue = (deep.critic.what_failed or deep.critic.what_succeeded or [None])[0]
                            agent.mind.reflection_engine.reflect(
                                task_name=f"deep review: {result.goal[:60]}",
                                succeeded=result.success,
                                what_happened=f"Critic scored this mission {deep.critic.overall_score:.0%}.",
                                what_failed=None if result.success else top_issue,
                                learned=top_issue if result.success else None,
                            )
                    asyncio.create_task(
                        asyncio.to_thread(_reflect), name="mark-reflect",
                    )
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
            await _set_conv_state(ConversationState.IDLE)
            if ticker_task is not None:
                ticker_task.cancel()
            if event_bus is not None:
                try:
                    broadcaster.uninstall(event_bus)
                except Exception:
                    pass
            try:
                speech_runtime.flush()
            except Exception:
                pass
            if agent is not None:
                self_state.task_finished(
                    agent, req.goal,
                    succeeded=bool(ev_payload.get("success")),
                    what_happened=_outcome_summary(ev_payload, ev_name),
                )
                # Brain Foundation: update emotional state from real outcome
                if _emotion is not None:
                    if ev_name == ServerEvents.RUN_COMPLETED and ev_payload.get("success"):
                        _emotion.on_success(req.goal)
                    elif ev_name == ServerEvents.RUN_FAILED:
                        _emotion.on_failure(ev_payload.get("error", ""))
                    elif intent is not None and getattr(intent, "route", "") == "needs_clarification":
                        _emotion.on_needs_clarification()
                if _brain is not None:
                    try:
                        asyncio.create_task(
                            _brain.emotion_changed(
                                _emotion.state if _emotion else "neutral",
                                _emotion.reason if _emotion else "",
                            ),
                            name="mark-emotion",
                        )
                    except Exception:
                        pass
                # event_bus is already uninstalled above — broadcast directly
                # via connection_manager, same as the post-run hooks below.
                await _broadcast_self_state(agent)
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
            # Same summary mind.complete_task() was already given above —
            # one shared record of what happened, not two independently
            # derived descriptions of the same run.
            outcome_summary = _outcome_summary(ev_payload, ev_name)

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

        # Brain Foundation: post-conversation learning pipeline
        # Extracts facts, updates owner memory, stores episodic memory, and
        # proposes concepts to the knowledge graph — background task so the
        # user's response is never delayed by learning overhead.
        if _brain is not None and agent is not None:
            try:
                async def _post_learning() -> None:
                    try:
                        from smartagent.server import learning_pipeline
                        result = await asyncio.to_thread(
                            learning_pipeline.run,
                            req.goal, reply_text,
                            _job_success,
                            _emotion.state if _emotion is not None else "neutral",
                            getattr(agent, "knowledge_manager", None),
                        )
                        if _brain is not None:
                            await _brain.memory_written("episodic", req.goal[:80])
                        for concept in (result.get("concepts_proposed") or [])[:2]:
                            if _brain is not None:
                                await _brain.knowledge_created(concept)
                            if _emotion is not None:
                                _emotion.on_knowledge_created(concept)
                    except Exception as _le:
                        logger.debug("post-learning failed: %s", _le)
                asyncio.create_task(_post_learning(), name="mark-learning")
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

    # Workspace analysis — runs on connect, with two optimisations:
    #
    #  1. Git-HEAD caching: if the current commit hasn't changed since the
    #     last scan, skip the full filesystem walk and reuse the cached payload.
    #     Full analysis still runs on first connect, git push, or branch switch.
    #
    #  2. Reconnect detection: if the user reconnects within 30 minutes (tab
    #     refresh, HMR, brief disconnect) MARK skips the full LLM opening and
    #     sends a brief one-line acknowledgement instead. This stops the repeated
    #     "Good morning, I've looked over this repo…" self-introductions.
    async def _send_workspace_analysis() -> None:
        ws_path = os.path.abspath(_state.workspace or ".")

        # ── Step 1: get current git HEAD (fast subprocess, won't block) ──────
        import subprocess as _sp

        def _get_git_info() -> tuple[str, str, int]:
            """Return (head, branch, dirty_file_count).

            Cache Invalidation Rules:
              1. HEAD hash changes → new commit → rescan
              2. dirty_count changes → uncommitted file changes → rescan
              3. branch changes → branch switch → rescan
              4. explicit POST /workspace/refresh → rescan (handled separately)
              5. first start (no cache) → rescan
            """
            try:
                head = _sp.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ws_path,
                    text=True, stderr=_sp.DEVNULL,
                ).strip()
                branch = _sp.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ws_path,
                    text=True, stderr=_sp.DEVNULL,
                ).strip()
                # Count changed files (tracked+untracked) — cheap compared to full scan
                status_out = _sp.check_output(
                    ["git", "status", "--short"], cwd=ws_path,
                    text=True, stderr=_sp.DEVNULL,
                )
                dirty = len([l for l in status_out.splitlines() if l.strip()])
                return head, branch, dirty
            except Exception:
                return "", "", 0

        git_head, git_branch, git_dirty = await asyncio.to_thread(_get_git_info)

        # ── Step 2: decide whether to run a full scan ─────────────────────────
        # Cache is valid only if HEAD, branch, AND dirty-file count all match.
        cached_head_info = conversation_store.get_workspace_git_head(ws_path)
        cached_ctx       = conversation_store.get_cached_workspace_context(ws_path)
        if cached_head_info is not None and len(cached_head_info) == 3:
            cached_head, cached_branch, cached_dirty = cached_head_info
        elif cached_head_info is not None:
            cached_head, cached_branch, cached_dirty = cached_head_info[0], cached_head_info[1], -1
        else:
            cached_head, cached_branch, cached_dirty = "", "", -1

        head_unchanged = (
            git_head
            and cached_ctx is not None
            and cached_head == git_head
            and cached_branch == git_branch
            and cached_dirty == git_dirty
        )

        if head_unchanged:
            payload = cached_ctx
            logger.info(
                "workspace analysis: HEAD %s branch=%s dirty=%d unchanged — using cache",
                git_head[:8], git_branch, git_dirty,
            )
        else:
            reason = (
                "first scan" if not cached_head else
                f"HEAD {cached_head[:8]}→{git_head[:8]}" if cached_head != git_head else
                f"branch {cached_branch}→{git_branch}" if cached_branch != git_branch else
                f"dirty {cached_dirty}→{git_dirty} files"
            )
            logger.info("workspace analysis: cache miss (%s) — running full scan", reason)
            try:
                payload = await asyncio.to_thread(_analyze_workspace, ws_path)
                conversation_store.cache_workspace_context(ws_path, payload)
                if git_head:
                    conversation_store.update_workspace_git_head(
                        ws_path, git_head, git_branch, git_dirty
                    )
            except Exception as exc:
                logger.debug("workspace analysis failed: %s", exc)
                return

        # Always send WORKSPACE_ANALYZED so the frontend panels stay up to date,
        # even when we used a cached payload.
        try:
            await connection_manager.send_to(ws, {
                "type":      "event",
                "name":      ServerEvents.WORKSPACE_ANALYZED,
                "payload":   payload,
                "timestamp": _now_iso(),
            })
        except Exception as exc:
            logger.debug("WORKSPACE_ANALYZED send failed: %s", exc)

        # ── Step 3: reconnect detection ───────────────────────────────────────
        # If the user reconnected within the session window (30 min), skip the
        # full LLM opening — just confirm MARK is present. This prevents the
        # repeated "Good morning / I've looked over this repo…" cycle that
        # fires on every tab refresh.
        greeting_age = conversation_store.get_last_greeting_age(ws_path)
        is_reconnect  = greeting_age < conversation_store.RECONNECT_WINDOW_SECS

        if is_reconnect:
            project_type = (payload or {}).get("project_type", "the project")
            branch_name  = (payload or {}).get("git_branch", "")
            if greeting_age < 120:
                reconnect_text = "I'm still here."
            elif branch_name:
                reconnect_text = f"Back — still on {branch_name}. What do you need?"
            else:
                reconnect_text = f"I'm still here, focused on {project_type}. What do you need?"
            try:
                await connection_manager.send_to(ws, {
                    "type":      "event",
                    "name":      ServerEvents.MARK_OPENING,
                    "payload":   {"text": reconnect_text},
                    "timestamp": _now_iso(),
                })
            except Exception:
                pass
            logger.info("workspace opening: reconnect (age=%.0fs) — brief ack", greeting_age)
            conversation_store.record_greeting(ws_path)
            return

        # ── Step 4: full opening (first connect or returning after 30+ min) ───
        frameworks_text = ", ".join(payload.get("frameworks") or []) or "no detected framework"
        fallback_opening = (
            f"Looking at this {payload.get('project_type') or 'repository'} — "
            f"branch {payload.get('git_branch') or 'unknown'}, {frameworks_text}, "
            f"{payload.get('todo_count', 0)} open TODOs. What do you want to work on?"
        )

        # "Remember and check if changes were made" — compares the current git
        # HEAD against what MARK last saw so it can naturally mention new commits.
        try:
            change_summary = await asyncio.to_thread(
                deploy_awareness.check_for_new_commits,
                ws_path,
            )
        except Exception:
            change_summary = None

        mark_agent = await _get_mark_agent(_state.workspace)

        # Capture the running event loop before entering to_thread so the
        # closure can hand it to speech_runtime.attach().
        _compose_loop = asyncio.get_event_loop()

        def _compose_opening() -> str:
            mm = mark_agent.model_manager

            import datetime as _dt
            _hour = _dt.datetime.now().hour
            _tod = "morning" if _hour < 12 else "afternoon" if _hour < 17 else "evening"

            facts = _workspace_preamble(payload)
            if change_summary:
                facts = f"{facts}\n\n{change_summary}"
            facts = f"Good {_tod}. {facts}"

            messages = [
                {"role": "system", "content": _MARK_OPENING_SYSTEM},
                {"role": "user",   "content": facts},
            ]
            chunks: list[str] = []

            _opening_bus = None
            if not _state.running and EventBus is not None:
                try:
                    speech_runtime.attach(connection_manager, _compose_loop)
                    speech_runtime.reset()
                    _opening_bus = EventBus()
                    _opening_bus.subscribe(ServerEvents.STREAMING_TOKEN, speech_runtime.on_token)
                except Exception as _be:
                    logger.debug("opening TTS setup failed: %s", _be)
                    _opening_bus = None

            try:
                for chunk in mm.chat_stream(messages, max_tokens=200):
                    if chunk and is_llm_error_text(chunk):
                        raise RuntimeError(chunk)
                    if chunk:
                        chunks.append(chunk)
                        if _opening_bus is not None:
                            _opening_bus.publish(
                                ServerEvents.STREAMING_TOKEN, text=chunk, source="mark"
                            )
            finally:
                if _opening_bus is not None:
                    speech_runtime.flush()

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

        conversation_store.record_greeting(ws_path)

    asyncio.create_task(_send_workspace_analysis())

    # Idle inspector — start once per server process
    _ensure_idle_inspector()

    # Real-voice engine readiness — checked once per server process. First
    # call downloads real model weights if they're not cached yet, so this
    # runs in a background thread rather than blocking this connection.
    _ensure_speech_engine_checked()

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
# Voice pipeline — WebSocket mic streaming + fast chat response
# ---------------------------------------------------------------------------

async def _voice_chat_response(text: str, workspace: str) -> None:
    """Lightweight voice-chat LLM response — forces the conversational fast
    path (direct LLM → TTS, no SmartAgent planning or worker dispatch).

    Called either from POST /voice/message (browser-triggered) or directly
    from voice_websocket on final transcript.  Always runs in a background
    asyncio task so it never blocks the caller.

    If an engineering run is currently active (e.g. the user spoke before a
    previous task completed), we wait up to 3 s for it to clear — the
    speech_start event will have already cancelled the inference task by the
    time the final transcript arrives, so the wait is usually <100 ms.

    Voice-mode response style is optimised for TTS: no markdown, no bullets,
    spoken-sentence cadence.  Context (workspace, conversation history) is
    still injected so MARK sounds coherent across turns.
    """
    global _state, _current_inference_task   # noqa: PLW0603

    # ── Self-message / feedback-loop guard ───────────────────────────────────
    # When the LLM is unavailable, _stream_llm_response falls back to
    # CHAT_FALLBACK_TEXT and plays it through TTS.  The microphone can then
    # pick up that speaker audio, STT transcribes it, and the same text
    # arrives here as a new "user" utterance — creating an infinite loop.
    #
    # Guard: reject any incoming text that exactly matches, closely resembles,
    # or starts with known fallback/self-introduction phrases.  This is a
    # belt-and-suspenders safety net; the real fix is a working LLM provider.
    _LOOP_PHRASES = (
        CHAT_FALLBACK_TEXT[:30].lower(),   # starts-with match on the first phrase
        "i'm mark",
        "i am mark",
        "i plan engineering work",
        "what would you like to build",
        # ── Media / broadcast audio contamination ──────────────────────────────
        # YouTube, podcast, and TV outros commonly picked up by open microphones.
        # These never originate from a live user speaking to MARK; drop them to
        # avoid spurious LLM calls and the appearance of MARK "talking to himself".
        "thanks for watching",
        "thank you for watching",
        "see you next time",
        "see you in the next video",
        "i'll see you in the next",
        "hope you'll see you in the next",
        "don't forget to subscribe",
        "hit that like button",
        "subscribe to the channel",
        "like and subscribe",
        "smash that subscribe button",
        "leave a comment below",
        "click the bell",
        "turn on notifications",
        "support the channel",
        "check out my other videos",
        "link in the description",
        "notes in the description",
        "in the description below",
    )
    logger.info("voice_chat: received transcript %r (len=%d)", text[:80], len(text))

    _text_lower = text.lower().strip()
    if any(_text_lower.startswith(p) or p in _text_lower for p in _LOOP_PHRASES):
        logger.warning(
            "voice_chat: dropping suspected self-echo/media-audio text: %r", text[:60]
        )
        return

    # ── Deduplication guard ───────────────────────────────────────────────────
    # VAD can fire two `final` events for the same utterance (endpoint
    # detected, then re-detected after a brief pause).  Identical text within
    # 5 seconds is almost certainly a double-trigger — drop the second copy.
    _now_mono = time.monotonic()
    if (
        _voice_last_text[0] == _text_lower
        and _now_mono - _voice_last_text[1] < 5.0
    ):
        logger.info("voice_chat: duplicate transcript within 5 s — dropping: %r", text[:60])
        return
    _voice_last_text[0] = _text_lower
    _voice_last_text[1] = _now_mono

    # Wait for any interrupted run to fully clean up before we start, then
    # claim the lock atomically so a second concurrent coroutine can't slip
    # through the TOCTOU window between "see running=False" and "set running=True".
    _lock = _get_voice_chat_lock()
    async with _lock:
        for _ in range(30):
            if not _state.running:
                break
            await asyncio.sleep(0.1)
        if _state.running:
            logger.info("voice_chat: run still active after 3 s — skipping response for %r", text[:60])
            return
        # Claim the run slot immediately while still holding the lock.
        _state.running = True
        logger.info("voice_chat: starting response for %r", text[:80])

    ws = workspace or _state.workspace or ""
    loop = asyncio.get_event_loop()
    _state.goal        = text
    _state.workspace   = ws
    _state.start_time  = time.monotonic()
    _state.cancel_requested = False

    try:
        event_bus = EventBus()
        broadcaster.install(event_bus, connection_manager, loop)
        speech_runtime.attach(connection_manager, loop)
        speech_runtime.reset()
        event_bus.subscribe(ServerEvents.STREAMING_TOKEN, speech_runtime.on_token)

        await connection_manager.broadcast({
            "type":      "event",
            "name":      ServerEvents.RUN_STARTED,
            "payload":   {"goal": text, "workspace": ws},
            "timestamp": _now_iso(),
        })

        agent = await _get_mark_agent(ws or None)
        agent.events = event_bus

        # ── Cognition-first conversation (Brain Runtime owns this) ───────────
        # The transcript is an OBSERVATION. It enters the Brain Runtime, which
        # retrieves memory + owner model + knowledge, reads emotional state, and
        # reasons — producing a semantic Decision. Only then does the Speech
        # Planner turn that Decision into spoken words. MARK's cognition never
        # depends on generated text; the words express the Decision, they are
        # not the Decision. See smartagent/server/brain_runtime.py.
        from smartagent.server.brain_runtime import brain_runtime, Observation
        observation = Observation(text=text, workspace=ws, source="voice")

        if _brain is not None:
            await _brain.thinking_started(text)

        # Fused phone-call turn: ONE streamed reasoning call in which the
        # semantic Decision is emitted first (cognition), then MARK's spoken
        # words stream straight into speech_runtime → Kokoro. The decision is
        # surfaced to the dashboard the moment it completes — before speech.
        def _on_decision(decision) -> None:  # runs in the worker thread
            asyncio.run_coroutine_threadsafe(
                connection_manager.broadcast({
                    "type":      "event",
                    "name":      "MarkDecision",
                    "payload":   decision.to_event(),
                    "timestamp": _now_iso(),
                }),
                loop,
            )

        _current_inference_task = asyncio.ensure_future(
            asyncio.to_thread(
                brain_runtime.converse, observation, agent, event_bus,
                token_event=ServerEvents.STREAMING_TOKEN,
                on_decision=_on_decision,
            )
        )
        decision = None
        reply_text = ""
        try:
            decision, reply_text = await _current_inference_task
        except asyncio.CancelledError:
            pass
        finally:
            _current_inference_task = None

        if _brain is not None:
            await _brain.thinking_finished(
                int((time.monotonic() - _state.start_time) * 1000)
            )
        speech_runtime.flush()
        # Transcript persistence — for memory, search, accessibility, debugging.
        # NOT the source of truth for the conversation (the Decision was).
        conversation_store.append_turn(ws, "user", text)
        conversation_store.append_turn(ws, "assistant", reply_text)
        if decision is not None:
            try:
                brain_runtime.record_turn(observation, decision, reply_text)
            except Exception:
                pass

        await connection_manager.broadcast({
            "type":      "event",
            "name":      ServerEvents.RUN_COMPLETED,
            "payload":   {
                "goal":           text,
                "success":        True,
                "elapsed":        time.monotonic() - _state.start_time,
                "files_created":  [],
                "files_modified": [],
                "summary":        "",
            },
            "timestamp": _now_iso(),
        })
    except Exception as exc:
        logger.warning("voice_chat_response: %s", exc)
        try:
            await connection_manager.broadcast({
                "type":      "event",
                "name":      ServerEvents.RUN_FAILED,
                "payload":   {"goal": text, "success": False, "error": str(exc)},
                "timestamp": _now_iso(),
            })
        except Exception:
            pass
    finally:
        _state.running = False


# ---------------------------------------------------------------------------
# WebSocket voice transport — continuous mic streaming, no WebRTC.
#
# This is the reliable single-user local transport: the browser
# (use-voice.ts) streams raw PCM16 @ 16 kHz frames over this WebSocket; we
# feed them to a VoiceSession (Silero VAD + faster-whisper + turn-taking)
# and stream transcript events back.  MARK's spoken reply (Kokoro TTS) goes
# back as binary PCM frames on the MAIN /ws connection (speech_runtime's
# legacy broadcast path, active whenever no LiveKit AudioSource is set).
#
# No separate server, no JWT, no UDP media ports, no Windows-Firewall
# surface — everything rides the one TCP WebSocket the dashboard already
# uses.  Chosen over self-hosted LiveKit for exactly that reliability.
# ---------------------------------------------------------------------------

@router.post("/voice/message")
async def voice_message(payload: dict) -> dict:
    """Receive a final voice transcript and trigger MARK's spoken reply.

    The browser POSTs {text, workspace} here the moment the server-side VAD
    reports a complete utterance (the 'final' event on /ws/voice).  MARK's
    reply is generated in the background and streamed back as audio over the
    main /ws — so this returns immediately.
    """
    text = (payload.get("text") or "").strip()
    workspace = payload.get("workspace") or _state.workspace or ""
    if not text:
        return {"ok": False, "reason": "empty"}
    asyncio.ensure_future(_voice_chat_response(text, workspace))
    return {"ok": True}


# Sticky conversation ownership: exactly one mic stream drives MARK at a
# time.  Ownership is claimed by streaming audio and KEPT while frames keep
# arriving; another connection can only take over after the owner has gone
# silent for _VOICE_OWNER_GRACE_S (tab closed, crashed, or stopped).  Frames
# from non-owners inside the grace window are dropped — never processed,
# never evicting — so two live tabs can't ping-pong-evict each other and a
# background tab can't steal the conversation mid-sentence.
_VOICE_OWNER_GRACE_S = 3.0
_active_voice_ws: dict[str, Any] = {"ws": None, "last_frame": 0.0}


@router.websocket("/ws/voice")
async def voice_websocket(ws: WebSocket) -> None:
    """Continuous browser-mic voice stream.

    Protocol
    --------
    Browser → server:
      * binary frames  — raw PCM16 mono @ 16 kHz mic audio
      * text  {"type":"tts_start"} / {"type":"tts_end"} — mic-gate hints while
        MARK is speaking (secondary echo-cancellation layer)

    Server → browser (JSON text frames):
      * {"type":"speech_start"}        — user started talking (drives barge-in)
      * {"type":"partial","text":...}  — interim transcript (display only)
      * {"type":"final","text":...}    — complete utterance (display only)

    Phone-call loop: when VAD closes an utterance ("final"), MARK's brain is
    dispatched HERE, server-side, the same instant — the browser never relays
    the transcript back (the old final → browser → debounce → POST round-trip
    added seconds of latency and silently dropped turns when the tab was
    throttled).  The browser only displays transcripts and plays audio.
    """
    from smartagent.server.voice_pipeline import (
        VoiceSession, register_session, unregister_session,
    )

    await ws.accept()

    loop = asyncio.get_event_loop()
    # Make sure speech_runtime can stream TTS audio + speech events back over
    # the main /ws while this voice socket is open.
    speech_runtime.attach(connection_manager, loop)

    session = VoiceSession()
    register_session(session)
    ws_workspace = ws.query_params.get("workspace", "") or ""
    logger.info("voice_ws: mic stream connected")

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            data = message.get("bytes")
            if data is not None:
                # ── Sticky ownership (see _active_voice_ws above) ──────────
                now = time.monotonic()
                owner = _active_voice_ws.get("ws")
                if owner is ws:
                    _active_voice_ws["last_frame"] = now
                elif owner is None or (
                    now - _active_voice_ws.get("last_frame", 0.0) > _VOICE_OWNER_GRACE_S
                ):
                    logger.info(
                        "voice_ws: conversation ownership → %s (prev owner silent/absent)",
                        getattr(ws, "client", "?"),
                    )
                    if owner is not None:
                        try:
                            await owner.close(code=4000)
                        except Exception:
                            pass
                    _active_voice_ws["ws"] = ws
                    _active_voice_ws["last_frame"] = now
                else:
                    # A live conversation exists on another connection —
                    # drop this frame silently. No eviction, no processing.
                    continue
                # Feed one PCM16 frame through VAD/STT.  transcribe() inside
                # feed() is blocking, so run the whole step in a worker thread
                # to keep the event loop responsive.  Calls are awaited in
                # order, so VoiceSession is never touched concurrently.
                try:
                    events = await asyncio.to_thread(session.feed, data)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("voice_ws: feed error: %s", exc)
                    continue
                for ev in events:
                    await ws.send_text(json.dumps(ev))
                    # ── Direct brain dispatch — the streamline loop ────────
                    if ev.get("type") == "final" and ev.get("text"):
                        asyncio.ensure_future(
                            _voice_chat_response(ev["text"], ws_workspace)
                        )
                continue

            text = message.get("text")
            if text:
                try:
                    ctrl = json.loads(text)
                except Exception:
                    continue
                ctrl_type = ctrl.get("type")
                if ctrl_type == "tts_start":
                    session.mute()
                elif ctrl_type == "tts_end":
                    session.unmute()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice_ws: %s", exc)
    finally:
        if _active_voice_ws.get("ws") is ws:
            _active_voice_ws["ws"] = None
        unregister_session(session)
        logger.info("voice_ws: mic stream disconnected")


# ---------------------------------------------------------------------------
# LiveKit voice endpoints (M1 + WebSocket proxy for signaling)
# ---------------------------------------------------------------------------

@router.get("/voice/token")
async def voice_token(role: str = "browser") -> dict:
    """Issue a LiveKit JWT for the browser or the MARK agent."""
    try:
        import uuid
        from smartagent.server.livekit_token import (
            create_browser_token, create_agent_token, livekit_configured,
        )
        if not livekit_configured():
            raise HTTPException(
                503,
                "LiveKit not configured — run `python -m smartagent.server.livekit_setup`",
            )
        if role == "agent":
            token = create_agent_token()
        else:
            token = create_browser_token(identity=f"browser-{uuid.uuid4().hex[:8]}")
        return {"token": token, "role": role}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/voice/config")
async def voice_config() -> dict:
    """Return LiveKit connection config for the browser.

    The browser uses the returned *url* to connect its LiveKit Room.
    On Replit (and any reverse-proxied deployment), *url* points at the
    /livekit-rtc WebSocket proxy on this same server so no extra port is
    needed.  Set LIVEKIT_BROWSER_URL to override with an external LiveKit
    host.
    """
    from smartagent.server.livekit_token import LIVEKIT_ROOM, livekit_configured

    lk_url  = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
    # Explicit override wins — useful for LiveKit Cloud or a custom domain.
    browser_url = os.environ.get("LIVEKIT_BROWSER_URL", "")

    if not browser_url:
        # Auto-derive: route signaling through this server's own base URL so
        # no second port needs to be exposed.  Works on Replit and any HTTPS
        # reverse proxy.
        api_base = os.environ.get("API_BASE_URL", "").rstrip("/")
        if api_base:
            ws_base = api_base.replace("https://", "wss://").replace("http://", "ws://")
            browser_url = f"{ws_base}/livekit-rtc"
        else:
            # Local dev fallback: browser → LiveKit direct (works when both
            # run on the same machine, i.e. `pnpm dev` on a dev laptop).
            browser_url = "ws://localhost:7880"

    is_cloud = "livekit.cloud" in lk_url or "livekit.cloud" in browser_url
    return {
        "url":       browser_url,
        "room":      LIVEKIT_ROOM,
        "mode":      "cloud" if is_cloud else "self-hosted",
        "available": livekit_configured(),
    }


@router.websocket("/livekit-rtc")
async def livekit_rtc_proxy(ws: WebSocket) -> None:
    """Proxy LiveKit WebSocket signaling through MARK's server.

    The browser connects to MARK at /livekit-rtc?access_token=...
    and this handler forwards the connection to the local LiveKit server
    on localhost:7880.  This makes LiveKit reachable through MARK's
    existing port — no extra firewall rules or port exposure needed.

    In self-hosted mode the LiveKit binary runs locally (started by
    mark_supervisor.py) and never needs to be directly accessible from
    the internet for signaling — only for WebRTC media (UDP 50000-60000),
    which the browser attempts via ICE candidates.
    """
    import websockets as _wsl

    await ws.accept()
    lk_port   = int(os.environ.get("LIVEKIT_PORT", "7880"))
    query_str = str(ws.url.query)
    upstream  = f"ws://127.0.0.1:{lk_port}/rtc"
    if query_str:
        upstream += f"?{query_str}"

    try:
        async with _wsl.connect(upstream, max_size=None, ping_interval=None) as lk:
            async def _fwd_to_lk() -> None:
                try:
                    async for chunk in ws.iter_bytes():
                        await lk.send(chunk)
                except Exception:
                    pass

            async def _fwd_to_ws() -> None:
                try:
                    async for msg in lk:
                        if isinstance(msg, bytes):
                            await ws.send_bytes(msg)
                        else:
                            await ws.send_text(msg)
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [asyncio.create_task(_fwd_to_lk()), asyncio.create_task(_fwd_to_ws())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("livekit_rtc_proxy: %s", exc)


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


# ---------------------------------------------------------------------------
# Speech engine readiness (MARK's real voice)
# ---------------------------------------------------------------------------

_speech_engine_check_task: asyncio.Task | None = None


def _ensure_speech_engine_checked() -> None:
    global _speech_engine_check_task
    try:
        loop = asyncio.get_event_loop()
        if _speech_engine_check_task is None or _speech_engine_check_task.done():
            _speech_engine_check_task = loop.create_task(_speech_engine_check())
    except Exception:
        pass


async def _speech_engine_check() -> None:
    """Real check, once per process — may download real model weights on
    first run. If the real engine can't initialize, tell every connected
    client explicitly so the frontend can fall back to the browser's
    speechSynthesis as the documented emergency-only path, instead of
    silently having no voice at all."""
    try:
        available = await asyncio.to_thread(tts_engine.is_available)
        if not available:
            await connection_manager.broadcast({
                "type":      "event",
                "name":      ServerEvents.SPEECH_ENGINE_UNAVAILABLE,
                "payload":   {"reason": tts_engine.unavailable_reason() or "unknown"},
                "timestamp": _now_iso(),
            })
            logger.warning(
                "MARK STATE speech-engine  unavailable  reason=%r",
                tts_engine.unavailable_reason(),
            )
        else:
            logger.info("MARK STATE speech-engine  ready  voice=%s", tts_engine.MARK_VOICE)
    except Exception as exc:
        logger.warning("speech engine check failed: %s", exc)


async def _idle_inspector_loop() -> None:
    """Emit proactive workspace suggestions when MARK has been idle for 45 s.

    Suggestions already reported to the user within the last 24 hours are
    filtered out so the same item ("No tests for hi.py") is never repeated
    until it is genuinely new or resolved.  If all current suggestions were
    already reported, MARK stays quiet instead of repeating itself.
    """
    import time as _t
    _last_notified: float = 0.0
    while True:
        await asyncio.sleep(15)
        try:
            idle_secs = _t.time() - _last_notified
            if not _state.running and idle_secs > 45 and connection_manager.active_connections:
                ws_path = _state.workspace or "."

                # Raw suggestions from static analysis
                all_suggestions = await asyncio.to_thread(_idle_suggestions, ws_path)

                # Filter: keep only items the user has NOT already seen today
                new_suggestions = conversation_store.filter_unreported_suggestions(
                    ws_path, all_suggestions
                )

                if new_suggestions:
                    for sug in new_suggestions[:4]:
                        await connection_manager.broadcast({
                            "type":      "event",
                            "name":      ServerEvents.IDLE_SUGGESTION,
                            "payload":   sug,
                            "timestamp": _now_iso(),
                        })
                    # Record that these were reported — won't show again for 24 h.
                    # NOTE: _broadcast_idle_chat_message is intentionally NOT called
                    # here.  Unsolicited LLM-generated chat messages appearing in the
                    # conversation thread while the user hasn't said anything feel like
                    # ghost traffic and break voice sessions (echo → transcript →
                    # another LLM call).  Suggestions are surfaced only in the passive
                    # Idle Suggestions panel (IDLE_SUGGESTION events above), never as
                    # a MARK_PROACTIVE message that interrupts the conversation.
                    conversation_store.mark_suggestions_reported(ws_path, new_suggestions)
                    _last_notified = _t.time()
                else:
                    # Everything already reported — reset the idle timer so we
                    # don't spin again immediately, but don't broadcast anything.
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

    mark_agent = await _get_mark_agent(workspace)

    def _compose() -> str:
        mm = mark_agent.model_manager
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
