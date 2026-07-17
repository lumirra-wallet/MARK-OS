"""
MARK server — Event Bus bridge.

WebSocketBroadcaster subscribes to the MARK EventBus (one-time setup when a
run starts) and fans every published event out to all connected WebSocket
clients.  Because EventBus.publish() is synchronous and can be called from
a worker thread, we use asyncio.run_coroutine_threadsafe() to schedule the
async broadcast on the event-loop thread without blocking the caller.

PrintInterceptor replaces builtins.print for the duration of a build so
every print() call is also emitted as a StreamingToken event on the bus,
making it visible in the dashboard terminal.

Server-specific event names (not part of the core EventBus vocabulary) are
collected in ServerEvents so publishers and subscribers agree on spelling.
"""

from __future__ import annotations

import asyncio
import builtins
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Generator

from smartagent.brain.events import Event

if TYPE_CHECKING:
    from smartagent.brain.events import EventBus
    from smartagent.server.websocket import ConnectionManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Server-specific event name constants
# ---------------------------------------------------------------------------

class ServerEvents:
    """Event names emitted by the server layer (not by MARK core)."""

    # Worker lifecycle
    WORKER_STARTED   = "WorkerStarted"
    WORKER_FINISHED  = "WorkerFinished"
    WORKER_THINKING  = "WorkerThinking"

    # Planning
    PLANNING_STARTED  = "PlanningStarted"
    PLANNING_FINISHED = "PlanningFinished"

    # Tools
    TOOL_STARTED  = "ToolStarted"
    TOOL_FINISHED = "ToolFinished"

    # File operations
    FILE_CREATED  = "FileCreated"
    FILE_MODIFIED = "FileModified"
    FILE_DELETED  = "FileDeleted"

    # Git
    GIT_COMMIT = "GitCommit"

    # Tests
    TESTS_STARTED = "TestsStarted"
    TESTS_PASSED  = "TestsPassed"
    TESTS_FAILED  = "TestsFailed"

    # Quality
    QUALITY_STARTED  = "QualityStarted"
    QUALITY_FINISHED = "QualityFinished"

    # Model
    MODEL_STARTED  = "ModelStarted"
    MODEL_FINISHED = "ModelFinished"

    # Streaming
    STREAMING_TOKEN = "StreamingToken"

    # MARK speaking outside of a run (e.g. the proactive opening message)
    MARK_OPENING = "MarkOpening"

    # MARK speaking up mid-session, unprompted (e.g. idle-repo findings) —
    # same "MARK opens a new chat message" contract as MARK_OPENING, just
    # triggered later than connect time.
    MARK_PROACTIVE = "MarkProactive"

    # System
    ERROR          = "Error"
    STATUS_CHANGED = "StatusChanged"

    # Permissions
    PERMISSION_REQUESTED = "PermissionRequested"
    PERMISSION_GRANTED   = "PermissionGranted"
    PERMISSION_DENIED    = "PermissionDenied"

    # Run lifecycle
    RUN_STARTED   = "RunStarted"
    RUN_COMPLETED = "RunCompleted"
    RUN_CANCELLED = "RunCancelled"
    RUN_FAILED    = "RunFailed"

    # Task graph / multi-agent (Feature 1, 2, 7)
    TASK_GRAPH_UPDATED   = "TaskGraphUpdated"
    TASK_NODE_STARTED    = "TaskNodeStarted"
    TASK_NODE_COMPLETED  = "TaskNodeCompleted"
    TASK_NODE_FAILED     = "TaskNodeFailed"
    AGENT_MESSAGE        = "AgentMessage"

    # Checkpoints (Feature 10)
    CHECKPOINT_CREATED   = "CheckpointCreated"

    # Jobs (Feature 14)
    JOB_STARTED          = "JobStarted"
    JOB_PAUSED           = "JobPaused"
    JOB_RESUMED          = "JobResumed"
    JOB_COMPLETED        = "JobCompleted"

    # Evaluation (Feature 17)
    EVALUATION_COMPLETE  = "EvaluationComplete"

    # Reflection (Feature 8)
    REFLECTION_STARTED   = "ReflectionStarted"
    REFLECTION_COMPLETE  = "ReflectionComplete"

    # Token budget (Feature 13)
    TOKEN_BUDGET_UPDATE  = "TokenBudgetUpdate"

    # Tool calls (Feature 3)
    TOOL_CALLED          = "ToolCalled"
    TOOL_RESULT          = "ToolResult"

    # Terminal (Feature 11)
    TERMINAL_OUTPUT      = "TerminalOutput"

    # Live Engineer panel
    WORKSPACE_ANALYZED  = "WorkspaceAnalyzed"   # startup project context
    REASONING_STAGE     = "ReasoningStage"      # current execution phase
    ACTIVITY_FEED_ENTRY = "ActivityFeedEntry"   # one action in the live feed
    IDLE_SUGGESTION     = "IdleSuggestion"      # proactive improvement hint
    MEMORY_UPDATED      = "MemoryUpdated"       # engineering session memory

    # Previews (Task 19)
    PREVIEW_REGISTERED     = "PreviewRegistered"
    PREVIEW_UPDATED        = "PreviewUpdated"
    PREVIEW_CLOSED         = "PreviewClosed"


