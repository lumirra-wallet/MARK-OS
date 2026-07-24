"""
conversation_session.py — Persistent semantic state for Elena's voice conversations.

Tracks what the conversation is actually *about* across turns, so Elena always
knows the context — enabling natural reference resolution and emotional adaptation.

Features implemented here:
  Feature 5  — Persistent Conversation State
  Feature 9  — Real Conversation Memory (reference resolution)
  Feature 10 — Emotional Adaptation
  Feature 11 — Background Thinking (triggers are in api.py)

State tracked:
  current_topic     — what we're discussing right now
  previous_topic    — what we were discussing before ("go back to that")
  open_questions    — things Elena asked that haven't been answered
  owner_emotion     — detected: neutral | frustrated | excited | tired | focused
  current_task      — active engineering task Elena is working on
  topic_entities    — key named entities (files, tools, concepts) in scope
  turn_count        — turns this session (resets on server restart)
  background_facts  — facts extracted post-turn by background reflection
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


# ── Emotion detection — keyword / pattern based, no LLM, < 1ms ───────────────

_FRUSTRATED_RE = re.compile(
    r"\b(frustrated?|annoying|broken|doesn'?t work|not working|why isn'?t|"
    r"still broken|keeps? (failing?|breaking?)|ugh+|argh|damn|this is wrong|"
    r"fix (this|it) (now|please|already)?|wrong again|keeps? happening|"
    r"not (again|this)|how many times|come on|seriously|ridiculous|"
    r"nothing works?|can'?t (get|make)|stop (doing|saying))\b",
    re.IGNORECASE,
)
_EXCITED_RE = re.compile(
    r"\b(amazing|awesome|perfect|exactly|love it|great|fantastic|yes!*|"
    r"that'?s it|nailed it|brilliant|works?!*|finally|let'?s go|build it|"
    r"ship it|this is great|this works?|works? perfectly|let'?s do it|"
    r"incredible|so good|oh wow|nice)\b",
    re.IGNORECASE,
)
_TIRED_RE = re.compile(
    r"\b(tired|exhausted|done for (today|now)|let'?s stop|enough for today|"
    r"that'?s enough|keep it simple|not now|maybe later|wrap up|"
    r"call it a day|simplify|just (do it|make it work)|too complicated|"
    r"i'?m done|forget it)\b",
    re.IGNORECASE,
)
_FOCUSED_RE = re.compile(
    r"\b(let'?s (focus|work on|build|fix|write|check|look at|add|remove|"
    r"update|debug|test|run|deploy|continue|implement)|working on|"
    r"implement|need to|want to (build|add|fix|check|create)|"
    r"back to|continue with|pick up where)\b",
    re.IGNORECASE,
)

# ── Topic extraction — what is this turn about? ───────────────────────────────

_TOPIC_PATTERNS = [
    # "build / create / implement X"
    (re.compile(
        r"\b(?:build|building|create|creating|implement(?:ing)?|add(?:ing)?|write|writing)\s+"
        r"(?:a |an |the )?(.+?)(?:\s*\.|$|\s+so\s|\s+that\s|\s+which\s|\s+to\s|\s+for\s)",
        re.IGNORECASE,
    ), 1),
    # "fix / debug / investigate X"
    (re.compile(
        r"\b(?:fix(?:ing)?|debug(?:ging)?|investigat(?:e|ing)|solve|repair(?:ing)?)\s+"
        r"(?:the |a |an )?(.+?)(?:\s*\.|$|\s+so\s|\s+that\s|\s+in\s)",
        re.IGNORECASE,
    ), 1),
    # "working on X"
    (re.compile(r"\bworking on\s+(?:the |a |an )?(.+?)(?:\s*\.|$)", re.IGNORECASE), 1),
    # "about X"
    (re.compile(r"\babout\s+(?:the |a |an )?(.+?)(?:\s*\.|$)", re.IGNORECASE), 1),
    # "the X pipeline / system / module / api / server / app"
    (re.compile(
        r"\bthe\s+(\w[\w\s]{2,30}(?:pipeline|system|module|api|server|app|engine|"
        r"component|service|interface|layer|feature|function|class|file))\b",
        re.IGNORECASE,
    ), 1),
]

# Proper-noun extractor (capitalised tokens, at least 3 chars, not sentence starters)
_PROPER_NOUN_RE = re.compile(r"(?<!\. )(?<!\? )(?<!\! )\b([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,})*)\b")

# Vague pronoun / reference detector
_VAGUE_RE = re.compile(
    r"^\s*(?:make|fix|change|update|improve|check|test|debug|add|remove|"
    r"delete|edit|refactor|optimize|speed up|slow down|reset|restart)\s+"
    r"(?:it|this|that|the (?:thing|project|code|file|app|system|pipeline|"
    r"api|server|backend|frontend|feature|bug|issue|error|problem))\b",
    re.IGNORECASE,
)

# Skip common false-positive proper nouns
_SKIP_NOUNS = frozenset({
    "I", "Elena", "Mr", "Smart", "You", "The", "A", "An", "This", "That",
    "He", "She", "We", "They", "It", "Is", "Are", "Was", "Were",
})


def detect_emotion(text: str) -> str:
    """Detect owner emotional state from transcript text.

    Returns one of: 'frustrated' | 'excited' | 'tired' | 'focused' | 'neutral'
    Priority: frustrated > tired > excited > focused > neutral.
    """
    if _FRUSTRATED_RE.search(text):
        return "frustrated"
    if _TIRED_RE.search(text):
        return "tired"
    if _EXCITED_RE.search(text):
        return "excited"
    if _FOCUSED_RE.search(text):
        return "focused"
    return "neutral"


def extract_topic(text: str) -> str:
    """Extract the main topic from a sentence. Returns '' if nothing found."""
    for pattern, grp in _TOPIC_PATTERNS:
        m = pattern.search(text)
        if m:
            candidate = m.group(grp).strip().rstrip(".!?,;").strip()
            # Reasonable length, not just a pronoun
            if 4 < len(candidate) < 80 and candidate.lower() not in {"it", "this", "that"}:
                return candidate
    return ""


def extract_proper_nouns(text: str) -> list[str]:
    """Return capitalised proper-noun candidates from text."""
    return [
        m.group(1) for m in _PROPER_NOUN_RE.finditer(text)
        if m.group(1) not in _SKIP_NOUNS
    ]


def resolve_references(text: str, current_topic: str, topic_entities: list[str]) -> str:
    """Annotate vague references so the LLM understands them without asking.

    'Make it faster' with topic='voice pipeline' →
    'Make it faster [topic: voice pipeline]'

    The annotation is injected into the LLM *user message* only — never shown
    to the owner. Keeps the conversation natural on both sides.
    """
    if not current_topic:
        return text
    # Only annotate if the message is short AND references something vague
    words = text.strip().split()
    if len(words) > 12:
        return text
    if not _VAGUE_RE.search(text):
        # Still annotate very short messages that likely reference the topic
        if len(words) <= 5 and re.search(r"\b(it|this|that)\b", text, re.IGNORECASE):
            return f"{text}  [topic: {current_topic}]"
        return text
    return f"{text}  [topic: {current_topic}]"


# ── Emotional response guidelines ─────────────────────────────────────────────

_EMOTION_RESPONSE_GUIDE: dict[str, str] = {
    "frustrated": (
        "The owner sounds frustrated. Acknowledge it briefly, then solve the "
        "problem directly. Don't over-explain. No fluff. 1-2 sentences max."
    ),
    "excited": (
        "The owner is excited and energised. Match that energy — be crisp, "
        "positive, and decisive. Build on their momentum."
    ),
    "tired": (
        "The owner sounds tired or wants simplicity. Keep it minimal. "
        "One clear sentence. Offer to continue later if appropriate."
    ),
    "focused": (
        "The owner is in work mode. Be direct and technical. "
        "Skip pleasantries — answer the question and ask what's next."
    ),
    "neutral": "",
}


def get_emotion_guidance(emotion: str) -> str:
    """Return the emotional adaptation instruction for Elena's system prompt."""
    return _EMOTION_RESPONSE_GUIDE.get(emotion, "")


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class ConversationState:
    """Semantic state of the current voice session."""
    current_topic:    str        = ""
    previous_topic:   str        = ""
    open_questions:   list[str]  = field(default_factory=list)
    owner_emotion:    str        = "neutral"
    current_task:     str        = ""
    topic_entities:   list[str]  = field(default_factory=list)
    background_facts: list[str]  = field(default_factory=list)
    turn_count:       int        = 0
    session_start:    float      = field(default_factory=time.monotonic)
    last_update:      float      = field(default_factory=time.monotonic)


