"""
MARK server — Permission gate.

PermissionGate pauses execution (in a background asyncio.to_thread call)
until a human approves or denies a destructive operation via the dashboard.

Flow:
  1. Server code calls ``gate.request(operation, path, diff)``.
  2. A ``PermissionRequested`` event is published on the EventBus.
  3. The WebSocket broadcaster pushes it to all dashboard clients.
  4. A client calls ``POST /approve`` or ``POST /deny``.
  5. The api handler calls ``gate.approve(request_id)`` or ``gate.deny(...)``.
  6. The asyncio.Event is set, ``wait_for_approval()`` returns, and execution
     resumes (or is aborted, depending on the result).

Phase 4 (Permission UI) will wire the gate directly into FileEditor so every
file write triggers a real approval flow.  For Phase 1 the gate exists and
is API-accessible but is not yet hooked into the write path.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.brain.events import EventBus

from smartagent.server.events import ServerEvents

logger = logging.getLogger(__name__)


APPROVED = "approved"
DENIED   = "denied"
PENDING  = "pending"


@dataclass
class PendingPermission:
    """One pending permission request."""

    request_id: str
    operation: str       # "create" | "modify" | "delete" | "shell" | "git" | "tool"
    path: str
    diff: str = ""
    result: str = PENDING

    def __post_init__(self) -> None:
        # asyncio.Event must be created inside the event loop; we create it
        # lazily on first access so this dataclass is safely constructable
        # outside coroutines (e.g. in sync helper code / tests).
        self._event: asyncio.Event | None = None

    @property
    def event(self) -> asyncio.Event:
        if self._event is None:
            self._event = asyncio.Event()
        return self._event


class PermissionGate:
    """
    Async gate that pauses MARK execution until a permission is resolved.

    All methods are safe to call from sync or async code.  ``wait_for_approval``
    must be awaited inside an async context (it is designed to be called from
    ``asyncio.to_thread`` via an asyncio-friendly shim — see ``request_async``).
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingPermission] = {}
        self._always_approved: set[str] = set()  # operations always approved

    # ------------------------------------------------------------------
    # Creating requests
    # ------------------------------------------------------------------

    def create_request(
        self,
        operation: str,
        path: str,
        diff: str = "",
        event_bus: "EventBus | None" = None,
    ) -> PendingPermission:
        """
        Create a new permission request, optionally publishing a
        ``PermissionRequested`` event on *event_bus*.
        """
        req_id = str(uuid.uuid4())[:8]
        perm = PendingPermission(request_id=req_id, operation=operation, path=path, diff=diff)
        self._pending[req_id] = perm

        if event_bus is not None:
            try:
                event_bus.publish(
                    ServerEvents.PERMISSION_REQUESTED,
                    request_id=req_id,
                    operation=operation,
                    path=path,
                    diff=diff[:2000],       # truncate large diffs for the event payload
                )
            except Exception:
                pass

        logger.info("PermissionGate: request created  id=%s  op=%s  path=%s", req_id, operation, path)
        return perm

    # ------------------------------------------------------------------
    # Resolving requests
    # ------------------------------------------------------------------

    def approve(self, request_id: str = "", always: bool = False) -> bool:
        """
        Approve a pending request.  If *request_id* is empty, approve the
        most recently created pending request.

        Returns ``True`` when a request was found and resolved.
        """
        perm = self._find(request_id)
        if perm is None:
            return False
        perm.result = APPROVED
        perm.event.set()
        if always:
            self._always_approved.add(perm.operation)
        logger.info("PermissionGate: approved  id=%s", perm.request_id)
        return True

    def deny(self, request_id: str = "", reason: str = "") -> bool:
        """Deny a pending request."""
        perm = self._find(request_id)
        if perm is None:
            return False
        perm.result = DENIED
        perm.event.set()
        logger.info("PermissionGate: denied  id=%s  reason=%r", perm.request_id, reason)
        return True

    # ------------------------------------------------------------------
    # Async waiting
    # ------------------------------------------------------------------

    async def wait_for_approval(
        self,
        perm: PendingPermission,
        timeout: float = 300.0,
    ) -> str:
        """
        Await the resolution of *perm*.

        Returns the result string: ``"approved"`` or ``"denied"``.
        Times out after *timeout* seconds and returns ``"denied"``.
        """
        # Check always-approved shortcut first.
        if perm.operation in self._always_approved:
            perm.result = APPROVED
            perm.event.set()
            return APPROVED

        try:
            await asyncio.wait_for(perm.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            perm.result = DENIED
        return perm.result

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def list_pending(self) -> list[PendingPermission]:
        """Return all unresolved permission requests, oldest first."""
        return [p for p in self._pending.values() if p.result == PENDING]

    def get(self, request_id: str) -> PendingPermission | None:
        return self._pending.get(request_id)

    def is_always_approved(self, operation: str) -> bool:
        return operation in self._always_approved

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find(self, request_id: str) -> PendingPermission | None:
        if request_id:
            return self._pending.get(request_id)
        # Latest pending
        for perm in reversed(list(self._pending.values())):
            if perm.result == PENDING:
                return perm
        return None


# Module-level singleton
permission_gate = PermissionGate()
