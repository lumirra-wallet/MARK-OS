"""
EmotionalStateEngine — context-derived emotional state for MARK.

States are determined by reasoning outcomes, not randomly chosen.
Each transition has a traceable cause so the dashboard can show honest context.

States:
  neutral    — default; nothing notable happened
  curious    — learning something new (knowledge created)
  focused    — working on a difficult task
  satisfied  — successfully helped the owner
  uncertain  — missing information; needs clarification
  frustrated — repeated failures in a short window

The engine is a lightweight module-level singleton; it never owns threads,
never auto-transitions on a timer, and never fabricates state.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# How long (seconds) a non-neutral state persists before decaying back to neutral.
_STATE_TTL = 120.0

# Consecutive failures needed to reach "frustrated"
_FRUSTRATION_THRESHOLD = 3


class EmotionalStateEngine:
    """MARK's emotional state, derived from real reasoning events."""

    def __init__(self) -> None:
        self._state: str = "neutral"
        self._reason: str = ""
        self._state_set_at: float = 0.0
        self._consecutive_failures: int = 0

    # ── Transition methods — each called by a real event ─────────────────────

    def on_knowledge_created(self, concept: str = "") -> str:
        """Learning something new → curious."""
        return self._set("curious", f"learned: {concept}" if concept else "learned something new")

    def on_complex_task_started(self) -> str:
        """Tackling a difficult multi-step task → focused."""
        return self._set("focused", "working on a complex task")

    def on_success(self, goal: str = "") -> str:
        """Successfully helped the owner → satisfied."""
        self._consecutive_failures = 0
        return self._set("satisfied", f"completed: {goal[:60]}" if goal else "task completed successfully")

    def on_needs_clarification(self) -> str:
        """Not enough information to proceed → uncertain."""
        return self._set("uncertain", "missing information to proceed")

    def on_failure(self, reason: str = "") -> str:
        """A task failed. Repeated failures → frustrated."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= _FRUSTRATION_THRESHOLD:
            return self._set("frustrated", reason or "repeated failures")
        return self._set("neutral", "")

    def on_voice_listening(self) -> str:
        """Owner is speaking — MARK is paying attention."""
        # Don't override a strong emotional state just because the mic opened.
        if self._state in ("neutral", "satisfied"):
            return self._set("neutral", "listening")
        return self._state

    def decay_if_stale(self) -> tuple[str, bool]:
        """
        If the current state has been held longer than _STATE_TTL, decay to neutral.
        Returns (current_state, changed).
        """
        if self._state == "neutral":
            return self._state, False
        if time.monotonic() - self._state_set_at > _STATE_TTL:
            prev = self._state
            self._state = "neutral"
            self._reason = ""
            logger.debug("EmotionalState: decayed %r → neutral (TTL)", prev)
            return "neutral", True
        return self._state, False

    # ── Read ─────────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        self.decay_if_stale()
        return self._state

    @property
    def reason(self) -> str:
        return self._reason

    # ── Internal ─────────────────────────────────────────────────────────────

    def _set(self, state: str, reason: str) -> str:
        prev = self._state
        self._state = state
        self._reason = reason
        self._state_set_at = time.monotonic()
        if prev != state:
            logger.debug("EmotionalState: %r → %r  reason=%r", prev, state, reason)
        return state


# Module-level singleton — shared across the whole server process, same as
# MARK himself (one mind, one emotional state).
emotional_state_engine = EmotionalStateEngine()
