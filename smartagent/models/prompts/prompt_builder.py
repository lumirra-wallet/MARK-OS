"""
PromptBuilder — Milestone 5, Part 5 / updated Milestone 9.

Assembles a `Prompt` from a system prompt, the current user message,
conversation history, memory context, skill context, and tool results —
without ever knowing which provider will consume it. `ModelManager` is
the only thing that hands a `Prompt` to a `BaseModel`; providers decide
for themselves whether they want `Prompt.render()` (a single flat string,
what `MockModelProvider` / `OllamaProvider` consume via flat text) or
`Prompt.to_messages()` (a chat-style list of `{"role", "content"}` dicts,
the shape a real chat-completion provider would want).

Milestone 9 additions (all new fields default to empty so existing call
sites are entirely unaffected):
  - `knowledge_context` — relevant concepts from the Knowledge Engine.
  - `mind_state`        — current Mind OS state string.
  - `identity`          — MARK identity summary line.
  - `goals`             — active goal descriptions from GoalManager.

`future_context` is preserved for backward compatibility but no longer
used internally — the new typed fields supersede it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from smartagent.models.context.conversation_context import ConversationContext


@dataclass
class Prompt:
    """
    A fully-assembled prompt, ready for `ModelManager` to hand to any provider.

    Attributes:
        system_prompt:      Instructions establishing the assistant's role/behavior.
        user_message:       The current request being answered.
        history_lines:      Rendered ``"role: content"`` lines from conversation history.
        memory_context:     Memory snippets relevant to this request.
        skill_context:      Free-text notes about what skills/capabilities are available.
        tool_results:       Recent tool outputs relevant to this request.
        future_context:     Kept for backward compatibility; prefer typed fields below.
        knowledge_context:  Knowledge-Engine concepts relevant to this request (M9).
        mind_state:         Current Mind OS state label, e.g. ``"thinking"`` (M9).
        identity:           One-line identity summary injected as system context (M9).
        goals:              Active goal descriptions from GoalManager (M9).
    """

    system_prompt: str
    user_message: str
    history_lines: tuple[str, ...] = ()
    memory_context: tuple[str, ...] = ()
    skill_context: str = ""
    tool_results: tuple[str, ...] = ()
    future_context: dict[str, str] = field(default_factory=dict)
    # Milestone 9 additions — all default to empty for backward compatibility.
    knowledge_context: tuple[str, ...] = ()
    mind_state: str = ""
    identity: str = ""
    goals: tuple[str, ...] = ()

    def render(self) -> str:
        """
        Flatten everything into a single string, for providers that take one prompt blob.

        Sections that are empty are omitted entirely rather than rendered
        as an empty heading, so a minimal `Prompt` renders as just the
        system prompt and user message.
        """
        sections: list[str] = [f"System: {self.system_prompt}"]
        if self.identity:
            sections.append(f"Identity: {self.identity}")
        if self.mind_state:
            sections.append(f"Current state: {self.mind_state}")
        if self.goals:
            sections.append("Active goals:\n" + "\n".join(f"- {g}" for g in self.goals))
        if self.memory_context:
            sections.append("Relevant memory:\n" + "\n".join(f"- {m}" for m in self.memory_context))
        if self.knowledge_context:
            sections.append("Relevant knowledge:\n" + "\n".join(f"- {k}" for k in self.knowledge_context))
        if self.skill_context:
            sections.append(f"Available skills: {self.skill_context}")
        if self.history_lines:
            sections.append("Conversation history:\n" + "\n".join(self.history_lines))
        if self.tool_results:
            sections.append("Recent tool results:\n" + "\n".join(f"- {t}" for t in self.tool_results))
        sections.append(f"User: {self.user_message}")
        return "\n\n".join(sections)

    def to_messages(self) -> list[dict[str, str]]:
        """Render as a chat-style message list, for providers that take structured turns."""
        messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        if self.identity:
            messages.append({"role": "system", "content": f"Identity: {self.identity}"})
        if self.mind_state:
            messages.append({"role": "system", "content": f"Current state: {self.mind_state}"})
        if self.goals:
            messages.append({"role": "system", "content": "Active goals:\n" + "\n".join(f"- {g}" for g in self.goals)})
        if self.memory_context:
            messages.append({"role": "system", "content": "Relevant memory:\n" + "\n".join(self.memory_context)})
        if self.knowledge_context:
            messages.append({"role": "system", "content": "Relevant knowledge:\n" + "\n".join(self.knowledge_context)})
        if self.skill_context:
            messages.append({"role": "system", "content": f"Available skills: {self.skill_context}"})
        if self.tool_results:
            messages.append({"role": "system", "content": "Recent tool results:\n" + "\n".join(self.tool_results)})
        for line in self.history_lines:
            role, _, content = line.partition(": ")
            messages.append({"role": role or "user", "content": content or line})
        messages.append({"role": "user", "content": self.user_message})
        return messages

    def token_estimate(self) -> int:
        """Rough combined size estimate (~4 chars/token), for logging."""
        return max(0, len(self.render()) // 4)


class PromptBuilder:
    """Builds `Prompt` instances from a message plus optional context sources."""

    def build(
        self,
        message: str,
        *,
        system_prompt: str = "You are SmartAgent, a helpful personal assistant.",
        context: "ConversationContext | None" = None,
        history_limit: int = 10,
        skill_context: str = "",
        # Milestone 9 additions — all keyword-only with empty defaults so
        # every existing call site continues to work without modification.
        knowledge_snippets: Sequence[str] = (),
        mind_state: str = "",
        identity: str = "",
        goals: Sequence[str] = (),
    ) -> Prompt:
        """
        Assemble a `Prompt` for `message`.

        Args:
            message:            The current user message.
            system_prompt:      Overridable system instructions.
            context:            A `ConversationContext` to pull history/memory/tool
                                context from. Optional.
            history_limit:      Maximum number of recent turns from `context` to include.
            skill_context:      Free-text description of currently available skills.
            knowledge_snippets: Knowledge-Engine concept summaries (M9).
            mind_state:         Current Mind OS state label (M9).
            identity:           One-line identity string (M9).
            goals:              Active goal descriptions (M9).

        Returns:
            A fully assembled `Prompt`.
        """
        history_lines: tuple[str, ...] = ()
        memory_context: tuple[str, ...] = ()
        tool_results: tuple[str, ...] = ()

        if context is not None:
            history_lines = tuple(f"{turn.role}: {turn.content}" for turn in context.recent(history_limit))
            memory_context = tuple(context.memory_refs)
            tool_results = tuple(context.tool_outputs)

        return Prompt(
            system_prompt=system_prompt,
            user_message=message,
            history_lines=history_lines,
            memory_context=memory_context,
            skill_context=skill_context,
            tool_results=tool_results,
            future_context={},
            knowledge_context=tuple(knowledge_snippets),
            mind_state=mind_state,
            identity=identity,
            goals=tuple(goals),
        )
