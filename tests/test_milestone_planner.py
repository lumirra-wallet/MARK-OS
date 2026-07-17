"""
Tests for the MilestonePlanner and Milestone dataclass.

Covers:
  - large/enterprise goals produce ≥ 2 milestones
  - trivial/small/medium goals produce exactly 1 milestone
  - task count within milestones is non-zero
  - milestone phases are sequential integers starting at 1
  - milestone metadata shape is stored correctly in context
  - backward compatibility: direct Planner.create_plan() calls are unchanged
  - Milestone.to_dict() shape
  - Orchestrator milestone integration (store in context.metadata)
"""

from __future__ import annotations

import pytest

from smartagent.executive.milestone_planner import Milestone, MilestonePlanner
from smartagent.executive.planner import Planner
from smartagent.executive.task import Task, TaskType, TaskStatus
from smartagent.executive.orchestrator import Orchestrator
from smartagent.executive.execution_state import ExecutionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def planner():
    return Planner()


@pytest.fixture
def milestone_planner():
    return MilestonePlanner()


@pytest.fixture
def orchestrator():
    from smartagent.executive.scheduler import Scheduler
    sched = Scheduler(show_progress=False)
    return Orchestrator(scheduler=sched)


# ---------------------------------------------------------------------------
# Milestone dataclass
# ---------------------------------------------------------------------------


class TestMilestoneDataclass:
    def test_milestone_has_phase(self):
        m = Milestone(phase=1, title="Foundation", objective="do setup", tasks=[])
        assert m.phase == 1

    def test_milestone_has_title(self):
        m = Milestone(phase=2, title="Build", objective="implement", tasks=[])
        assert m.title == "Build"

    def test_milestone_has_objective(self):
        m = Milestone(phase=1, title="X", objective="my objective", tasks=[])
        assert "my objective" in m.objective

    def test_milestone_tasks_default_empty(self):
        m = Milestone(phase=1, title="X", objective="y")
        assert m.tasks == []

    def test_to_dict_shape(self):
        task = Task(title="Impl", task_type=TaskType.IMPLEMENTATION)
        m = Milestone(phase=1, title="Foundation", objective="setup", tasks=[task])
        d = m.to_dict()
        assert d["phase"] == 1
        assert d["title"] == "Foundation"
        assert d["objective"] == "setup"
        assert task.id in d["task_ids"]
        assert "Impl" in d["task_titles"]
        assert d["task_count"] == 1
        assert "status" in d

    def test_to_dict_status_pending(self):
        task = Task(title="T", task_type=TaskType.IMPLEMENTATION)
        m = Milestone(phase=1, title="X", objective="y", tasks=[task])
        assert m.to_dict()["status"] == "pending"

    def test_to_dict_status_completed(self):
        task = Task(title="T", task_type=TaskType.IMPLEMENTATION)
        task.mark_ready()
        task.mark_running()
        task.mark_completed("done")
        m = Milestone(phase=1, title="X", objective="y", tasks=[task])
        assert m.to_dict()["status"] == "completed"

    def test_repr_contains_phase_and_title(self):
        m = Milestone(phase=3, title="QA", objective="test", tasks=[])
        r = repr(m)
        assert "3" in r
        assert "QA" in r


# ---------------------------------------------------------------------------
# MilestonePlanner — trivial / small / medium → single milestone
# ---------------------------------------------------------------------------


class TestSingleMilestone:
    def test_trivial_produces_one_milestone(self, milestone_planner):
        milestones = milestone_planner.create_milestones("hello.py", complexity="trivial")
        assert len(milestones) == 1

    def test_small_produces_one_milestone(self, milestone_planner):
        milestones = milestone_planner.create_milestones("Build a REST API", complexity="small")
        assert len(milestones) == 1

    def test_medium_produces_one_milestone(self, milestone_planner):
        milestones = milestone_planner.create_milestones("Build a blog app", complexity="medium")
        assert len(milestones) == 1

    def test_no_complexity_produces_one_milestone(self, milestone_planner):
        milestones = milestone_planner.create_milestones("Build something")
        assert len(milestones) == 1

    def test_single_milestone_phase_is_one(self, milestone_planner):
        milestones = milestone_planner.create_milestones("Create hello.py", complexity="trivial")
        assert milestones[0].phase == 1

    def test_single_milestone_has_tasks(self, milestone_planner):
        milestones = milestone_planner.create_milestones("Create hello.py", complexity="trivial")
        assert len(milestones[0].tasks) > 0

    def test_single_milestone_title_is_string(self, milestone_planner):
        milestones = milestone_planner.create_milestones("Do something", complexity="medium")
        assert isinstance(milestones[0].title, str)
        assert milestones[0].title  # non-empty


