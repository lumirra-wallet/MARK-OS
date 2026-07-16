"""
Task Complexity Classifier.

Classifies a free-text goal into one of five levels:
    trivial    — single file / single function (hello.py, calculator, add function)
    small      — simple app (REST API, Flask CRUD, FastAPI endpoint, CLI tool)
    medium     — multi-feature app (Todo app, Blog, Chat app, Auth system)
    large      — complex system (SaaS, full-stack + auth + DB + payments)
    enterprise — multi-service platform (CRM, ERP, data platform)

The complexity drives which Planner template is selected:
    trivial    → Implementation + Testing only (2 AI calls)
    small      → Implementation + Testing (same, slightly richer)
    medium     → Research + Implementation + Testing + Review (4 calls)
    large      → full pipeline — Research + Architecture + Impl + Test + Review (5 calls)
    enterprise → full pipeline + Documentation (6 calls)

Usage::

    from smartagent.performance.complexity import classify_complexity, TaskComplexity

    level = classify_complexity("Build a FastAPI CRUD API")
    # → TaskComplexity.SMALL

    level.value   # → "small"
    level.skip_research   # → True (no research call needed)
"""

from __future__ import annotations

import re
from enum import Enum


class TaskComplexity(str, Enum):
    """Task complexity levels — ordered from simplest to most complex."""

    TRIVIAL = "trivial"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    ENTERPRISE = "enterprise"

    @property
    def skip_research(self) -> bool:
        """True when the research worker should be omitted for this complexity."""
        return self in (TaskComplexity.TRIVIAL, TaskComplexity.SMALL)

    @property
    def skip_review(self) -> bool:
        """True when the review worker should be omitted for this complexity."""
        return self in (TaskComplexity.TRIVIAL, TaskComplexity.SMALL)

    @property
    def skip_documentation(self) -> bool:
        """True when the documentation worker should be omitted for this complexity."""
        return self in (TaskComplexity.TRIVIAL, TaskComplexity.SMALL, TaskComplexity.MEDIUM)

    @property
    def max_prior_chars(self) -> int:
        """Maximum characters to inject from prior worker results."""
        return {
            TaskComplexity.TRIVIAL: 200,
            TaskComplexity.SMALL: 300,
            TaskComplexity.MEDIUM: 500,
            TaskComplexity.LARGE: 800,
            TaskComplexity.ENTERPRISE: 1200,
        }[self]


# ---------------------------------------------------------------------------
# Classification rules — ordered from most specific to most general
# ---------------------------------------------------------------------------

# Trivial patterns: single-file, single-function goals
_TRIVIAL_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\bhello[\s._-]?(?:world|py)?\b",
        r"\bcreate\s+hello",
        r"\bwrite\s+(?:a\s+)?(?:simple\s+)?calculator\b",
        r"\bbuild\s+(?:a\s+)?(?:simple\s+)?calculator\b",
        r"\bcalculator\s+(?:cli|script|program|app)?\b",
        r"\badd\s+(?:a\s+)?(?:single\s+)?function\b",
        r"\brename\s+(?:a\s+)?(?:variable|function|class)\b",
        r"\bcreate\s+(?:a\s+)?requirements\.txt\b",
        r"\bcreate\s+(?:a\s+)?\.(gitignore|env|editorconfig)\b",
        r"\badd\s+(?:a\s+)?readme\b",
        r"\bcreate\s+(?:a\s+)?readme\b",
        r"\bwrite\s+(?:a\s+)?(?:simple\s+)?(?:python\s+)?script\s+(?:that|to)\s+\w+\s+\w+\s*$",
        r"\bfix\s+(?:a\s+)?(?:single\s+)?(?:bug|typo|error|issue)\b",
        r"\bprint\s+hello\b",
        r"\bfibonacci\b",
        r"\bfactorial\b",
        r"\breverse\s+(?:a\s+)?string\b",
        r"\bpalindrome\b",
        r"\bconvert\s+celsius\b",
        r"\bconvert\s+fahrenheit\b",
    ]
]

# Enterprise patterns — checked before large
_ENTERPRISE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\bcrm\b",
        r"\berp\b",
        r"\benterprise\b",
        r"\bmulti[\s-]?tenant\b",
        r"\bmicro[\s-]?service",
        r"\bdata\s+platform\b",
        r"\bml\s+platform\b",
        r"\bai\s+platform\b",
        r"\borchestrat",
    ]
]

# Large patterns
_LARGE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\bsaas\b",
        r"\bfull[\s-]?stack\b",
        r"\bplatform\b",
        r"\bdashboard\b",
        r"\bsystem\s+(?:with|that)\b",
        r"\bauth(?:entication)?\s+(?:and|with|plus)\s+\w+",  # auth AND something
        r"\bpayment",
        r"\bsubscription\b",
        r"\bproject\s+management\b",
        r"\bworkflow\b",
        r"\bpipeline\b",
        r"\bmonitor",
        r"\banalytic",
        r"\breporting\b",
    ]
]

# Medium patterns — multi-feature app
_MEDIUM_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\btodo\s+app\b",
        r"\bblog\b",
        r"\bchat\s+app\b",
        r"\bchat\s+system\b",
        r"\bsocial\b",
        r"\bforum\b",
        r"\bportfolio\b",
        r"\be[\s-]?commerce\b",
        r"\bshop\b",
        r"\bstore\b",
        r"\bauth(?:entication)?\s+system\b",
        r"\buser\s+management\b",
        r"\bnotification",
        r"\bdatabase\s+(?:and|with)\b",
    ]
]


def classify_complexity(goal: str) -> TaskComplexity:
    """
    Classify a goal string into a :class:`TaskComplexity` level.

    Args:
        goal: Free-text goal from the user (e.g. ``"Build a calculator CLI"``).

    Returns:
        A :class:`TaskComplexity` enum member.

    Examples::

        >>> classify_complexity("Create hello.py")
        <TaskComplexity.TRIVIAL: 'trivial'>

        >>> classify_complexity("Build a FastAPI REST API with CRUD endpoints")
        <TaskComplexity.SMALL: 'small'>

        >>> classify_complexity("Build a SaaS billing platform")
        <TaskComplexity.LARGE: 'large'>
    """
    if not goal or not goal.strip():
        return TaskComplexity.MEDIUM

    # Trivial: single-file / single-function — check first, highest priority
    for pattern in _TRIVIAL_PATTERNS:
        if pattern.search(goal):
            return TaskComplexity.TRIVIAL

    # Enterprise: before large so "enterprise CRM" routes correctly
    for pattern in _ENTERPRISE_PATTERNS:
        if pattern.search(goal):
            return TaskComplexity.ENTERPRISE

    # Large: complex multi-domain system
    for pattern in _LARGE_PATTERNS:
        if pattern.search(goal):
            return TaskComplexity.LARGE

    # Medium: multi-feature app
    for pattern in _MEDIUM_PATTERNS:
        if pattern.search(goal):
            return TaskComplexity.MEDIUM

    # Word-count heuristic: longer goals tend to be more complex
    words = len(goal.split())
    if words <= 5:
        return TaskComplexity.SMALL
    if words <= 12:
        return TaskComplexity.SMALL
    if words <= 25:
        return TaskComplexity.MEDIUM

    return TaskComplexity.MEDIUM
