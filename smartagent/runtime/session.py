"""
session.py — Elena's conversation session management.

A Session is the container for one continuous conversation between Elena and
Mr. Smart.  It tracks:

  • Turn history (speaker, text, timestamp)
  • Conversation phase (idle / listening / thinking / speaking)
  • User's current goal (inferred from recent turns)
  • Utterance classification for the most recent user input

Sessions are owned by the Runtime.  Providers (speech, reasoning) receive
a Session reference so they can read context — they never write to it
directly; they call Session methods.

Usage
─────
    session = Session(session_id="abc123")
    session.start()

    session.add_user_turn("Hello Elena.")
    session.set_state(SessionState.THINKING)
    session.add_elena_turn("Hello, Mr. Smart.")
    session.set_state(SessionState.IDLE)

    # Classify the latest user utterance for context-aware responses
    cls = session.classify_last_utterance()
    # → UtteranceKind.GREETING
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class SessionState(Enum):
    """
    The phase Elena is currently in within this session.

    IDLE       — waiting; no active conversation
    LISTENING  — mic is open, waiting for user to speak
    DETECTING  — VAD detected speech onset; accumulating audio
    THINKING   — audio received; brain is reasoning
    SPEAKING   — Elena's TTS audio is streaming to the speaker
    INTERRUPTED— Elena was barged in on; discarding current TTS
    """
    IDLE        = auto()
    LISTENING   = auto()
    DETECTING   = auto()
    THINKING    = auto()
    SPEAKING    = auto()
    INTERRUPTED = auto()


class UtteranceKind(Enum):
    """
    Classification of the most recent user utterance.

    Drives the Conversation Executive so Elena never treats
    "Okay." as a new topic.
    """
    CONTINUATION  = auto()   # "Continue.", "Go on.", "And then?"
    CONFIRMATION  = auto()   # "Yes.", "Right.", "Exactly.", "Okay."
    CORRECTION    = auto()   # "No, I meant…", "Actually…"
    INTERRUPT     = auto()   # Barged in mid-sentence
    FOLLOW_UP     = auto()   # Question building on the last exchange
    TOPIC_CHANGE  = auto()   # Clearly new subject
    COMMAND       = auto()   # Imperative: "Stop.", "Cancel.", "Open…"
    GREETING      = auto()   # "Hey Elena.", "Good morning."
    FAREWELL      = auto()   # "Bye.", "That's all."
    QUESTION      = auto()   # Standalone question
    STATEMENT     = auto()   # General statement (fallback)


# ── Turn dataclass ────────────────────────────────────────────────────────────

@dataclass
class Turn:
    """One spoken exchange (either user or Elena)."""
    role:       str           # "user" | "elena"
    text:       str
    timestamp:  float = field(default_factory=time.time)
    turn_id:    str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata:   Dict  = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role":      self.role,
            "text":      self.text,
            "timestamp": self.timestamp,
            "turn_id":   self.turn_id,
        }


# ── Session ───────────────────────────────────────────────────────────────────

# Short utterances that indicate continuation, confirmation, or correction.
_CONTINUATION_PHRASES = {
    "continue", "go on", "and", "then", "so", "keep going",
    "go ahead", "proceed", "carry on", "yeah go on",
}
_CONFIRMATION_PHRASES = {
    "yes", "yeah", "yep", "yup", "right", "exactly", "correct",
    "sure", "okay", "ok", "alright", "fine", "understood",
    "got it", "perfect", "great", "good", "agreed", "absolutely",
}
_FAREWELL_PHRASES = {
    "bye", "goodbye", "see you", "that's all", "that's it",
    "we're done", "end", "close", "exit", "stop", "quit",
}
_GREETING_PHRASES = {
    "hello", "hey", "hi", "good morning", "good afternoon",
    "good evening", "howdy", "morning", "afternoon",
    "elena", "hey elena", "hi elena",
}


class Session:
    """
    One continuous conversation session between Elena and her owner.

    The Runtime creates and owns Sessions.  Providers receive a reference
    and read context through the public API; they never mutate state directly.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        owner_id: str = "mr_smart",
    ) -> None:
        self.session_id:   str          = session_id or str(uuid.uuid4())
        self.owner_id:     str          = owner_id
        self.state:        SessionState = SessionState.IDLE
        self.started_at:   float        = 0.0
        self.last_active:  float        = 0.0

        self._turns:        List[Turn]  = []
        self._current_goal: str         = ""
        self._last_kind:    Optional[UtteranceKind] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Mark the session as active."""
        self.started_at  = time.time()
        self.last_active = self.started_at
        self.state       = SessionState.LISTENING

    def end(self) -> None:
        """Mark the session as ended."""
        self.state = SessionState.IDLE

    # ── State machine ─────────────────────────────────────────────────────────

    def set_state(self, state: SessionState) -> None:
        self.state       = state
        self.last_active = time.time()

    # ── Turn management ───────────────────────────────────────────────────────

    def add_user_turn(self, text: str, metadata: Optional[Dict] = None) -> Turn:
        """
        Record a user utterance.

        Automatically classifies the utterance and updates the inferred goal
        if the exchange appears to start a new topic.
        """
        turn = Turn(role="user", text=text, metadata=metadata or {})
        self._turns.append(turn)
        self.last_active = turn.timestamp
        self._last_kind  = self._classify(text)
        # Update current goal when user is clearly starting a new topic.
        if self._last_kind in (
            UtteranceKind.TOPIC_CHANGE,
            UtteranceKind.QUESTION,
            UtteranceKind.STATEMENT,
            UtteranceKind.COMMAND,
        ):
            self._current_goal = text.strip()
        return turn

    def add_elena_turn(self, text: str, metadata: Optional[Dict] = None) -> Turn:
        """Record an Elena response."""
        turn = Turn(role="elena", text=text, metadata=metadata or {})
        self._turns.append(turn)
        self.last_active = turn.timestamp
        return turn

    # ── Context access ────────────────────────────────────────────────────────

    @property
    def turns(self) -> List[Turn]:
        """All turns in this session (oldest first)."""
        return list(self._turns)

    def recent_turns(self, n: int = 6) -> List[Turn]:
        """Last ``n`` turns (oldest first)."""
        return list(self._turns[-n:])

    def recent_context(self, n: int = 6) -> str:
        """
        Human-readable recent exchange for injecting into prompts.

        Format: "user: …\\nelena: …"
        """
        return "\n".join(
            f"{t.role}: {t.text}" for t in self.recent_turns(n)
        )

    @property
    def current_goal(self) -> str:
        """The inferred current goal / topic from the conversation."""
        return self._current_goal

    @property
    def last_utterance_kind(self) -> Optional[UtteranceKind]:
        """Classification of the most recent user utterance."""
        return self._last_kind

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    @property
    def user_turn_count(self) -> int:
        return sum(1 for t in self._turns if t.role == "user")

    def is_active(self) -> bool:
        return self.state not in (SessionState.IDLE,)

    def last_elena_response(self) -> str:
        """Most recent text Elena spoke.  Empty string if Elena hasn't spoken yet."""
        for turn in reversed(self._turns):
            if turn.role == "elena":
                return turn.text
        return ""

    def last_user_utterance(self) -> str:
        """Most recent text the user spoke.  Empty string if none."""
        for turn in reversed(self._turns):
            if turn.role == "user":
                return turn.text
        return ""

    # ── Utterance classification ──────────────────────────────────────────────

    def classify_last_utterance(self) -> Optional[UtteranceKind]:
        """Return the pre-computed classification of the last user turn."""
        return self._last_kind

    @staticmethod
    def _classify(text: str) -> UtteranceKind:
        """
        Rule-based utterance classification.

        Designed to handle short conversational responses without treating
        them as new topics — the key behaviour the spec requires.

        A simple LLM-based classifier can be swapped in later while keeping
        this as the fast synchronous fallback.
        """
        cleaned = text.strip().lower().rstrip(".,!?")

        # Very short single-word / short-phrase responses
        if cleaned in _CONTINUATION_PHRASES:
            return UtteranceKind.CONTINUATION

        if cleaned in _CONFIRMATION_PHRASES:
            return UtteranceKind.CONFIRMATION

        if cleaned in _FAREWELL_PHRASES:
            return UtteranceKind.FAREWELL

        if cleaned in _GREETING_PHRASES:
            return UtteranceKind.GREETING

        # Starts with negation — likely correction
        if cleaned.startswith(("no ", "not ", "actually ", "wait ", "hmm no")):
            return UtteranceKind.CORRECTION

        # Command imperative (short, starts with verb)
        _COMMAND_STARTERS = (
            "stop", "pause", "cancel", "open", "close", "run", "start",
            "check", "show", "tell", "read", "write", "create", "delete",
            "send", "call", "find", "search", "remind",
        )
        first_word = cleaned.split()[0] if cleaned.split() else ""
        if first_word in _COMMAND_STARTERS:
            return UtteranceKind.COMMAND

        # Question detection
        if text.rstrip().endswith("?") or cleaned.startswith(
            ("what", "who", "where", "when", "why", "how", "is ", "are ",
             "do ", "does ", "can ", "could ", "would ", "will ", "should ")
        ):
            return UtteranceKind.QUESTION

        return UtteranceKind.STATEMENT

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "session_id":    self.session_id,
            "owner_id":      self.owner_id,
            "state":         self.state.name,
            "started_at":    self.started_at,
            "last_active":   self.last_active,
            "turn_count":    self.turn_count,
            "current_goal":  self._current_goal,
            "last_kind":     self._last_kind.name if self._last_kind else None,
            "recent_turns":  [t.to_dict() for t in self.recent_turns(6)],
        }

    def __repr__(self) -> str:
        return (
            f"Session(id={self.session_id[:8]!r}, "
            f"state={self.state.name}, turns={self.turn_count})"
        )