# ---------------------------------------------------------------------------
# MilestonePlanner — large / enterprise → multiple milestones
# ---------------------------------------------------------------------------


class TestMultipleMilestones:
    def test_large_produces_at_least_two_milestones(self, milestone_planner):
        milestones = milestone_planner.create_milestones(
            "Build a SaaS billing platform", complexity="large"
        )
        assert len(milestones) >= 2

    def test_enterprise_produces_at_least_two_milestones(self, milestone_planner):
        milestones = milestone_planner.create_milestones(
            "Build a global CRM with analytics", complexity="enterprise"
        )
        assert len(milestones) >= 2

    def test_enterprise_api_goal_produces_milestones(self, milestone_planner):
        milestones = milestone_planner.create_milestones(
            "Build a REST API platform with authentication and documentation",
            complexity="enterprise",
        )
        assert len(milestones) >= 2

    def test_phases_are_sequential_from_one(self, milestone_planner):
        milestones = milestone_planner.create_milestones(
            "Build a SaaS billing platform", complexity="large"
        )
        phases = [m.phase for m in milestones]
        assert phases == list(range(1, len(milestones) + 1))

    def test_all_milestones_have_non_empty_tasks(self, milestone_planner):
        milestones = milestone_planner.create_milestones(
            "Build a SaaS billing platform", complexity="large"
        )
        for m in milestones:
            assert len(m.tasks) > 0, f"Milestone {m.phase} has no tasks"

    def test_all_tasks_covered(self, milestone_planner):
        """Total task count across milestones equals the flat plan count."""
        goal = "Build a database schema with documentation"
        milestones = milestone_planner.create_milestones(goal, complexity="enterprise")
        # Use a fresh planner with the same goal/complexity to get the expected count
        flat_count = len(Planner().create_plan(goal, complexity="enterprise"))
        milestone_count = sum(len(m.tasks) for m in milestones)
        assert milestone_count == flat_count

    def test_milestone_titles_are_non_empty_strings(self, milestone_planner):
        milestones = milestone_planner.create_milestones(
            "Build a CRM platform", complexity="enterprise"
        )
        for m in milestones:
            assert isinstance(m.title, str)
            assert m.title.strip()

    def test_first_task_of_each_milestone_has_no_cross_deps(self, milestone_planner):
        """The first task of each milestone must have no dependencies
        (cross-milestone deps are stripped so each milestone is self-contained)."""
        milestones = milestone_planner.create_milestones(
            "Build a SaaS billing platform", complexity="large"
        )
        for m in milestones:
            assert m.tasks[0].dependencies == [], (
                f"Milestone {m.phase} first task still has cross-deps"
            )


# ---------------------------------------------------------------------------
# MilestonePlanner — error handling
# ---------------------------------------------------------------------------


class TestMilestonePlannerErrors:
    def test_empty_goal_raises(self, milestone_planner):
        with pytest.raises(ValueError):
            milestone_planner.create_milestones("")

    def test_whitespace_goal_raises(self, milestone_planner):
        with pytest.raises(ValueError):
            milestone_planner.create_milestones("   ")


