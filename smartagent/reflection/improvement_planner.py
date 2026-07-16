"""
ImprovementPlanner — Milestone 14.

Converts a ``CriticReport`` into a concrete ``ImprovementPlan``:
  - Prompt improvements per worker (versioned in PromptRegistry)
  - Knowledge concepts to propose (via KnowledgeManager inbox)
  - Memory entries to store (lessons learned, successful strategies)
  - Recommended settings adjustments
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.reflection.critic import CriticReport
    from smartagent.reflection.execution_analyzer import ExecutionReport


@dataclass
class KnowledgeProposal:
    """A concept to propose to the KnowledgeManager inbox."""
    title: str
    description: str
    category: str = "AI Execution"
    tags: list[str] = field(default_factory=list)


@dataclass
class MemoryEntry:
    """A lesson to store in the MemoryManager vault."""
    content: str
    category: str = "Lessons"
    tags: list[str] = field(default_factory=list)


@dataclass
class PromptImprovement:
    """A suggested improved system prompt for one worker."""
    worker_name: str
    hint: str               # one-sentence guidance from the Critic
    improved_prompt: str    # expanded into a full prompt addendum
    estimated_gain: float   # rough confidence improvement estimate


@dataclass
class ImprovementPlan:
    """
    Complete improvement plan produced by ``ImprovementPlanner.plan()``.

    All lists may be empty — nothing is forced when execution was already
    high quality.
    """
    prompt_improvements: list[PromptImprovement] = field(default_factory=list)
    knowledge_proposals: list[KnowledgeProposal] = field(default_factory=list)
    memory_entries: list[MemoryEntry] = field(default_factory=list)
    recommended_settings: dict = field(default_factory=dict)
    summary: str = ""


class ImprovementPlanner:
    """
    Translates ``CriticReport`` output into actionable improvement plans.

    Entirely heuristic — no LLM required.  The planner follows simple rules:
      - Low confidence workers get prompt addenda.
      - Missing knowledge topics become knowledge proposals.
      - Failure patterns are stored as lessons in memory.
    """

    # Minimum confidence below which we generate a prompt improvement
    _PROMPT_IMPROVEMENT_THRESHOLD = 0.60

    def plan(
        self,
        critic: "CriticReport",
        report: "ExecutionReport | None" = None,
    ) -> ImprovementPlan:
        """Build an ``ImprovementPlan`` from *critic* and optional raw *report*."""
        prompt_improvements = self._plan_prompt_improvements(critic)
        knowledge_proposals = self._plan_knowledge(critic, report)
        memory_entries = self._plan_memory(critic, report)
        settings = self._plan_settings(critic, report)

        summary_parts: list[str] = []
        if prompt_improvements:
            summary_parts.append(
                f"{len(prompt_improvements)} prompt improvement(s)"
            )
        if knowledge_proposals:
            summary_parts.append(f"{len(knowledge_proposals)} knowledge proposal(s)")
        if memory_entries:
            summary_parts.append(f"{len(memory_entries)} memory entry(ies)")

        summary = (
            "Improvement plan: " + ", ".join(summary_parts) + "."
            if summary_parts
            else "No improvements needed — execution quality is high."
        )

        return ImprovementPlan(
            prompt_improvements=prompt_improvements,
            knowledge_proposals=knowledge_proposals,
            memory_entries=memory_entries,
            recommended_settings=settings,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Prompt improvements
    # ------------------------------------------------------------------

    def _plan_prompt_improvements(
        self, critic: "CriticReport"
    ) -> list[PromptImprovement]:
        improvements: list[PromptImprovement] = []
        for worker_name, hint in critic.prompt_hints.items():
            addendum = self._expand_hint_to_addendum(worker_name, hint)
            improvements.append(
                PromptImprovement(
                    worker_name=worker_name,
                    hint=hint,
                    improved_prompt=addendum,
                    estimated_gain=0.05,  # conservative estimate
                )
            )
        return improvements

    def _expand_hint_to_addendum(self, worker_name: str, hint: str) -> str:
        """Expand a one-sentence hint into a structured prompt addendum."""
        return (
            f"\n---\n## Improvement Note\n"
            f"Based on recent performance analysis:\n\n"
            f"{hint}\n\n"
            f"Apply this guidance throughout your response."
        )

    # ------------------------------------------------------------------
    # Knowledge proposals
    # ------------------------------------------------------------------

    def _plan_knowledge(
        self,
        critic: "CriticReport",
        report: "ExecutionReport | None",
    ) -> list[KnowledgeProposal]:
        proposals: list[KnowledgeProposal] = []

        for topic in critic.missing_knowledge:
            # Trim boilerplate prefix
            title = topic.replace("Domain knowledge was missing for ", "").strip("'\"")
            title = title[:80]
            proposals.append(KnowledgeProposal(
                title=f"Knowledge Gap: {title}",
                description=(
                    f"During an AI execution, this knowledge gap was identified: {topic}. "
                    f"Resolving this would improve future similar executions."
                ),
                category="AI Execution",
                tags=["knowledge-gap", "reflection", "ai-learning"],
            ))

        if report and critic.overall_score > 0.7:
            # High-quality execution — propose what worked as a best practice
            goal_short = report.goal[:60]
            proposals.append(KnowledgeProposal(
                title=f"Successful Strategy: {goal_short}",
                description=(
                    f"A high-quality execution (score {critic.overall_score:.0%}) "
                    f"was completed for the goal: '{report.goal}'. "
                    f"The execution achieved {report.success_rate:.0%} task success "
                    f"rate with {report.avg_confidence:.0%} average confidence."
                ),
                category="Best Practices",
                tags=["successful-execution", "best-practice", "reflection"],
            ))

        return proposals

    # ------------------------------------------------------------------
    # Memory entries
    # ------------------------------------------------------------------

    def _plan_memory(
        self,
        critic: "CriticReport",
        report: "ExecutionReport | None",
    ) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []

        # Store failures as lessons
        for failure in critic.what_failed:
            if failure != "No significant failures detected.":
                entries.append(MemoryEntry(
                    content=f"Lesson learned: {failure}",
                    category="Lessons",
                    tags=["lesson", "failure", "reflection"],
                ))

        # Store the critic summary
        if critic.summary:
            entries.append(MemoryEntry(
                content=f"Reflection summary: {critic.summary}",
                category="Reflections",
                tags=["reflection", "summary"],
            ))

        # Store successful strategies
        if critic.overall_score > 0.75 and report:
            entries.append(MemoryEntry(
                content=(
                    f"Successful strategy for '{report.goal[:60]}': "
                    f"{', '.join(critic.what_succeeded[:3])}"
                ),
                category="Successful Strategies",
                tags=["strategy", "success", "reflection"],
            ))

        return entries

    # ------------------------------------------------------------------
    # Settings recommendations
    # ------------------------------------------------------------------

    def _plan_settings(
        self,
        critic: "CriticReport",
        report: "ExecutionReport | None",
    ) -> dict:
        settings: dict = {}

        if critic.missing_tools and report and len(report.tool_ids_used) == 0:
            settings["enable_tool_engine"] = True

        return settings
