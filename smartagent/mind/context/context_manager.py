"""
ContextManager — Milestone 6, Part 6.

Assembles the most relevant context from every source the Mind has access
to (conversation, working memory, knowledge/memory search results, goals,
research, reflection, tool outputs, identity) into one bundle, and renders
a compact text blob from it — the first step toward future token-budget
optimization (Part 6: "Prepare for future token optimization").

Design decision: sources are supplied per-call as plain lists of strings
(not live references to other subsystems) so `ContextManager` has zero
import dependency on memory/skills/tools/etc. Whoever calls `assemble()`
(typically `ExecutiveController`) is responsible for gathering each
source's current content first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_MAX_ITEMS_PER_SOURCE = 5
DEFAULT_MAX_CHARS = 4000


@dataclass
class ContextBundle:
    """The assembled context for one turn, grouped by source."""

    conversation: list[str] = field(default_factory=list)
    working_memory: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    research: list[str] = field(default_factory=list)
    reflection: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)
    identity: list[str] = field(default_factory=list)

    def render(self, max_chars: int = DEFAULT_MAX_CHARS) -> str:
        """Flatten every source into one truncated text blob, most important sources first."""
        sections = [
            ("Identity", self.identity),
            ("Goals", self.goals),
            ("Conversation", self.conversation),
            ("Working Memory", self.working_memory),
            ("Knowledge", self.knowledge),
            ("Research", self.research),
            ("Reflection", self.reflection),
            ("Tool Outputs", self.tool_outputs),
        ]
        parts: list[str] = []
        for title, items in sections:
            if not items:
                continue
            parts.append(f"[{title}]\n" + "\n".join(f"- {item}" for item in items))
        rendered = "\n\n".join(parts)
        if len(rendered) > max_chars:
            rendered = rendered[:max_chars].rstrip() + "\n… (truncated)"
        return rendered


class ContextManager:
    """
    Builds a `ContextBundle` from raw source material, keeping only the most
    relevant items per source (Part 6: "Return only the most relevant context").

    Args:
        max_items_per_source: Cap on how many items from each source survive
            into the bundle. Relevance ordering is the caller's
            responsibility (each list is assumed most-relevant-first); this
            manager only truncates.
    """

    def __init__(self, max_items_per_source: int = DEFAULT_MAX_ITEMS_PER_SOURCE) -> None:
        self.max_items_per_source = max_items_per_source

    def assemble(
        self,
        conversation: list[str] | None = None,
        working_memory: list[str] | None = None,
        knowledge: list[str] | None = None,
        goals: list[str] | None = None,
        research: list[str] | None = None,
        reflection: list[str] | None = None,
        tool_outputs: list[str] | None = None,
        identity: list[str] | None = None,
    ) -> ContextBundle:
        """Build a `ContextBundle`, truncating each source to `max_items_per_source`."""
        return ContextBundle(
            conversation=self._cap(conversation),
            working_memory=self._cap(working_memory),
            knowledge=self._cap(knowledge),
            goals=self._cap(goals),
            research=self._cap(research),
            reflection=self._cap(reflection),
            tool_outputs=self._cap(tool_outputs),
            identity=self._cap(identity),
        )

    def _cap(self, items: list[str] | None) -> list[str]:
        if not items:
            return []
        return list(items[: self.max_items_per_source])
