"""
IsolationPlanner — reorders a flat task list so same-subsystem tasks are
adjacent while preserving topological (dependency) order.

Usage::

    from smartagent.executive.isolation_planner import IsolationPlanner

    tasks = planner.create_plan(goal)
    IsolationPlanner.reorder(tasks)   # mutates subsystem field; returns reordered list

After ``reorder()``:
  - Every task has its ``subsystem`` field set (never empty / None).
  - Tasks belonging to the same subsystem are adjacent where DAG order allows.
  - All dependency relationships are honoured — a task never appears before
    its dependencies.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

from smartagent.executive.subsystem_classifier import SubsystemClassifier
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.task import Task

logger = get_logger(__name__)


class IsolationPlanner:
    """
    Groups tasks by subsystem while respecting topological order.

    The algorithm is a *subsystem-biased topological sort*:

    1.  Classify every task and assign its ``subsystem`` field.
    2.  Compute in-degree (how many dependencies each task has in the set).
    3.  Seed the ready-queue with all zero-in-degree tasks.
    4.  Pick the next task greedily: prefer a task whose subsystem matches the
        last emitted task (to minimise handoffs).  When none match, pick the
        first available task (stable, preserves relative input order).
    5.  After emitting a task, decrement dependents' in-degrees and enqueue
        newly unblocked tasks.

    The result is a valid topological ordering with subsystems clustered
    together as tightly as the DAG allows.
    """

    def __init__(self, classifier: SubsystemClassifier | None = None) -> None:
        self._classifier = classifier or SubsystemClassifier()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reorder(self, tasks: list["Task"]) -> list["Task"]:
        """
        Classify and reorder *tasks* in-place (subsystem fields are mutated).

        Returns the reordered list (a new list object; originals are mutated).
        Raises ``ValueError`` if the dependency graph contains a cycle.
        """
        if not tasks:
            return []

        # Step 1 — classify
        for task in tasks:
            task.subsystem = self._classifier.classify(task)

        logger.debug(
            "IsolationPlanner: classified %d tasks: %s",
            len(tasks),
            {t.title: t.subsystem for t in tasks},
        )

        # Step 2 — build adjacency structures (only within this task set)
        task_by_id: dict[str, "Task"] = {t.id: t for t in tasks}
        in_degree: dict[str, int] = {t.id: 0 for t in tasks}
        dependents: dict[str, list[str]] = defaultdict(list)  # dep_id → [task_id]

        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id in task_by_id:  # only count internal deps
                    in_degree[task.id] += 1
                    dependents[dep_id].append(task.id)

        # Step 3 — seed ready queue (stable order = input order)
        ready: deque["Task"] = deque(
            t for t in tasks if in_degree[t.id] == 0
        )

        # Step 4/5 — greedy subsystem-biased emit
        result: list["Task"] = []
        current_subsystem: str | None = None

        while ready:
            # Prefer a task matching current_subsystem; fall back to first ready
            chosen: "Task" | None = None
            if current_subsystem is not None:
                for candidate in ready:
                    if candidate.subsystem == current_subsystem:
                        chosen = candidate
                        break

            if chosen is None:
                chosen = ready[0]

            ready.remove(chosen)
            result.append(chosen)
            current_subsystem = chosen.subsystem

            # Unblock dependents
            for dep_task_id in dependents[chosen.id]:
                in_degree[dep_task_id] -= 1
                if in_degree[dep_task_id] == 0:
                    ready.append(task_by_id[dep_task_id])

        if len(result) != len(tasks):
            raise ValueError(
                "IsolationPlanner: dependency cycle detected — "
                f"only {len(result)}/{len(tasks)} tasks could be ordered."
            )

        logger.info(
            "IsolationPlanner: reordered %d tasks across subsystems: %s",
            len(result),
            [t.subsystem for t in result],
        )
        return result

    # ------------------------------------------------------------------
    # Convenience class-method so callers don't need to instantiate
    # ------------------------------------------------------------------

    @classmethod
    def reorder_tasks(cls, tasks: list["Task"]) -> list["Task"]:
        """Convenience wrapper: ``IsolationPlanner.reorder_tasks(tasks)``."""
        return cls().reorder(tasks)
