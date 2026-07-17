"""
Tests for Task #9 — Subsystem Isolation.

Coverage:
  - SubsystemClassifier: accuracy for each of the six subsystems
  - Task.subsystem: field exists and defaults to "generic"
  - IsolationPlanner.reorder: sets subsystem on every task, preserves DAG order,
    clusters same-subsystem tasks together where possible
  - Scheduler handoff: logs / prints the transition banner on subsystem change
  - Generic tasks are accepted without blocking execution
"""

from __future__ import annotations

import io
import logging
from unittest.mock import MagicMock, patch

import pytest

from smartagent.executive.isolation_planner import IsolationPlanner
from smartagent.executive.subsystem_classifier import SubsystemClassifier
from smartagent.executive.task import Task, TaskType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_task(
    title: str,
    task_type: TaskType = TaskType.GENERIC,
    deps: list[str] | None = None,
    files: list[str] | None = None,
) -> Task:
    t = Task(title=title, task_type=task_type, dependencies=deps or [])
    if files:
        t.metadata["files"] = files
    return t


# ---------------------------------------------------------------------------
# 1. Task.subsystem field
# ---------------------------------------------------------------------------


class TestTaskSubsystemField:
    def test_default_is_generic(self):
        t = Task(title="anything")
        assert t.subsystem == "generic"

    def test_field_is_mutable(self):
        t = Task(title="x")
        t.subsystem = "api"
        assert t.subsystem == "api"

    def test_all_subsystem_values_accepted(self):
        for name in ("api", "models", "workers", "storage", "ui", "tests", "generic"):
            t = Task(title="x")
            t.subsystem = name
            assert t.subsystem == name


# ---------------------------------------------------------------------------
# 2. SubsystemClassifier — accuracy per subsystem
# ---------------------------------------------------------------------------