# ── Singleton manager ─────────────────────────────────────────────────────────

class _ConversationSessionManager:
    """Process-wide voice session state. Thread-safe."""

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._state = ConversationState()

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_state(self) -> ConversationState:
        with self._lock:
            return self._state

    # ── Write: called after each user utterance ───────────────────────────────

    def on_utterance(self, text: str) -> ConversationState:
        """Update state from what the owner just said. Returns updated state."""
        with self._lock:
            s = self._state
            s.turn_count  += 1
            s.last_update  = time.monotonic()

            # Emotion
            emotion = detect_emotion(text)
            if emotion != "neutral":
                s.owner_emotion = emotion
            elif s.turn_count > 3:
                # After a few turns of silence on emotion, decay back to neutral
                s.owner_emotion = "neutral"

            # Topic
            new_topic = extract_topic(text)
            if new_topic and new_topic.lower() != s.current_topic.lower():
                if s.current_topic:
                    s.previous_topic = s.current_topic
                s.current_topic = new_topic

            # Entities (cap at 20, newest first)
            for noun in extract_proper_nouns(text):
                if noun not in s.topic_entities:
                    s.topic_entities.insert(0, noun)
            s.topic_entities = s.topic_entities[:20]

            return s

    def on_reply(self, reply_text: str) -> None:
        """Update state from Elena's reply (track open questions she asked)."""
        with self._lock:
            s = self._state
            questions = [q.strip() for q in re.findall(r"[^.!?]*\?", reply_text)]
            for q in questions:
                if len(q) > 12 and q not in s.open_questions:
                    s.open_questions.insert(0, q)
            s.open_questions = s.open_questions[:5]

    def on_user_answered(self) -> None:
        """Clear open questions once the owner responds (they answered)."""
        with self._lock:
            self._state.open_questions.clear()

    def set_task(self, task: str) -> None:
        """Set the current active engineering task."""
        with self._lock:
            self._state.current_task = task

    def add_background_fact(self, fact: str) -> None:
        """Add a fact extracted by background reflection."""
        with self._lock:
            s = self._state
            if fact and fact not in s.background_facts:
                s.background_facts.insert(0, fact)
            s.background_facts = s.background_facts[:20]

    def reset(self) -> None:
        """Reset session state (new session / server restart)."""
        with self._lock:
            self._state = ConversationState()

    # ── Prompt helpers ────────────────────────────────────────────────────────

    def resolve(self, text: str) -> str:
        """Resolve vague references in *text* using current session context."""
        with self._lock:
            return resolve_references(
                text, self._state.current_topic, self._state.topic_entities
            )

    def to_prompt_block(self) -> str:
        """Format session state as a block to inject into Elena's system prompt."""
        with self._lock:
            s = self._state
        parts: list[str] = []

        if s.current_topic:
            parts.append(f"Current topic: {s.current_topic}")
        if s.previous_topic:
            parts.append(f"Previous topic: {s.previous_topic} (may be referenced as 'that')")
        if s.current_task:
            parts.append(f"Active task: {s.current_task}")
        if s.open_questions:
            parts.append(f"Open question you asked: \"{s.open_questions[0]}\"")
        if s.topic_entities:
            parts.append(f"Entities in scope: {', '.join(s.topic_entities[:8])}")
        if s.background_facts:
            parts.append("Background facts extracted from this session:")
            for f in s.background_facts[:4]:
                parts.append(f"  • {f}")

        emotion_guide = get_emotion_guidance(s.owner_emotion)

        if not parts and not emotion_guide:
            return ""

        block = "SESSION STATE (use this to resolve references and adapt tone):\n"
        if parts:
            block += "\n".join(f"  {p}" for p in parts)
        if emotion_guide:
            block += ("\n\n" if parts else "") + f"EMOTIONAL ADAPTATION: {emotion_guide}"
        return block

    def to_dict(self) -> dict:
        """Serialize for WebSocket broadcast to the dashboard."""
        with self._lock:
            s = self._state
        return {
            "current_topic":   s.current_topic,
            "previous_topic":  s.previous_topic,
            "open_questions":  s.open_questions,
            "owner_emotion":   s.owner_emotion,
            "current_task":    s.current_task,
            "topic_entities":  s.topic_entities[:8],
            "background_facts": s.background_facts[:5],
            "turn_count":      s.turn_count,
        }


# Process-wide singleton
conversation_session = _ConversationSessionManager()
