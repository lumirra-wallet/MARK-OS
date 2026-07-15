"""
ConversationContext — Milestone 5, Part 6.

Tracks everything about an ongoing conversation that `PromptBuilder` needs
to assemble a prompt, and that a future compression/summarization pass
(explicitly out of scope for Milestone 5) will eventually operate on:
message history, running summaries, active goals/task, memory references,
tool outputs, timestamps, and a token estimate.

Deliberately provider-agnostic and dependency-free: this module never
imports anything from `smartagent.models.providers` or
`smartagent.brain` — it is a plain data container that `PromptBuilder`
reads and `ModelManager`/the Brain integration populates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _estimate_tokens(text: str) -> int:
    """Rough, provider-agnostic token estimate: ~4 characters per token."""
    return max(0, len(text) // 4)


@dataclass
class ConversationTurn:
    """A single exchange in the conversation history."""

    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    timestamp: str = field(default_factory=_now)

    def token_estimate(self) -> int:
        return _estimate_tokens(self.content)


@dataclass
class ConversationContext:
    """
    Accumulated state for one conversation, independent of any provider.

    Attributes:
        history: Ordered list of every turn seen so far (oldest first).
        summaries: Running summaries of older history — populated by a
            future compression pass (Part 6 explicitly defers this; the
            field exists now so `PromptBuilder` has a stable place to read
            summaries from once that pass exists).
        active_goals: Free-text descriptions of goals currently in play
            (e.g. sourced from `GoalManager`), for `PromptBuilder` to fold
            into the system/context section.
        active_task: The single task currently being worked on, if any.
        memory_refs: Snippets recalled from `MemoryManager` relevant to the
            current turn.
        tool_outputs: Recent tool results relevant to the current turn,
            most recent last.
        created_at / updated_at: ISO-8601 UTC timestamps.
    """

    history: list[ConversationTurn] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    active_goals: list[str] = field(default_factory=list)
    active_task: str | None = None
    memory_refs: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add_turn(self, role: str, content: str) -> ConversationTurn:
        """Append a new turn to `history` and return it."""
        turn = ConversationTurn(role=role, content=content)
        self.history.append(turn)
        self.updated_at = _now()
        return turn

    def add_memory_ref(self, snippet: str) -> None:
        """Record a memory snippet relevant to the current turn."""
        self.memory_refs.append(snippet)
        self.updated_at = _now()

    def add_tool_output(self, output: str) -> None:
        """Record a tool result relevant to the current turn."""
        self.tool_outputs.append(output)
        self.updated_at = _now()

    def add_summary(self, summary: str) -> None:
        """
        Record a summary of older history.

        Milestone 5 does not implement automatic compression — callers
        (or a future `ContextCompressor`) decide when to summarize and
        call this directly; `ConversationContext` itself never trims
        `history`.
        """
        self.summaries.append(summary)
        self.updated_at = _now()

    def set_active_task(self, task: str | None) -> None:
        self.active_task = task
        self.updated_at = _now()

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def recent(self, limit: int = 10) -> list[ConversationTurn]:
        """The most recent `limit` turns, oldest first."""
        if limit <= 0:
            return []
        return self.history[-limit:]

    def token_estimate(self) -> int:
        """
        Rough total token estimate across history, summaries, and refs.

        Deliberately simple (character-count heuristic) rather than a real
        tokenizer — Milestone 5 has no provider-specific tokenizer
        dependency, and this is only meant to give `PromptBuilder`/
        `ModelManager` a ballpark for logging and future compression
        triggers, not an exact count.
        """
        total = sum(turn.token_estimate() for turn in self.history)
        total += sum(_estimate_tokens(s) for s in self.summaries)
        total += sum(_estimate_tokens(r) for r in self.memory_refs)
        total += sum(_estimate_tokens(t) for t in self.tool_outputs)
        return total

    def to_dict(self) -> dict:
        """Plain-dict snapshot, useful for logging/statistics without exposing dataclass internals."""
        return {
            "turns": len(self.history),
            "summaries": len(self.summaries),
            "active_goals": list(self.active_goals),
            "active_task": self.active_task,
            "memory_refs": len(self.memory_refs),
            "tool_outputs": len(self.tool_outputs),
            "token_estimate": self.token_estimate(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