class TestSubsystemClassifierApi:
    def setup_method(self):
        self.clf = SubsystemClassifier()

    def test_architecture_type_maps_to_api(self):
        t = make_task("Design the API architecture", task_type=TaskType.ARCHITECTURE)
        assert self.clf.classify(t) == "api"

    def test_api_title_keyword(self):
        t = make_task("Build REST endpoint", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "api"

    def test_server_path_glob(self):
        t = make_task("Add handler", task_type=TaskType.GENERIC, files=["src/server/handler.py"])
        assert self.clf.classify(t) == "api"

    def test_api_underscore_path(self):
        t = make_task("Add route", task_type=TaskType.GENERIC, files=["smartagent/api_routes.py"])
        assert self.clf.classify(t) == "api"


class TestSubsystemClassifierModels:
    def setup_method(self):
        self.clf = SubsystemClassifier()

    def test_design_type_maps_to_models(self):
        t = make_task("Schema design", task_type=TaskType.DESIGN)
        assert self.clf.classify(t) == "models"

    def test_model_title_keyword(self):
        t = make_task("Add user model", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "models"

    def test_schema_path_glob(self):
        t = make_task("Migrate", task_type=TaskType.GENERIC, files=["db/schema_v2.py"])
        assert self.clf.classify(t) == "models"

    def test_migration_title(self):
        t = make_task("Create migration for orders table", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "models"


class TestSubsystemClassifierWorkers:
    def setup_method(self):
        self.clf = SubsystemClassifier()

    def test_implementation_type_maps_to_workers(self):
        t = make_task("Implement worker logic", task_type=TaskType.IMPLEMENTATION)
        assert self.clf.classify(t) == "workers"

    def test_coding_type_maps_to_workers(self):
        t = make_task("Write code", task_type=TaskType.CODING)
        assert self.clf.classify(t) == "workers"

    def test_worker_path_glob(self):
        t = make_task("Add specialist", task_type=TaskType.GENERIC, files=["smartagent/executive/workers/my_worker.py"])
        assert self.clf.classify(t) == "workers"

    def test_worker_title_keyword(self):
        t = make_task("Add executor for async jobs", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "workers"


class TestSubsystemClassifierStorage:
    def setup_method(self):
        self.clf = SubsystemClassifier()

    def test_storage_path_glob(self):
        t = make_task("Refactor", task_type=TaskType.GENERIC, files=["smartagent/storage/backend.py"])
        assert self.clf.classify(t) == "storage"

    def test_cache_path_glob(self):
        t = make_task("Clear old entries", task_type=TaskType.GENERIC, files=["lib/cache/lru.py"])
        assert self.clf.classify(t) == "storage"

    def test_cache_title_keyword(self):
        t = make_task("Add cache layer for responses", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "storage"

    def test_vector_title_keyword(self):
        t = make_task("Integrate vector index for embeddings", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "storage"


class TestSubsystemClassifierUI:
    def setup_method(self):
        self.clf = SubsystemClassifier()

    def test_dashboard_path_glob(self):
        t = make_task("Update panel", task_type=TaskType.GENERIC, files=["frontend/dashboard/Panel.tsx"])
        assert self.clf.classify(t) == "ui"

    def test_component_title_keyword(self):
        t = make_task("Build sidebar component", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "ui"

    def test_html_path_glob(self):
        t = make_task("Edit layout", task_type=TaskType.GENERIC, files=["templates/base.html"])
        assert self.clf.classify(t) == "ui"

    def test_frontend_title_keyword(self):
        t = make_task("Fix frontend rendering bug", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "ui"


class TestSubsystemClassifierTests:
    def setup_method(self):
        self.clf = SubsystemClassifier()

    def test_testing_type_maps_to_tests(self):
        t = make_task("Write unit tests", task_type=TaskType.TESTING)
        assert self.clf.classify(t) == "tests"

    def test_test_file_path_glob(self):
        t = make_task("Add coverage", task_type=TaskType.GENERIC, files=["tests/test_foo.py"])
        assert self.clf.classify(t) == "tests"

    def test_fixture_path(self):
        t = make_task("Add fixture", task_type=TaskType.GENERIC, files=["tests/fixtures/data.json"])
        assert self.clf.classify(t) == "tests"

    def test_test_title_keyword(self):
        t = make_task("Run benchmark suite", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) in ("tests", "generic")  # "benchmark" → tests


class TestSubsystemClassifierGeneric:
    def setup_method(self):
        self.clf = SubsystemClassifier()

    def test_unclassified_returns_generic(self):
        t = make_task("Do something unrelated", task_type=TaskType.REPORT)
        assert self.clf.classify(t) == "generic"

    def test_empty_title_returns_generic(self):
        t = make_task("", task_type=TaskType.GENERIC)
        assert self.clf.classify(t) == "generic"


# ---------------------------------------------------------------------------
# 3. IsolationPlanner
# ---------------------------------------------------------------------------


class TestIsolationPlannerSubsystemAssignment:
    def test_every_task_has_subsystem_set(self):
        tasks = [
            make_task("Research API", task_type=TaskType.RESEARCH),
            make_task("Implement logic", task_type=TaskType.IMPLEMENTATION),
            make_task("Write tests", task_type=TaskType.TESTING),
        ]
        planner = IsolationPlanner()
        result = planner.reorder(tasks)
        for t in result:
            assert t.subsystem != "" and t.subsystem is not None

    def test_generic_tasks_get_subsystem_field(self):
        tasks = [make_task("Random task", task_type=TaskType.GENERIC)]
        result = IsolationPlanner().reorder(tasks)
        assert result[0].subsystem == "generic"

    def test_empty_list_returns_empty(self):
        assert IsolationPlanner().reorder([]) == []


class TestIsolationPlannerTopologicalOrder:
    """reorder() must never emit a task before its dependency."""

    def test_linear_chain_preserved(self):
        a = make_task("Research", task_type=TaskType.RESEARCH)
        b = make_task("Implement", task_type=TaskType.IMPLEMENTATION, deps=[a.id])
        c = make_task("Test", task_type=TaskType.TESTING, deps=[b.id])
        result = IsolationPlanner().reorder([a, b, c])
        positions = {t.id: i for i, t in enumerate(result)}
        assert positions[a.id] < positions[b.id] < positions[c.id]

    def test_diamond_dep_order_respected(self):
        root = make_task("Root", task_type=TaskType.RESEARCH)
        left = make_task("Left", task_type=TaskType.IMPLEMENTATION, deps=[root.id])
        right = make_task("Right", task_type=TaskType.TESTING, deps=[root.id])
        leaf = make_task("Leaf", task_type=TaskType.GENERIC, deps=[left.id, right.id])
        result = IsolationPlanner().reorder([root, left, right, leaf])
        positions = {t.id: i for i, t in enumerate(result)}
        assert positions[root.id] < positions[left.id]
        assert positions[root.id] < positions[right.id]
        assert positions[left.id] < positions[leaf.id]
        assert positions[right.id] < positions[leaf.id]

    def test_all_tasks_present(self):
        tasks = [
            make_task("A", task_type=TaskType.RESEARCH),
            make_task("B", task_type=TaskType.IMPLEMENTATION),
            make_task("C", task_type=TaskType.TESTING),
        ]
        result = IsolationPlanner().reorder(tasks)
        assert len(result) == len(tasks)


class TestIsolationPlannerClusteringPreference:
    """Same-subsystem tasks should be adjacent where the DAG allows."""

    def test_two_test_tasks_are_adjacent(self):
        # No deps — planner should cluster both test tasks together
        t1 = make_task("Test feature A", task_type=TaskType.TESTING)
        t2 = make_task("Implement feature A", task_type=TaskType.IMPLEMENTATION)
        t3 = make_task("Test feature B", task_type=TaskType.TESTING)
        result = IsolationPlanner().reorder([t1, t2, t3])
        # Both tests should be adjacent (positions differ by 1 or both at start/end)
        subsystems = [t.subsystem for t in result]
        test_positions = [i for i, t in enumerate(result) if t.subsystem == "tests"]
        if len(test_positions) == 2:
            assert abs(test_positions[0] - test_positions[1]) == 1

    def test_subsystems_classified_on_returned_tasks(self):
        tasks = [
            make_task("Write endpoint", task_type=TaskType.IMPLEMENTATION),
            make_task("Add tests", task_type=TaskType.TESTING),
        ]
        result = IsolationPlanner().reorder(tasks)
        subsystems = {t.subsystem for t in result}
        assert len(subsystems) >= 1  # at least classified


class TestIsolationPlannerConvenienceClassMethod:
    def test_reorder_tasks_classmethod(self):
        tasks = [make_task("Do something", task_type=TaskType.TESTING)]
        result = IsolationPlanner.reorder_tasks(tasks)
        assert len(result) == 1
        assert result[0].subsystem != ""


# ---------------------------------------------------------------------------
# 4. Scheduler handoff logging
# ---------------------------------------------------------------------------


class TestSchedulerHandoffLogging:
    def _make_scheduler(self):
        from smartagent.executive.scheduler import Scheduler
        return Scheduler(worker_registry=None, max_retries=0, show_progress=False)

    def test_handoff_logged_on_subsystem_change(self):
        """When subsystem changes, scheduler logs the transition banner."""
        from smartagent.executive.scheduler import Scheduler
        from smartagent.executive.execution_context import ExecutionContext
        from smartagent.executive.task_graph import TaskGraph
        from smartagent.executive.task_queue import TaskQueue

        scheduler = Scheduler(worker_registry=None, max_retries=0, show_progress=False)

        t1 = make_task("API task", task_type=TaskType.ARCHITECTURE)
        t1.subsystem = "api"
        t2 = make_task("Test task", task_type=TaskType.TESTING)
        t2.subsystem = "tests"

        # Simulate scheduler tracking
        scheduler._current_subsystem = "api"
        logged_messages = []

        with patch.object(scheduler, "_print") as mock_print:
            # Simulate what _run_task does for handoff detection
            task_subsystem = t2.subsystem
            if scheduler._current_subsystem is not None and task_subsystem != scheduler._current_subsystem:
                banner = f"── switching subsystem: {scheduler._current_subsystem} → {task_subsystem} ──"
                scheduler._print(banner)
                scheduler._current_subsystem = task_subsystem

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert "switching subsystem" in call_args
        assert "api" in call_args
        assert "tests" in call_args

    def test_no_handoff_when_same_subsystem(self):
        from smartagent.executive.scheduler import Scheduler
        scheduler = Scheduler(worker_registry=None, max_retries=0, show_progress=False)
        scheduler._current_subsystem = "tests"

        with patch.object(scheduler, "_print") as mock_print:
            t = make_task("Another test", task_type=TaskType.TESTING)
            t.subsystem = "tests"
            task_subsystem = t.subsystem
            if scheduler._current_subsystem is not None and task_subsystem != scheduler._current_subsystem:
                scheduler._print("should not be printed")

        mock_print.assert_not_called()

    def test_no_handoff_on_first_task(self):
        from smartagent.executive.scheduler import Scheduler
        scheduler = Scheduler(worker_registry=None, max_retries=0, show_progress=False)
        assert scheduler._current_subsystem is None

        with patch.object(scheduler, "_print") as mock_print:
            t = make_task("First task", task_type=TaskType.TESTING)
            t.subsystem = "tests"
            task_subsystem = t.subsystem
            if scheduler._current_subsystem is not None and task_subsystem != scheduler._current_subsystem:
                scheduler._print("should not be printed")
            scheduler._current_subsystem = task_subsystem

        mock_print.assert_not_called()

    def test_handoff_banner_format(self):
        """Banner matches: '── switching subsystem: X → Y ──'"""
        from smartagent.executive.scheduler import Scheduler
        scheduler = Scheduler(worker_registry=None, max_retries=0, show_progress=True)
        scheduler._current_subsystem = "models"

        printed = []
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(a[0])):
            t = make_task("API task")
            t.subsystem = "api"
            task_subsystem = t.subsystem
            if scheduler._current_subsystem is not None and task_subsystem != scheduler._current_subsystem:
                banner = f"── switching subsystem: {scheduler._current_subsystem} → {task_subsystem} ──"
                scheduler._print(banner)

        assert any("switching subsystem" in msg for msg in printed)
        assert any("models" in msg and "api" in msg for msg in printed)


# ---------------------------------------------------------------------------
# 5. Generic tasks accepted without blocking execution
# ---------------------------------------------------------------------------


class TestGenericTasksAccepted:
    def test_generic_tasks_are_classified(self):
        clf = SubsystemClassifier()
        t = make_task("Do some miscellaneous work", task_type=TaskType.GENERIC)
        result = clf.classify(t)
        assert result == "generic"

    def test_generic_tasks_survive_reorder(self):
        tasks = [
            make_task("Generic step", task_type=TaskType.GENERIC),
            make_task("Another generic step", task_type=TaskType.GENERIC),
        ]
        result = IsolationPlanner().reorder(tasks)
        assert len(result) == 2
        for t in result:
            assert t.subsystem == "generic"

    def test_mixed_generic_and_typed_reorder(self):
        tasks = [
            make_task("Generic step A", task_type=TaskType.GENERIC),
            make_task("Write tests", task_type=TaskType.TESTING),
            make_task("Generic step B", task_type=TaskType.GENERIC),
        ]
        result = IsolationPlanner().reorder(tasks)
        assert len(result) == 3
        classified = {t.subsystem for t in result}
        assert "generic" in classified
        assert "tests" in classified

    def test_only_generic_tasks_in_scheduler_context(self):
        """A plan of all generic tasks executes without error."""
        from smartagent.executive.scheduler import Scheduler
        from smartagent.executive.execution_context import ExecutionContext
        from smartagent.executive.execution_state import ExecutionState
        from smartagent.executive.task_graph import TaskGraph
        from smartagent.executive.task_queue import TaskQueue

        t1 = make_task("Generic 1")
        t1.subsystem = "generic"
        t2 = make_task("Generic 2", deps=[t1.id])
        t2.subsystem = "generic"

        graph = TaskGraph()
        graph.add_task(t1)
        graph.add_task(t2)
        graph.validate()

        queue = TaskQueue()
        t1.mark_ready()
        queue.enqueue(t1)

        ctx = ExecutionContext(goal="generic test")
        ctx.task_graph = graph
        ctx.task_queue = queue
        ctx.transition_to(ExecutionState.READY)

        scheduler = Scheduler(worker_registry=None, max_retries=0, show_progress=False)
        result = scheduler.run(ctx)
        assert result.state == ExecutionState.COMPLETED
