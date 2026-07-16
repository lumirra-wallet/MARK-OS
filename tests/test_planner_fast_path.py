"""
Tests for v2.0 Planner complexity-aware plan selection.

Verifies that trivial and small goals produce 2-task plans, and that
larger goals use the full pipeline.
"""

import pytest
from smartagent.executive.planner import Planner
from smartagent.executive.task import TaskType


@pytest.fixture
def planner():
    return Planner()


class TestTrivialPlan:
    """Trivial complexity → 2 tasks: Implementation + Testing only."""

    def test_trivial_hello_world(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        assert len(tasks) == 2

    def test_trivial_task_types(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        types = {t.task_type for t in tasks}
        assert TaskType.IMPLEMENTATION in types
        assert TaskType.TESTING in types

    def test_trivial_no_research(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        types = {t.task_type for t in tasks}
        assert TaskType.RESEARCH not in types

    def test_trivial_no_review(self, planner):
        tasks = planner.create_plan("Build a calculator", complexity="trivial")
        types = {t.task_type for t in tasks}
        assert TaskType.REVIEW not in types

    def test_small_uses_keyword_template(self, planner):
        # "small" no longer applies the trivial fast-path; keyword matching applies
        tasks = planner.create_plan("Build a REST API", complexity="small")
        assert len(tasks) >= 2


class TestMediumPlan:
    """Medium complexity → up to 4 tasks (no Design/Documentation)."""

    def test_medium_fewer_than_full(self, planner):
        tasks = planner.create_plan("Build a todo app", complexity="medium")
        # Medium should have fewer tasks than the full 5-step default
        assert len(tasks) <= 5

    def test_medium_has_implementation(self, planner):
        tasks = planner.create_plan("Build a blog app", complexity="medium")
        types = {t.task_type for t in tasks}
        assert TaskType.IMPLEMENTATION in types

    def test_medium_has_testing(self, planner):
        tasks = planner.create_plan("Build a chat app", complexity="medium")
        types = {t.task_type for t in tasks}
        assert TaskType.TESTING in types


class TestLargePlan:
    """Large/enterprise complexity → full pipeline."""

    def test_large_full_pipeline(self, planner):
        tasks = planner.create_plan("Build a SaaS billing platform", complexity="large")
        assert len(tasks) >= 4

    def test_enterprise_full_pipeline(self, planner):
        tasks = planner.create_plan("Build a CRM system", complexity="enterprise")
        assert len(tasks) >= 4


class TestAutoDetection:
    """Complexity is passed explicitly by the caller (DevLoop/SoftwareEngineer)."""

    def test_explicit_trivial_gives_two_tasks(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        assert len(tasks) == 2

    def test_explicit_trivial_calculator(self, planner):
        tasks = planner.create_plan("Write a calculator", complexity="trivial")
        assert len(tasks) == 2

    def test_returns_task_list(self, planner):
        tasks = planner.create_plan("Build something")
        assert isinstance(tasks, list)
        assert len(tasks) >= 2

    def test_default_medium_uses_keyword_matching(self, planner):
        # Default (medium) uses keyword-based template, not trivial fast-path
        tasks = planner.create_plan("Build a calculator")
        assert len(tasks) >= 3  # default template


class TestPlannerDependencies:
    """Each task depends on its predecessor — linear chain."""

    def test_first_task_no_deps(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        assert tasks[0].dependencies == []

    def test_second_task_depends_on_first(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        assert tasks[0].id in tasks[1].dependencies

    def test_chain_valid_for_medium(self, planner):
        tasks = planner.create_plan("Build a REST API", complexity="large")
        for i in range(1, len(tasks)):
            assert tasks[i - 1].id in tasks[i].dependencies


class TestAvailableTemplates:
    def test_includes_trivial(self, planner):
        assert "trivial" in planner.available_templates()

    def test_includes_default(self, planner):
        assert "default" in planner.available_templates()
