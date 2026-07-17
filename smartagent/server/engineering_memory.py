"""
Engineering memory — session-scoped tracking of goals, milestones, and blockers.

A single EngineeringMemory instance lives in api.py for the duration of the
server process.  It is updated by the agent loop and queried by the dashboard
via the /memory endpoint and the MemoryUpdated WebSocket event.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Milestone:
    text: str
    completed: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class Blocker:
    text: str
    resolved: bool = False
    timestamp: float = field(default_factory=time.time)


class EngineeringMemory:
    """
    Lightweight session memory that survives across multiple runs.

    Thread-safe for read/write from worker threads.
    """

    def __init__(self) -> None:
        self.current_goal:  str           = ""
        self.context:       str           = ""           # project type, workspace path, etc.
        self.milestones:    list[Milestone] = []
        self.blockers:      list[Blocker]   = []
        self.session_start: float = time.time()
        self._last_updated: float = time.time()

    # ── Mutations ─────────────────────────────────────────────────────────────

    def set_goal(self, goal: str) -> None:
        self.current_goal = goal
        self._last_updated = time.time()
        logger.debug("EngineeringMemory: goal = %r", goal[:60])

    def set_context(self, context: str) -> None:
        self.context = context
        self._last_updated = time.time()

    def add_milestone(self, text: str, completed: bool = False) -> None:
        # Avoid duplicates
        for m in self.milestones:
            if m.text == text:
                m.completed = completed
                self._last_updated = time.time()
                return
        self.milestones.append(Milestone(text=text, completed=completed))
        self._last_updated = time.time()

    def complete_milestone(self, text: str) -> None:
        for m in self.milestones:
            if m.text == text or text in m.text:
                m.completed = True
                self._last_updated = time.time()
                return

    def complete_last_milestone(self) -> None:
        for m in reversed(self.milestones):
            if not m.completed:
                m.completed = True
                self._last_updated = time.time()
                return

    def add_blocker(self, text: str) -> None:
        for b in self.blockers:
            if b.text == text:
                return
        self.blockers.append(Blocker(text=text))
        self._last_updated = time.time()

    def resolve_blockers(self) -> None:
        for b in self.blockers:
            b.resolved = True
        self._last_updated = time.time()

    def clear(self) -> None:
        self.current_goal  = ""
        self.context       = ""
        self.milestones    = []
        self.blockers      = []
        self._last_updated = time.time()

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        import time as _time
        return {
            "current_goal":   self.current_goal,
            "context":        self.context,
            "milestones": [
                {"text": m.text, "completed": m.completed}
                for m in self.milestones[-20:]   # cap to last 20
            ],
            "blockers": [
                {"text": b.text, "resolved": b.resolved}
                for b in self.blockers
                if not b.resolved
            ],
            "session_elapsed": round(_time.time() - self.session_start),
            "last_updated":    round(_time.time() - self._last_updated),
        }

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_updated


# Module-level singleton — one memory per server process.
engineering_memory = EngineeringMemory()
