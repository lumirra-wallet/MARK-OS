"""
MilestonePlanner — groups a flat task list into ordered, named milestones.

For ``large`` and ``enterprise`` complexity goals, ``create_milestones()``
groups the flat ``Planner`` output into 2–4 named ``Milestone`` dataclasses.
For simpler complexities it returns a single unnamed milestone so all callers
are always milestone-aware and the downstream ``Orchestrator`` logic is
uniform.

Rule-based grouping (no LLM required — LLM upgrade is a future task):
  - Phase 1 "Foundation"       — RESEARCH, PLANNING, DESIGN, ARCHITECTURE tasks
  - Phase 2 "Core Development" — IMPLEMENTATION, CODING tasks
  - Phase 3 "Quality Assurance"— TESTING, REVIEW, ANALYSIS, REPORT tasks
  - Phase 4 "Documentation"    — DOCUMENTATION tasks

Empty phases are omitted.  If grouping would produce only one non-empty
phase, the whole list is returned as a single milestone (graceful fallback).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from smartagent.executive.planner import Planner, _COMPLEXITY_UNSET
from smartagent.executive.task import Task, TaskType
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Task-type → milestone phase mapping
# ---------------------------------------------------------------------------

_PHASE_MAP: dict[TaskType, int] = {
    TaskType.RESEARCH:       1,
    TaskType.PLANNING:       1,
    TaskType.DESIGN:         1,
    TaskType.ARCHITECTURE:   1,
    TaskType.IMPLEMENTATION: 2,
    TaskType.CODING:         2,
    TaskType.TESTING:        3,
    TaskType.REVIEW:         3,
    TaskType.ANALYSIS:       3,
    TaskType.REPORT:         3,
    TaskType.DOCUMENTATION:  4,
    # Everything else defaults to phase 2 (build phase)
}

_PHASE_TITLES: dict[int, str] = {
    1: "Foundation",
    2: "Core Development",
    3: "Quality Assurance",
    4: "Documentation",
}

# Complexities that trigger multi-milestone decomposition
_MILESTONE_COMPLEXITIES = frozenset({"large", "enterprise"})


# ---------------------------------------------------------------------------
# Milestone dataclass
# ---------------------------------------------------------------------------


@dataclass
class Milestone:
    """
    One named phase of a goal's execution plan.

    Attributes:
        phase:      Sequential integer starting at 1.
        title:      Short human-readable name (e.g. "Foundation").
        objective:  One-sentence description of what this milestone achieves.
        tasks:      Ordered list of ``Task`` objects belonging to this milestone.
    """

    phase: int
    title: str
    objective: str
    tasks: list[Task] = field(default_factory=list)
    total: int = 1  # Task #11 — total milestones in this run (set by MilestonePlanner)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation of this milestone."""
        return {
            "phase": self.phase,
            "title": self.title,
            "objective": self.objective,
            "task_ids": [t.id for t in self.tasks],
            "task_titles": [t.title for t in self.tasks],
            "task_count": len(self.tasks),
            "status": self._aggregate_status(),
        }

    def _aggregate_status(self) -> str:
        """Aggregate status across all tasks in this milestone."""
        from smartagent.executive.task import TaskStatus
        statuses = {t.status for t in self.tasks}
        if all(t.status == TaskStatus.COMPLETED for t in self.tasks):
            return "completed"
        if any(t.status == TaskStatus.FAILED for t in self.tasks):
            return "failed"
        if any(t.status == TaskStatus.RUNNING for t in self.tasks):
            return "running"
        if any(t.status == TaskStatus.READY for t in self.tasks):
            return "ready"
        return "pending"

    def __repr__(self) -> str:
        return (
            f"Milestone(phase={self.phase}, title={self.title!r}, "
            f"tasks={len(self.tasks)})"
        )


# ---------------------------------------------------------------------------
# MilestonePlanner
# ---------------------------------------------------------------------------


