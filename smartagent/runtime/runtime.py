"""
runtime.py — The Elena Runtime.

The Runtime IS Elena.  It is the one object that owns her continuous existence:
her session, her memory, her identity, her event nervous system, her
configuration, and her catalogue of swappable service providers.

It does NOT own reasoning, speech, or model inference — those are registered
as Providers and the Runtime delegates to whichever one is currently active.

Lifecycle
─────────
    runtime = Runtime.create()
    await runtime.start()

    # … system runs …

    await runtime.stop()

Thread / concurrency model
──────────────────────────
The Runtime is designed for single-event-loop asyncio use.  All public methods
that touch async state are coroutines.  Synchronous methods (config, identity
accessors) are safe to call from anywhere.

Design invariants
─────────────────
• One Runtime per process.  Use Runtime.instance() to get it after creation.
• The Runtime never calls provider code at init time — providers are lazy.
• Shutdown is always clean: pending tasks are cancelled before the loop exits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .config import Config
from .event_bus import Event, EventBus
from .identity import Identity
from .provider_registry import ProviderKind, ProviderRegistry
from .session import Session, SessionState

logger = logging.getLogger(__name__)

_instance: Optional["Runtime"] = None


class Runtime:
    """
    Elena's Runtime — the single authoritative owner of her core state.

    Attributes (public, read-only)
    ──────────────────────────────
    config      — typed configuration snapshot
    identity    — Elena's immutable identity
    event_bus   — async publish/subscribe event bus
    session     — the current active conversation session
    providers   — registry of reasoning/speech/storage providers
    started_at  — float epoch time when start() completed, or 0
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config:    Config           = config or Config.load()
        self.identity:  Identity         = Identity.instance()
        self.event_bus: EventBus         = EventBus()
        self.providers: ProviderRegistry = ProviderRegistry()

        self.session:   Session          = Session(owner_id="mr_smart")
        self.started_at: float           = 0.0
        self._running:  bool             = False
        self._tasks:    list             = []

    # ── Singleton factory ──────────────────────────────────────────────────────

    @classmethod
    def create(cls, config: Optional[Config] = None) -> "Runtime":
        """
        Create (and cache) the singleton Runtime instance.

        Call this once at application startup.  Subsequent calls return the
        existing instance — the ``config`` argument is ignored after the first
        call (use ``Runtime.instance()`` instead).
        """
        global _instance
        if _instance is None:
            _instance = cls(config)
            logger.info("runtime: Elena Runtime created")
        return _instance

    @classmethod
    def instance(cls) -> "Runtime":
        """
        Return the singleton Runtime.

        Raises ``RuntimeError`` if ``create()`` has not been called yet.
        """
        if _instance is None:
            raise RuntimeError(
                "Runtime has not been created yet. "
                "Call Runtime.create() at application startup."
            )
        return _instance

    @classmethod
    def reset(cls) -> None:
        """
        Destroy the singleton.  Intended for tests only.

        Does NOT call stop() — call that first if the runtime is running.
        """
        global _instance
        _instance = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the Runtime.

        Sequence:
          1. Mark running
          2. Start the active conversation session
          3. Fire SESSION_STARTED on the event bus
          4. Schedule any background maintenance tasks
        """
        if self._running:
            logger.warning("runtime: start() called but already running")
            return

        logger.info(
            "runtime: starting (identity=%s, provider=%s)",
            self.identity.name,
            self.config.active_provider,
        )

        self._running   = True
        self.started_at = time.time()

        # Start a fresh session
        self.session.start()

        # Announce startup
        await self.event_bus.publish(Event(
            type=EventBus.SESSION_STARTED,
            source="runtime",
            data={
                "session_id":    self.session.session_id,
                "identity":      self.identity.name,
                "active_provider": self.config.active_provider,
            },
        ))

        logger.info("runtime: Elena is online (session=%s)", self.session.session_id[:8])

    async def stop(self) -> None:
        """
        Gracefully shut down the Runtime.

        Sequence:
          1. Fire SHUTDOWN on the event bus (subscribers can flush / persist)
          2. End the current session
          3. Cancel background tasks
          4. Mark not running
        """
        if not self._running:
            return

        logger.info("runtime: shutting down")

        await self.event_bus.publish(Event(
            type=EventBus.SHUTDOWN,
            source="runtime",
            data={"session_id": self.session.session_id},
        ))

        self.session.end()

        # Cancel any background tasks registered via _schedule_task
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        self._running   = False
        self.started_at = 0.0
        logger.info("runtime: shutdown complete")

    # ── Session management ────────────────────────────────────────────────────

    def new_session(self) -> Session:
        """
        Replace the current session with a fresh one.

        The old session is ended cleanly; the new one starts immediately.
        An event is published so subscribers (e.g. memory) can persist the
        outgoing session before it is discarded.
        """
        old = self.session
        old.end()
        self.event_bus.publish_nowait(Event(
            type=EventBus.SESSION_ENDED,
            source="runtime",
            data=old.to_dict(),
        ))

        self.session = Session(owner_id="mr_smart")
        self.session.start()
        self.event_bus.publish_nowait(Event(
            type=EventBus.SESSION_STARTED,
            source="runtime",
            data={"session_id": self.session.session_id},
        ))
        logger.info(
            "runtime: new session started (old=%s, new=%s)",
            old.session_id[:8], self.session.session_id[:8],
        )
        return self.session

    # ── Provider convenience ──────────────────────────────────────────────────

    def register_provider(
        self,
        kind: ProviderKind,
        name: str,
        provider: object,
        *,
        set_active: bool = False,
    ) -> None:
        """Register a service provider and optionally make it active."""
        self.providers.register(kind, name, provider, set_active=set_active)
        self.event_bus.publish_nowait(Event(
            type=EventBus.PROVIDER_CHANGED,
            source="runtime",
            data={
                "kind":   kind.name,
                "name":   name,
                "action": "registered",
                "active": self.providers.get_active_name(kind),
            },
        ))

    def activate_provider(self, kind: ProviderKind, name: str) -> None:
        """Switch the active provider for ``kind`` to ``name``."""
        self.providers.set_active(kind, name)
        self.event_bus.publish_nowait(Event(
            type=EventBus.PROVIDER_CHANGED,
            source="runtime",
            data={
                "kind":   kind.name,
                "name":   name,
                "action": "activated",
            },
        ))
        logger.info("runtime: %s provider → %s", kind.name, name)

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime(self) -> float:
        """Seconds since start(), or 0 if not running."""
        if not self._running or self.started_at == 0:
            return 0.0
        return time.time() - self.started_at

    def status(self) -> dict:
        """
        Return a JSON-serialisable status snapshot.

        Used by the /healthz and /status API endpoints.
        """
        return {
            "identity":        self.identity.name,
            "os":              self.identity.os_name,
            "running":         self._running,
            "uptime_seconds":  round(self.uptime, 1),
            "session":         self.session.to_dict(),
            "providers":       self.providers.active_names(),
            "event_handlers":  self.event_bus.handler_count(),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _schedule_task(self, coro) -> asyncio.Task:
        """
        Schedule a background coroutine and track it for clean cancellation
        at shutdown.
        """
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        task.add_done_callback(lambda t: self._tasks.remove(t) if t in self._tasks else None)
        return task

    def __repr__(self) -> str:
        return (
            f"Runtime(identity={self.identity.name!r}, "
            f"running={self._running}, uptime={self.uptime:.1f}s)"
        )
