"""
Planner — rule-based goal decomposition (Phase 1).

The ``Planner`` receives a goal string and returns an ordered list of
``Task`` objects that the ``ExecutiveController`` will arrange into a
``TaskGraph``.

Phase 1 strategy:
    Keyword analysis on the goal string selects a named task template
    (a pre-defined list of task types and titles).  No AI is invoked.

Phase 4 upgrade path:
    Replace ``_infer_template()`` with an Ollama call that returns a
    JSON plan, while keeping the rest of the pipeline identical.

Templates (rule-based):
    api / backend / service / endpoint / rest / graphql
        → Research → Architecture → Implementation → Testing → Documentation

    script / utility / tool / cli / automation
        → Research → Implementation → Testing

    research / analyse / analyze / study / investigate / explore
        → Research → Analysis → Report

    algorithm / sort / search / data structure / optimise / optimize
        → Research → Design → Implementation → Testing

    database / schema / migration / model / orm
        → Research → Design → Implementation → Testing → Documentation

    calculator / app / application / system / platform (default)
        → Research → Design → Implementation → Testing → Review
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
    "api": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research requirements and prior art for: {goal}"),
        _TaskSpec("Architecture",   TaskType.ARCHITECTURE,   "Design the API architecture and data contracts for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Implement the API endpoints for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Write and run tests for: {goal}"),
        _TaskSpec("Documentation",  TaskType.DOCUMENTATION,  "Write API documentation for: {goal}"),
    ],
    "script": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research the best approach for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Write the script or tool for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Test and validate the script for: {goal}"),
    ],
    "research": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Gather information and sources for: {goal}"),
        _TaskSpec("Analysis",       TaskType.ANALYSIS,       "Analyse and synthesise findings for: {goal}"),
        _TaskSpec("Report",         TaskType.REPORT,         "Write a structured report for: {goal}"),
    ],
    "algorithm": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research existing algorithms for: {goal}"),
        _TaskSpec("Design",         TaskType.DESIGN,         "Design the algorithm and data structures for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Implement the algorithm for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Test and benchmark the algorithm for: {goal}"),
    ],
    "database": [
        _TaskSpec("Research",       TaskType.RESEARCH,       "Research data model options for: {goal}"),
        _TaskSpec("Design",         TaskType.DESIGN,         "Design the schema and relationships for: {goal}"),
        _TaskSpec("Implementation", TaskType.IMPLEMENTATION, "Create migrations and models for: {goal}"),
        _TaskSpec("Testing",        TaskType.TESTING,        "Test queries and data integrity for: {goal}"),
        _TaskSpec("Documentation",  TaskType.DOCUMENTATION,  "Document the schema for: {goal}"),
    ],
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


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """
    Rule-based goal decomposer.

    ``create_plan(goal)`` returns an ordered list of ``Task`` objects whose
    dependencies are pre-wired so that each task depends on its predecessor.
    The ``ExecutiveController`` passes this list to ``build_task_graph()``.

    The ``Planner`` has no state — it can be called repeatedly.
    """

    def create_plan(self, goal: str) -> list[Task]:
        """
        Decompose *goal* into an ordered list of ``Task`` objects.

        Tasks are linked sequentially: task N depends on task N-1.
        This linear chain is the safe default; future versions may return
        a branching structure (e.g. parallel research + design).

        Args:
            goal: Free-form user goal string (e.g. "Build a calculator").

        Returns:
            Ordered list of ``Task`` objects (first task has no dependencies).
        """
        if not goal or not goal.strip():
            raise ValueError("Goal must be a non-empty string.")

        template_name = self._infer_template(goal.strip())
        specs = _TEMPLATES[template_name]
        logger.info("Planner: goal=%r → template=%r (%d tasks)", goal, template_name, len(specs))

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