class MilestonePlanner:
    """
    Wraps the rule-based ``Planner`` and groups its output into milestones.

    Args:
        planner: Optional ``Planner`` instance.  A default one is created
                 if not provided.
    """

    def __init__(self, planner: Planner | None = None) -> None:
        self._planner = planner or Planner()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_milestones(
        self,
        goal: str,
        complexity: str | None = None,
    ) -> list[Milestone]:
        """
        Decompose *goal* into an ordered list of ``Milestone`` objects.

        For ``large``/``enterprise`` complexity the flat task list is grouped
        into 2–4 named phases.  For all other complexities a single milestone
        wrapping the original flat plan is returned, preserving full backward
        compatibility.

        Args:
            goal:       Free-form user goal string.
            complexity: Optional complexity hint — ``"trivial"``, ``"small"``,
                        ``"medium"``, ``"large"``, or ``"enterprise"``.

        Returns:
            Non-empty ordered list of ``Milestone`` objects.
        """
        if not goal or not goal.strip():
            raise ValueError("Goal must be a non-empty string.")

        # Delegate task creation to the underlying Planner
        if complexity is not None:
            tasks = self._planner.create_plan(goal, complexity=complexity)
        else:
            tasks = self._planner.create_plan(goal)

        use_milestones = (
            complexity is not None and complexity in _MILESTONE_COMPLEXITIES
        )

        if use_milestones and len(tasks) >= 3:
            milestones = self._group_into_milestones(goal, tasks)
            # Fallback: if grouping collapsed to a single group, wrap normally
            if len(milestones) >= 2:
                logger.info(
                    "MilestonePlanner: %d tasks → %d milestones for %r",
                    len(tasks), len(milestones), complexity,
                )
                return milestones

        # Single-milestone path — wraps the flat plan unchanged
        logger.info(
            "MilestonePlanner: complexity=%r → single milestone (%d tasks)",
            complexity, len(tasks),
        )
        return self._single_milestone(goal, tasks)

    # ------------------------------------------------------------------
    # Grouping helpers
    # ------------------------------------------------------------------

    def _group_into_milestones(
        self, goal: str, tasks: list[Task]
    ) -> list[Milestone]:
        """
        Group *tasks* by their semantic phase and return ordered milestones.

        Tasks whose type is not in ``_PHASE_MAP`` default to phase 2
        (build phase).  Empty phases are omitted.  Cross-milestone
        dependencies on the first task of each milestone are cleared so
        each milestone runs as a self-contained unit (results remain
        available in the shared ``ExecutionContext``).
        """
        # Bucket tasks by phase
        buckets: dict[int, list[Task]] = {}
        for task in tasks:
            phase = _PHASE_MAP.get(task.task_type, 2)
            buckets.setdefault(phase, []).append(task)

        # Build milestones in phase order, re-sequencing phase numbers
        milestones: list[Milestone] = []
        phase_number = 1
        for original_phase in sorted(buckets.keys()):
            bucket = buckets[original_phase]
            title = _PHASE_TITLES.get(original_phase, f"Phase {original_phase}")
            objective = self._build_objective(title, goal)

            # Clear the first task's dependency if it crosses into a
            # previous milestone (callers pass the original linear chain).
            first = bucket[0]
            first.dependencies = []

            # Re-wire remaining tasks in this bucket so they form a
            # sequential chain within the milestone.
            for i in range(1, len(bucket)):
                bucket[i].dependencies = [bucket[i - 1].id]

            milestones.append(
                Milestone(
                    phase=phase_number,
                    title=title,
                    objective=objective,
                    tasks=bucket,
                )
            )
            phase_number += 1

        # Task #11 — stamp total on each milestone so CheckpointManager can
        # include it in the commit message without needing the full list.
        total = len(milestones)
        for m in milestones:
            m.total = total

        return milestones

    def _single_milestone(self, goal: str, tasks: list[Task]) -> list[Milestone]:
        """Wrap *tasks* into a single milestone (backward-compat path)."""
        return [
            Milestone(
                phase=1,
                title="Execution",
                objective=f"Execute: {goal[:100]}",
                tasks=tasks,
                total=1,
            )
        ]

    @staticmethod
    def _build_objective(title: str, goal: str) -> str:
        """Build a short objective string for a milestone."""
        return f"{title} phase for: {goal[:100]}"