# ---------------------------------------------------------------------------
# Backward compatibility — direct Planner.create_plan() is unchanged
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_planner_trivial_still_returns_list(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        assert isinstance(tasks, list)
        assert len(tasks) == 2

    def test_planner_medium_unchanged(self, planner):
        tasks = planner.create_plan("Build a blog", complexity="medium")
        assert len(tasks) >= 2

    def test_planner_large_unchanged(self, planner):
        tasks = planner.create_plan("Build a SaaS platform", complexity="large")
        assert len(tasks) >= 4

    def test_planner_no_complexity_unchanged(self, planner):
        tasks = planner.create_plan("Build a REST API")
        assert len(tasks) >= 3

    def test_planner_returns_task_objects(self, planner):
        tasks = planner.create_plan("Create hello.py", complexity="trivial")
        assert all(isinstance(t, Task) for t in tasks)


# ---------------------------------------------------------------------------
# Orchestrator milestone metadata integration
# ---------------------------------------------------------------------------


class TestOrchestratorMilestoneMetadata:
    def test_context_has_milestones_key(self, orchestrator):
        ctx = orchestrator.execute_goal("Create hello.py", complexity="trivial")
        assert "milestones" in ctx.metadata

    def test_milestones_metadata_is_list(self, orchestrator):
        ctx = orchestrator.execute_goal("Create hello.py", complexity="trivial")
        assert isinstance(ctx.metadata["milestones"], list)

    def test_single_milestone_metadata_shape(self, orchestrator):
        ctx = orchestrator.execute_goal("Create hello.py", complexity="trivial")
        m = ctx.metadata["milestones"][0]
        assert "phase" in m
        assert "title" in m
        assert "objective" in m
        assert "task_ids" in m
        assert "task_count" in m
        assert "status" in m

    def test_large_goal_metadata_has_multiple_milestones(self, orchestrator):
        ctx = orchestrator.execute_goal(
            "Build a SaaS billing platform", complexity="large"
        )
        assert len(ctx.metadata["milestones"]) >= 2

    def test_active_milestone_tracked_in_metadata(self, orchestrator):
        ctx = orchestrator.execute_goal("Create hello.py", complexity="trivial")
        # After execution, active_milestone should be set to the last milestone's phase
        assert "active_milestone" in ctx.metadata
        assert isinstance(ctx.metadata["active_milestone"], int)


# ---------------------------------------------------------------------------
# Orchestrator stop_on_failure=False — early failure must not hide as success
# ---------------------------------------------------------------------------


class _AlwaysFailWorker:
    """Worker that always raises to simulate a milestone failure."""

    def __init__(self, task, context):
        self._task = task
        self._context = context

    def execute(self):
        raise RuntimeError("Simulated worker failure")


class _AlwaysPassWorker:
    """Worker that always succeeds."""

    def __init__(self, task, context):
        self._task = task
        self._context = context

    def execute(self):
        return "ok"


class TestOrchestratorFailureAggregation:
    """
    Regression tests ensuring that an early milestone failure propagates to
    the final ExecutionContext state even when stop_on_failure=False.
    """

    def _make_orchestrator_with_failing_first_milestone(self, stop_on_failure: bool):
        """
        Build an Orchestrator whose first-milestone tasks will fail because the
        WorkerRegistry maps every task type to a worker that raises.
        """
        from smartagent.executive.scheduler import Scheduler
        from smartagent.executive.worker_registry import WorkerRegistry

        registry = WorkerRegistry()
        # Register the failing worker for all task types
        from smartagent.executive.task import TaskType
        for tt in TaskType:
            registry.register(tt, _AlwaysFailWorker)

        sched = Scheduler(
            worker_registry=registry,
            max_retries=0,
            show_progress=False,
        )
        return Orchestrator(
            scheduler=sched,
            worker_registry=registry,
            stop_on_failure=stop_on_failure,
        )

    def test_stop_on_failure_true_first_milestone_fails_final_state_failed(self):
        orch = self._make_orchestrator_with_failing_first_milestone(stop_on_failure=True)
        ctx = orch.execute_goal("Build a SaaS platform", complexity="large")
        assert ctx.state == ExecutionState.FAILED

    def test_stop_on_failure_false_early_failure_final_state_still_failed(self):
        """
        Core regression: even when stop_on_failure=False so later milestones
        can still run, the final state must be FAILED if any milestone failed.
        """
        orch = self._make_orchestrator_with_failing_first_milestone(stop_on_failure=False)
        ctx = orch.execute_goal("Build a SaaS platform", complexity="large")
        # An earlier milestone failed → aggregate outcome must be FAILED,
        # not COMPLETED (the old buggy behaviour).
        assert ctx.state == ExecutionState.FAILED

    def test_stop_on_failure_false_does_not_set_completed_on_any_failure(self):
        orch = self._make_orchestrator_with_failing_first_milestone(stop_on_failure=False)
        ctx = orch.execute_goal("Build an enterprise CRM", complexity="enterprise")
        assert ctx.state != ExecutionState.COMPLETED

    def test_stop_on_failure_true_remaining_milestones_marked_skipped(self):
        orch = self._make_orchestrator_with_failing_first_milestone(stop_on_failure=True)
        ctx = orch.execute_goal("Build a SaaS platform", complexity="large")
        milestones_meta = ctx.metadata.get("milestones", [])
        # With multiple milestones, at least one remaining should be skipped
        statuses = [m.get("status") for m in milestones_meta]
        # Either skipped exists, or there was only 1 milestone to begin with
        if len(milestones_meta) > 1:
            assert "skipped" in statuses

    def test_task_count_reflects_all_milestones(self):
        """
        context.task_count must equal the total tasks across all milestones,
        not just the last one.
        """
        from smartagent.executive.scheduler import Scheduler
        sched = Scheduler(show_progress=False)
        orch = Orchestrator(scheduler=sched)
        ctx = orch.execute_goal("Build a SaaS billing platform", complexity="large")
        milestone_total = sum(
            m["task_count"] for m in ctx.metadata["milestones"]
            if m.get("status") != "skipped"
        )
        assert ctx.task_count == milestone_total, (
            f"context.task_count={ctx.task_count} but milestones sum={milestone_total}"
        )

    def test_completed_count_reflects_all_milestones(self):
        """
        context.completed_count must include tasks from earlier milestones,
        not just the last one.
        """
        from smartagent.executive.scheduler import Scheduler
        sched = Scheduler(show_progress=False)
        orch = Orchestrator(scheduler=sched)
        ctx = orch.execute_goal("Build a CRM system", complexity="enterprise")
        # All tasks should be accounted for in either completed or failed
        assert ctx.completed_count + ctx.failed_count == ctx.task_count

    def test_mixed_outcomes_early_fail_later_success_still_failed(self):
        """
        Core regression guard: first milestone fails, later milestone succeeds
        (stop_on_failure=False).  Final state MUST be FAILED — not COMPLETED.

        Uses a mixed registry: RESEARCH/DESIGN/ARCHITECTURE/PLANNING tasks fail;
        IMPLEMENTATION/CODING tasks pass.  A large 'default'-template goal
        produces Foundation (fail) → Core Development (pass) milestones.
        """
        from smartagent.executive.scheduler import Scheduler
        from smartagent.executive.worker_registry import WorkerRegistry
        from smartagent.executive.task import TaskType

        registry = WorkerRegistry()
        # First-milestone task types → fail
        for tt in (TaskType.RESEARCH, TaskType.PLANNING,
                   TaskType.DESIGN, TaskType.ARCHITECTURE):
            registry.register(tt, _AlwaysFailWorker)
        # Second-milestone task types → succeed
        for tt in (TaskType.IMPLEMENTATION, TaskType.CODING,
                   TaskType.TESTING, TaskType.REVIEW,
                   TaskType.DOCUMENTATION, TaskType.ANALYSIS,
                   TaskType.REPORT, TaskType.GENERIC,
                   TaskType.DEBUGGING, TaskType.GIT):
            registry.register(tt, _AlwaysPassWorker)

        sched = Scheduler(worker_registry=registry, max_retries=0, show_progress=False)
        orch = Orchestrator(
            scheduler=sched,
            worker_registry=registry,
            stop_on_failure=False,
        )

        # "large" goal using "default" template → Research+Design (fail) then
        # Implementation+Testing+Review (pass) across milestones.
        ctx = orch.execute_goal(
            "Build a comprehensive enterprise platform", complexity="large"
        )

        # The final state MUST reflect the early failure — not the later success.
        assert ctx.state == ExecutionState.FAILED, (
            f"Expected FAILED but got {ctx.state}; "
            "early milestone failure must not be masked by a later success"
        )
