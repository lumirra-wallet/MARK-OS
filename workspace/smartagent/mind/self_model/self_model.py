"""
`SelfModel` — the data shape behind Milestone 6, Part 2 (Self Model).

A single dynamic object answering the fixed set of questions the milestone
brief poses ("Who am I? What am I doing? What should I do next?" ...)
without re-reading any files — `SelfModelEngine` mutates one of these in
place as the rest of the Mind/Brain reports changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SelfModel:
    """
    MARK's current self-representation.

    Attributes:
        name: Mirrors `Identity.name`.
        owner: Mirrors `Identity.owner`.
        mission: Mirrors `Identity.mission`.
        current_activity: Free-text description of what MARK is doing right now.
        current_goal: The goal (if any) MARK is currently pursuing.
        tools: Ids of tools currently available (mirrors `ToolEngine.list_available()`).
        skills: Names of skills currently available (mirrors `SkillEngine.list_available()`).
        active_model: Id of the currently active model provider, or `None`.
        confidence: Most recent overall confidence score, 0.0-1.0.
        health_score: Most recent overall health score, 0.0-1.0.
        recent_changes: Bounded log of the most recent self-model updates.
        currently_learning: Free-text description of what MARK is currently learning, if anything.
        goals: Names of every goal currently being pursued.
        next_action: MARK's best guess at what it should do next.
        state: Name of the current internal state (see `smartagent.mind.state`).
        last_updated: ISO timestamp of the last update.
    """

    name: str = "MARK"
    owner: str = "Mr. Smart"
    mission: str = ""
    current_activity: str = "idle"
    current_goal: str | None = None
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    active_model: str | None = None
    confidence: float = 0.0
    health_score: float = 1.0
    recent_changes: list[str] = field(default_factory=list)
    currently_learning: str | None = None
    goals: list[str] = field(default_factory=list)
    next_action: str | None = None
    state: str = "idle"
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def describe(self) -> str:
        """A human-readable answer to the milestone's full question list, in one string."""
        return (
            f"I am {self.name}, built for {self.owner}. "
            f"Mission: {self.mission or 'not set'}. "
            f"I am currently: {self.current_activity} (state={self.state}). "
            f"Tools: {len(self.tools)}. Skills: {len(self.skills)}. "
            f"Active model: {self.active_model or 'none'}. "
            f"Confidence: {self.confidence:.2f}. Health: {self.health_score:.2f}. "
            f"Currently learning: {self.currently_learning or 'nothing in particular'}. "
            f"Goals: {', '.join(self.goals) if self.goals else 'none'}. "
            f"Next action: {self.next_action or 'undecided'}."
        )
