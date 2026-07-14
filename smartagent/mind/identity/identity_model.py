"""
`Identity` — the data shape behind Milestone 6, Part 3 (Identity Engine).

A plain dataclass rather than a live-parsed view of `SMARTAGENT.md` on every
access: the mission is to make identity *executable* (a Python object other
engines can query/pass around) instead of prose a human has to re-read.
`IdentityEngine` (this package's `identity_engine.py`) is what turns the
Markdown file into one of these and back.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Identity:
    """
    MARK's executable identity.

    Attributes:
        name: The assistant's name (e.g. "MARK").
        owner: Who MARK exists for (e.g. "Mr. Smart").
        mission: One-paragraph statement of purpose.
        core_values: Short, ordered list of non-negotiable principles.
        operating_principles: How MARK is expected to behave day-to-day.
        safety_rules: Actions that require explicit confirmation.
        architecture_vision: The list of subsystems MARK is built from.
        personality: A short adjective-style description of tone/manner.
        long_term_objectives: Capabilities MARK is working toward.
    """

    name: str = "MARK"
    owner: str = "Mr. Smart"
    mission: str = ""
    core_values: list[str] = field(default_factory=list)
    operating_principles: list[str] = field(default_factory=list)
    safety_rules: list[str] = field(default_factory=list)
    architecture_vision: list[str] = field(default_factory=list)
    personality: str = ""
    long_term_objectives: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line human-readable identity summary (used by `SelfModel.describe()`)."""
        return f"{self.name}, built for {self.owner}. Mission: {self.mission or 'not set'}."
