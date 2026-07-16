"""
PromptAuditor — measures token contribution per section of a worker prompt.

Tracks:
  - system prompt size
  - prior task results injected
  - goal text
  - knowledge snippets
  - memory snippets
  - task description

Usage::

    from smartagent.performance.prompt_auditor import PromptAudit, measure_prompt

    audit = measure_prompt(
        system=worker._system_prompt,
        prior_results=prior_block,
        goal=context.goal,
        task_desc=task.description,
        knowledge=knowledge_ctx,
        memory=memory_ctx,
    )

    for line in audit.as_display_lines():
        print(line)
"""

from __future__ import annotations

from dataclasses import dataclass

_CHARS_PER_TOKEN: int = 4
_WARN_THRESHOLD_TOKENS: int = 400   # flag any section exceeding this


@dataclass
class PromptAudit:
    """Token breakdown for one worker's prompt."""

    system_chars: int = 0
    prior_chars: int = 0
    goal_chars: int = 0
    task_chars: int = 0
    knowledge_chars: int = 0
    memory_chars: int = 0

    @property
    def system_tokens(self) -> int:
        return self.system_chars // _CHARS_PER_TOKEN

    @property
    def prior_tokens(self) -> int:
        return self.prior_chars // _CHARS_PER_TOKEN

    @property
    def goal_tokens(self) -> int:
        return self.goal_chars // _CHARS_PER_TOKEN

    @property
    def task_tokens(self) -> int:
        return self.task_chars // _CHARS_PER_TOKEN

    @property
    def knowledge_tokens(self) -> int:
        return self.knowledge_chars // _CHARS_PER_TOKEN

    @property
    def memory_tokens(self) -> int:
        return self.memory_chars // _CHARS_PER_TOKEN

    @property
    def total_chars(self) -> int:
        return (
            self.system_chars
            + self.prior_chars
            + self.goal_chars
            + self.task_chars
            + self.knowledge_chars
            + self.memory_chars
        )

    @property
    def total_tokens(self) -> int:
        return self.total_chars // _CHARS_PER_TOKEN

    def as_display_lines(self) -> list[str]:
        """Return aligned display lines showing token contribution per section."""
        sections = [
            ("System Prompt",    self.system_tokens),
            ("Prior Results",    self.prior_tokens),
            ("Goal",             self.goal_tokens),
            ("Task Description", self.task_tokens),
            ("Knowledge",        self.knowledge_tokens),
            ("Memory",           self.memory_tokens),
        ]

        # Filter out zero-contribution sections
        sections = [(label, tok) for label, tok in sections if tok > 0]
        if not sections:
            return ["  (no prompt data)"]

        label_width = max(len(l) for l, _ in sections)
        lines: list[str] = ["── Prompt Audit ──────────────────────────────────"]
        for label, tokens in sections:
            warn = " ← large" if tokens > _WARN_THRESHOLD_TOKENS else ""
            lines.append(f"  {label:<{label_width}} {tokens:>5} tokens{warn}")

        lines.append("──────────────────────────────────────────────────")
        lines.append(f"  {'TOTAL':<{label_width}} {self.total_tokens:>5} tokens")
        lines.append("──────────────────────────────────────────────────")
        return lines

    def flagged_sections(self) -> list[str]:
        """Return names of sections exceeding the warning threshold."""
        flagged = []
        if self.system_tokens > _WARN_THRESHOLD_TOKENS:
            flagged.append("System Prompt")
        if self.prior_tokens > _WARN_THRESHOLD_TOKENS:
            flagged.append("Prior Results")
        if self.knowledge_tokens > _WARN_THRESHOLD_TOKENS:
            flagged.append("Knowledge")
        if self.memory_tokens > _WARN_THRESHOLD_TOKENS:
            flagged.append("Memory")
        return flagged


def measure_prompt(
    *,
    system: str = "",
    prior_results: str = "",
    goal: str = "",
    task_desc: str = "",
    knowledge: str = "",
    memory: str = "",
) -> PromptAudit:
    """
    Build a :class:`PromptAudit` by measuring each prompt section.

    All parameters are raw strings (not yet joined).  Pass empty strings for
    sections that were not included in the prompt.
    """
    return PromptAudit(
        system_chars=len(system),
        prior_chars=len(prior_results),
        goal_chars=len(goal),
        task_chars=len(task_desc),
        knowledge_chars=len(knowledge),
        memory_chars=len(memory),
    )