# ---------------------------------------------------------------------------
# WebSocket broadcaster
# ---------------------------------------------------------------------------

class WebSocketBroadcaster:
    """
    Bridge between the synchronous MARK EventBus and async WebSocket clients.

    Call ``install(event_bus, connection_manager, loop)`` once before a run
    starts.  Every subsequent EventBus.publish() call will be forwarded as a
    JSON message to all connected WebSocket clients without polling.

    Call ``uninstall(event_bus)`` after the run ends to remove the handler.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager: ConnectionManager | None = None

    def install(
        self,
        event_bus: "EventBus",
        manager: "ConnectionManager",
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Subscribe to all events on *event_bus* and route them to *manager*."""
        self._loop    = loop
        self._manager = manager
        event_bus.subscribe_all(self._on_event)
        logger.debug("WebSocketBroadcaster installed")

    def uninstall(self, event_bus: "EventBus") -> None:
        """Remove the catch-all subscription."""
        event_bus.unsubscribe_all(self._on_event)
        self._loop    = None
        self._manager = None
        logger.debug("WebSocketBroadcaster uninstalled")

    def _on_event(self, event: Event) -> None:
        """
        Called synchronously from any thread when an event is published.

        Schedules an async broadcast on the event loop using
        run_coroutine_threadsafe so the caller is never blocked.
        """
        if self._loop is None or self._manager is None:
            return
        msg: dict = {
            "type":      "event",
            "name":      event.name,
            "payload":   event.payload,
            "timestamp": event.timestamp,
        }
        try:
            asyncio.run_coroutine_threadsafe(
                self._manager.broadcast(msg),
                self._loop,
            )
        except RuntimeError:
            # Loop already closed — ignore (happens during test teardown).
            pass


# ---------------------------------------------------------------------------
# Print interceptor
# ---------------------------------------------------------------------------

class _PrintInterceptor:
    """
    Context manager that replaces ``builtins.print`` with a function that
    also emits a ``StreamingToken`` event on the given EventBus.

    The original print behaviour is preserved so CLI output still works.
    Thread-safe assumption: only one MARK build runs at a time.
    """

    def __init__(self, event_bus: "EventBus") -> None:
        self._bus  = event_bus
        self._orig = builtins.print

    def __enter__(self) -> "_PrintInterceptor":
        bus      = self._bus
        orig     = self._orig

        def _intercepted_print(
            *args: object,
            sep:  str = " ",
            end:  str = "\n",
            **kwargs,
        ) -> None:
            text = sep.join(str(a) for a in args) + end
            # Emit event FIRST so the dashboard sees the text immediately.
            try:
                bus.publish(ServerEvents.STREAMING_TOKEN, text=text, source="print")
            except Exception:
                pass
            # Still write to stdout/file as requested.
            orig(*args, sep=sep, end=end, **kwargs)

        builtins.print = _intercepted_print  # type: ignore[assignment]
        return self

    def __exit__(self, *_: object) -> None:
        builtins.print = self._orig  # type: ignore[assignment]


@contextmanager
def intercept_print(event_bus: "EventBus") -> Generator[None, None, None]:
    """Context manager that routes print() calls through the EventBus."""
    interceptor = _PrintInterceptor(event_bus)
    with interceptor:
        yield


# Module-level singleton used by api.py.
broadcaster = WebSocketBroadcaster()
