"""
SubsystemClassifier — maps tasks to one of six logical subsystems.

Subsystems:
    api      — API layer, endpoints, server code, architecture tasks
    models   — Data models, schemas, ORM, database tasks
    workers  — Worker classes, specialist executors, job processors
    storage  — Storage backends, file I/O, caching, persistence
    ui       — Frontend, dashboard, templates, CSS/HTML
    tests    — Test suites, fixtures, validation, quality runners

Any task that does not match a named subsystem falls through to ``"generic"``.
"""

from __future__ import annotations

import fnmatch
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.executive.task import Task


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Each entry maps a subsystem name to a dict with:
#   "task_types"  — set of TaskType *values* (strings) that belong here
#   "path_globs"  — file-path glob patterns (matched with fnmatch)
#   "title_words" — case-insensitive substrings matched against task title
_SUBSYSTEM_PATTERNS: dict[str, dict] = {
    "api": {
        "task_types": {"architecture", "research"},
        "path_globs": [
            "*/server/*", "*/api_*", "*/api/*", "*_api.py",
            "*/endpoints/*", "*/routes/*", "*/views/*",
        ],
        "title_words": [
            "api", "endpoint", "route", "server", "backend",
            "rest", "graphql", "webhook", "microservice", "architecture",
        ],
    },
    "models": {
        "task_types": {"design"},
        "path_globs": [
            "*/models/*", "*/model_*", "*_model.py",
            "*/schema*", "*/migration*", "*/orm/*",
        ],
        "title_words": [
            "model", "schema", "migration", "database", "orm",
            "table", "relation", "entity", "data model",
        ],
    },
    "workers": {
        "task_types": {"implementation", "coding"},
        "path_globs": [
            "*/workers/*", "*_worker.py", "*/jobs/*", "*/tasks/*",
            "*/executor*", "*/processor*",
        ],
        "title_words": [
            "worker", "executor", "processor", "job", "task handler",
            "specialist", "mixin", "dispatcher",
        ],
    },
    "storage": {
        "task_types": set(),
        "path_globs": [
            "*/storage/*", "*_storage.py", "*/cache/*", "*_cache.py",
            "*/repository/*", "*/persistence/*", "*/db/*", "*/database/*",
        ],
        "title_words": [
            "storage", "cache", "persist", "repository", "file store",
            "object store", "vector", "index", "bucket",
        ],
    },
    "ui": {
        "task_types": set(),
        "path_globs": [
            "*/ui/*", "*/frontend/*", "*/dashboard/*", "*/templates/*",
            "*.html", "*.css", "*.tsx", "*.jsx", "*/components/*",
        ],
        "title_words": [
            "ui", "frontend", "dashboard", "component", "template",
            "html", "css", "panel", "view", "widget", "page",
        ],
    },
    "tests": {
        "task_types": {"testing"},
        "path_globs": [
            "tests/*", "test_*.py", "*_test.py", "*/fixtures/*",
            "*/conftest*",
        ],
        "title_words": [
            "test", "testing", "spec", "fixture", "validation",
            "quality", "coverage", "assert", "benchmark",
        ],
    },
}


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class SubsystemClassifier:
    """
    Classify a ``Task`` into one of six subsystems based on its type, title,
    and file paths stored in ``task.metadata.get("files", [])``.

    Returns ``"generic"`` when no pattern matches.
    """

    # Priority order: subsystems are checked in this order; first match wins.
    _PRIORITY: list[str] = ["tests", "api", "models", "workers", "storage", "ui"]

    def classify(self, task: "Task") -> str:
        """
        Return the subsystem name for *task*.

        Matching order (first match wins):
          1. TaskType value matches a subsystem's ``task_types`` set.
          2. Any path in ``task.metadata["files"]`` matches a glob pattern.
          3. Any ``title_words`` entry appears (case-insensitive) in the title.
        """
        task_type_val = task.task_type.value  # e.g. "testing", "implementation"
        title_lower = task.title.lower()
        files: list[str] = task.metadata.get("files", [])

        for subsystem in self._PRIORITY:
            pattern = _SUBSYSTEM_PATTERNS[subsystem]

            # 1. Task-type match
            if task_type_val in pattern["task_types"]:
                return subsystem

            # 2. File-path glob match
            for file_path in files:
                for glob in pattern["path_globs"]:
                    if fnmatch.fnmatch(file_path, glob):
                        return subsystem

            # 3. Title keyword match (whole-word to avoid false positives like
            #    "specialist" matching "spec")
            for word in pattern["title_words"]:
                # Multi-word phrases: plain substring is fine (space is boundary).
                # Single words: require word boundaries.
                if " " in word:
                    if word in title_lower:
                        return subsystem
                else:
                    if re.search(r"\b" + re.escape(word) + r"\b", title_lower):
                        return subsystem

        return "generic"


# Singleton for convenience — callers can ``from ... import default_classifier``
default_classifier = SubsystemClassifier()
