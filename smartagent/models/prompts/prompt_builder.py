"""
PromptBuilder — Milestone 5, Part 5.

Assembles a `Prompt` from a system prompt, the current user message,
conversation history, memory context, skill context, and tool results —
without ever knowing which provider will consume it. `ModelManager` is
the only thing that hands a `Prompt` to a `BaseModel`; providers decide
for themselves whether they want `Prompt.render()` (a single flat string,
what `MockModelProvider` consumes) or `Prompt.to_messages()` (a chat-style
list of `{"role", "content"}` dicts, the shape a real chat-completion
provider would want).

`future_context` exists but is deliberately left empty by `build()` for
now — Part 5 lists research, knowledge-graph, and vision context as
future integration points, none of which are implemented in Milestone 5.
The field is here so `PromptBuilder`'s shape does not need to change again
once those subsystems exist; it is just never populated yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.models.context.conversation_context import ConversationContext

#: Placeholder categories for future context sources (Part 5). None of these
#: are populated by `PromptBuilder.build()` in Milestone 5 — see module docstring.
_FUTURE_CONTEXT_KEYS: tuple[str, ...] = ("research", "knowledge_graph", "vision")


@dataclass
class Prompt:
    """
    A fully-assembled prompt, ready for `ModelManager` to hand to any provider.

    Attributes:
        system_prompt: Instructions establishing the assistant's role/behavior.
        user_message: The current request being answered.
        history_lines: Rendered `"role: content"` lines from conversation history.
        memory_context: Memory snippets relevant to this request.
        skill_context: Free-text notes about what skills/capabilities are available.
        tool_results: Recent tool outputs relevant to this request.
        future_context: Placeholder dict for research/knowledge-graph/vision
            context (Part 5) — always empty in Milestone 5.
    """

    system_prompt: str
    user_message: str
    history_lines: tuple[str, ...] = ()
    memory_context: tuple[str, ...] = ()
    skill_context: str = ""
    tool_results: tuple[str, ...] = ()
    future_context: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """
        Flatten everything into a single string, for providers that take one prompt blob.

        Sections that are empty are omitted entirely rather than rendered
        as an empty heading, so a minimal `Prompt` renders as just the
        system prompt and user message.
        """
        sections: list[str] = [f"System: {self.system_prompt}"]
        if self.memory_context:
            sections.append("Relevant memory:\n" + "\n".join(f"- {m}" for m in self.memory_context))
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
        if self.memory_context:
            messages.append({"role": "system", "content": "Relevant memory:\n" + "\n".join(self.memory_context)})
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
        """Rough combined size estimate (~4 chars/token), for logging (Part 12: "log prompt size")."""
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
    ) -> Prompt:
        """
        Assemble a `Prompt` for `message`.

        Args:
            message: The current user message.
            system_prompt: Overridable system instructions.
            context: A `ConversationContext` to pull history/memory/tool
                context from. Optional — omitting it produces a minimal
                prompt with just the system prompt and message, which is
                exactly what a stateless one-off call needs.
            history_limit: Maximum number of recent turns from `context` to include.
            skill_context: Free-text description of currently available
                skills/modules, typically `", ".join(context.skill_names)`-shaped
                text supplied by the caller (Brain integration), not derived here.

        Returns:
            A `Prompt`. `future_context` is always empty (see module docstring).
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
        )
