"""
Planner — rule-based goal decomposition / v2.0 Performance Upgrade.

v2.0: added complexity-aware plan selection via TaskComplexity.
  - trivial goals → 2 tasks (Implementation + Testing)
  - small goals   → 3 tasks (Implementation + Testing)  [same as script]
  - medium goals  → Research + Implementation + Testing + Review (4 tasks)
  - large goals   → full pipeline (5 tasks)
  - enterprise    → full pipeline + Documentation (6 tasks)

Keyword routing is unchanged — the template selected by keywords is then
further filtered by complexity so trivial/small goals never trigger 5-call
pipelines unnecessarily.

Phase 4 upgrade path:
    Replace ``_infer_template()`` with an Ollama call that returns a
    JSON plan, while keeping the rest of the pipeline identical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from smartagent.executive.task import Task, TaskType
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _TaskSpec:
    """One step in a plan template."""
    title: str
    task_type: TaskType
    description_template: str  # may contain {goal}


_TEMPLATES: dict[str, list[_TaskSpec]] = {
    # --- trivial: 2 tasks — no research, no review ---
    "trivial": [
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Implement: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Write tests for: {goal}"),
    ],
    # --- medium_app: 3 tasks — planning + coding + testing, no research ---
    # Used when complexity is explicitly "medium" (progressive execution tier 2).
    # NOTE: this template is ONLY selected when complexity="medium" is explicitly
    # passed to create_plan().  Calling create_plan(goal) without complexity still
    # uses keyword matching (backward compatible).
    "medium_app": [
        _TaskSpec("Planning",       TaskType.PLANNING,       "Create a focused plan for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Implement: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Write and run tests for: {goal}"),
    ],
    # --- api / backend: 5 tasks ---
    "api": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research requirements and prior art for: {goal}"),
        _TaskSpec("Architecture",   TaskType.ARCHITECTURE,   "Design the API architecture and data contracts for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Implement the API endpoints for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Write and run tests for: {goal}"),
        _TaskSpec("Documentation",  TaskType.DOCUMENTATION,  "Write API documentation for: {goal}"),
    ],
    # --- script / cli: 3 tasks ---
    "script": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research the best approach for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Write the script or tool for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Test and validate the script for: {goal}"),
    ],
    # --- research / analysis: 3 tasks ---
    "research": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Gather information and sources for: {goal}"),
        _TaskSpec("Analysis",       TaskType.ANALYSIS,       "Analyse and synthesise findings for: {goal}"),
        _TaskSpec("Report",         TaskType.REPORT,         "Write a structured report for: {goal}"),
    ],
    # --- algorithm: 4 tasks ---
    "algorithm": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research existing algorithms for: {goal}"),
        _TaskSpec("Design",         TaskType.DESIGN,         "Design the algorithm and data structures for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Implement the algorithm for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Test and benchmark the algorithm for: {goal}"),
    ],
    # --- database / schema: 5 tasks ---
    "database": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research data model options for: {goal}"),
        _TaskSpec("Design",         TaskType.DESIGN,         "Design the schema and relationships for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Create migrations and models for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Test queries and data integrity for: {goal}"),
        _TaskSpec("Documentation",  TaskType.DOCUMENTATION,  "Document the schema for: {goal}"),
    ],
    # --- default: 5 tasks ---
    "default": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research requirements and best practices for: {goal}"),
        _TaskSpec("Design",         TaskType.DESIGN,         "Design the architecture and interfaces for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Implement the solution for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Test and validate the implementation for: {goal}"),
        _TaskSpec("Review",         TaskType.REVIEW,         "Review, refine, and finalise: {goal}"),
    ],
}

# Maps keyword patterns to template names.
_KEYWORD_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(api|rest|graphql|endpoint|backend|service|server|microservice|webhook)\b", re.I), "api"),
    (re.compile(r"\b(script|utility|tool|cli|command.?line|automation|scraper|crawler|bot)\b", re.I), "script"),
    (re.compile(r"\b(research|analys[ei]s|analys[ei]ze|study|investigate|explore|survey|review\s+paper)\b", re.I), "research"),
    (re.compile(r"\b(algorithm|sort|sorting|search|searching|data.?struct|optimis|optimiz|recursion|dynamic.?prog)\b", re.I), "algorithm"),
    (re.compile(r"\b(database|schema|migration|orm|model|sql|nosql|postgres|mongodb|redis|table)\b", re.I), "database"),
]

# Sentinel — distinguishes "caller passed complexity explicitly" from "caller
# omitted it and got the default".  This lets the Planner apply template
# selection only when complexity is intentionally specified, preserving full
# backward compatibility for all callers that use create_plan(goal) without
# the complexity argument.
_COMPLEXITY_UNSET = object()


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """
    Rule-based goal decomposer.

    v2.0: complexity-aware plan selection reduces AI calls for simple goals.
    ``create_plan(goal, complexity)`` accepts an optional complexity string.

    ``create_plan(goal)`` returns an ordered list of ``Task`` objects whose
    dependencies are pre-wired so that each task depends on its predecessor.
    """

    def create_plan(self, goal: str, complexity=_COMPLEXITY_UNSET) -> list[Task]:
        """
        Decompose *goal* into an ordered list of ``Task`` objects.

        Args:
            goal:       Free-form user goal string.
            complexity: Optional complexity hint — ``"trivial"``, ``"small"``,
                        ``"medium"``, ``"large"``, or ``"enterprise"``.

                        When omitted (the default), keyword matching selects
                        the template — this is the backward-compatible path
                        used by all pre-v2.0 callers.

                        When explicitly passed:
                          - ``"trivial"`` / ``"small"`` → 2-task plan
                            (Implementation + Testing only).
                          - ``"medium"`` → 3-task plan
                            (Planning + Implementation + Testing).
                            No Research, Architecture, or Documentation.
                          - ``"large"`` / ``"enterprise"`` → full
                            keyword-matched template (same as omitting).

        Returns:
            Ordered list of ``Task`` objects (first task has no deps).
        """
        if not goal or not goal.strip():
            raise ValueError("Goal must be a non-empty string.")

        explicitly_set = complexity is not _COMPLEXITY_UNSET

        # ── Template selection ────────────────────────────────────────────
        if explicitly_set and complexity in ("trivial", "small"):
            # Fast-path: simple task — 2 workers (code + test only)
            template_name = "trivial"
            specs = _TEMPLATES["trivial"]

        elif explicitly_set and complexity == "medium":
            # Progressive tier 2: no research / architecture / documentation
            template_name = "medium_app"
            specs = _TEMPLATES["medium_app"]

        else:
            # Legacy / large / enterprise / omitted → keyword matching.
            # This path is identical to all pre-v2.0 behaviour and must not
            # be changed — many tests rely on specific template selection.
            template_name = self._infer_template(goal.strip())
            specs = _TEMPLATES[template_name]

        logger.info(
            "Planner: goal=%r complexity=%r template=%r (%d tasks)",
            goal, complexity if explicitly_set else "(auto)", template_name, len(specs),
        )

        tasks: list[Task] = []
        for spec in specs:
            description = spec.description_template.format(goal=goal)
            deps = [tasks[-1].id] if tasks else []
            task = Task(
                title=spec.title,
                description=description,
                task_type=spec.task_type,
                dependencies=deps,
            )
            tasks.append(task)

        return tasks

    def _infer_template(self, goal: str) -> str:
        """
        Classify *goal* into a template name using keyword matching.

        Returns the name of the best-matching template, or ``"default"``
        when no keywords match.
        """
        for pattern, template_name in _KEYWORD_MAP:
            if pattern.search(goal):
                logger.debug("Planner: keyword match → template=%r", template_name)
                return template_name
        return "default"

    def available_templates(self) -> list[str]:
        """Return the names of all built-in plan templates."""
        return list(_TEMPLATES.keys())
