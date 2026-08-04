"""
Conversation Session Manager.

Tracks conversation lifecycle, metrics (latency, turn count, duration), partial transcripts,
and session state persistence.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("smartagent.voice.conversation.session")


@dataclass
class ConversationTurn:
    """Represents a single conversational turn."""

    turn_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    user_transcript: str = ""
    assistant_transcript: str = ""
    tool_calls: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    duration_ms: float = 0.0


class ConversationSession:
    """
    Active live conversation session tracker.
    """

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.created_at = time.time()
        self.turns: List[ConversationTurn] = []
        self.current_turn: Optional[ConversationTurn] = None
        self.active = True

    def start_turn(self) -> ConversationTurn:
        """Start tracking a new conversation turn."""
        turn = ConversationTurn()
        self.current_turn = turn
        return turn

    def add_user_transcript(self, text: str) -> None:
        """Append partial or complete user text to current turn."""
        if not self.current_turn:
            self.start_turn()
        self.current_turn.user_transcript += text

    def add_assistant_transcript(self, text: str) -> None:
        """Append partial assistant response text to current turn."""
        if not self.current_turn:
            self.start_turn()
        self.current_turn.assistant_transcript += text

    def record_tool_call(self, tool_name: str) -> None:
        """Record an Elina tool execution in the current turn."""
        if self.current_turn:
            self.current_turn.tool_calls.append(tool_name)

    def finalize_turn(self, latency_ms: float = 0.0) -> Optional[ConversationTurn]:
        """Complete the current conversation turn."""
        if not self.current_turn:
            return None

        turn = self.current_turn
        turn.latency_ms = latency_ms
        turn.duration_ms = (time.time() - turn.timestamp) * 1000.0
        self.turns.append(turn)
        self.current_turn = None
        logger.info(
            f"Turn {turn.turn_id} complete (Latency: {turn.latency_ms:.1f}ms, "
            f"Duration: {turn.duration_ms:.1f}ms)"
        )
        return turn

    def get_summary(self) -> str:
        """Return summary metrics of the current session."""
        total_turns = len(self.turns)
        duration_sec = time.time() - self.created_at
        avg_latency = (
            sum(t.latency_ms for t in self.turns) / total_turns if total_turns > 0 else 0.0
        )
        return (
            f"Session {self.session_id[:8]} Summary: {total_turns} turns, "
            f"Duration: {duration_sec:.1f}s, Avg Latency: {avg_latency:.1f}ms"
        )
