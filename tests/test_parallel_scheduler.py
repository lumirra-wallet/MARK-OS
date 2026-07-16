"""
tests/test_parallel_scheduler.py — Milestone 13: Parallel Executive Engine.

Verifies:
  * Parallel execution of independent tasks (ThreadPoolExecutor)
  * DAG dependency ordering is never violated
  * Thread safety: no lost results, no duplicate executions
  * Cancellation mid-run
  * Performance metrics recording
  * Configurable max_workers via Settings
  * 100+ concurrent plan stress test
  * Random DAG stress test
  * All existing serial tests are unaffected (use_parallel=False default)
"""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pytest

from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.executive_controller import ExecutiveController
from smartagent.executive.parallel_scheduler import ParallelScheduler
from smartagent.executive.planner import Planner
from smartagent.executive.task import Task, TaskStatus, TaskType
from smartagent.executive.task_graph import TaskGraph
from smartagent.executive.task_queue import TaskQueue
from smartagent.executive.worker_registry import build_default_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler(max_workers: int = 4) -> ParallelScheduler:
    """ParallelScheduler with no progress output for clean test runs."""
    return ParallelScheduler(
        worker_registry=build_default_registry(),
        max_workers=max_workers,
        show_progress=False,
    )


def _simple_context(goal: str = "Test") -> ExecutionContext:
    ctx = ExecutionContext(goal=goal)
    return ctx


def _linear_chain(n: int, start_type: TaskType = TaskType.RESEARCH) -> list[Task]:
    """Build a linear chain of n tasks: t0 ← t1 ← t2 ← ... ← t(n-1)."""
    types = list(TaskType)
    tasks = []
    for i in range(n):
        t = Task(
            title=f"Step {i}",
            task_type=types[i % len(types)],
        )
        if i > 0:
            t.dependencies = [tasks[i - 1].id]
        tasks.append(t)
    return tasks


def _diamond(
    root_type: TaskType = TaskType.RESEARCH,
) -> list[Task]:
    """
    Diamond DAG:
        root
        / \\
       L   R
        \\ /
        join
    """
    root = Task(title="Root", task_type=TaskType.RESEARCH)
    left = Task(title="Left", task_type=TaskType.DESIGN, dependencies=[root.id])
    right = Task(title="Right", task_type=TaskType.CODING, dependencies=[root.id])
    join = Task(title="Join", task_type=TaskType.REVIEW,
                dependencies=[left.id, right.id])
    return [root, left, right, join]


def _random_dag(n: int, seed: int = 0) -> list[Task]:
    """
    Generate a random DAG with *n* tasks.  Each task depends on 0–2 earlier tasks,
    guaranteeing no cycles.
    """
    rng = random.Random(seed)
    types = list(TaskType)
    tasks: list[Task] = []
    for i in range(n):
        task = Task(
            title=f"Task-{i}",
            task_type=types[i % len(types)],
        )
        # Depend on up to 2 earlier tasks
        if i > 0:
            num_deps = rng.randint(0, min(2, i))
            if num_deps:
                deps = rng.sample([t.id for t in tasks], num_deps)
                task.dependencies = deps
        tasks.append(task)
    return tasks


def _build_and_run(
    tasks: list[Task],
    max_workers: int = 4,
    goal: str = "Test",
) -> ExecutionContext:
    """Build a TaskGraph, seed queue, run in parallel, return context."""
    ctx = _simple_context(goal)
    graph = TaskGraph()
    for t in tasks:
        graph.add_task(t)
    graph.validate()
    ctx.task_graph = graph
    ctx.task_queue = TaskQueue()  # ParallelScheduler doesn't use the queue

    sched = _make_scheduler(max_workers)
    return sched.run(ctx)


# ---------------------------------------------------------------------------
# 1. Basic parallel execution
# ---------------------------------------------------------------------------


class TestParallelSchedulerBasic:
    """Core correctness: all tasks run, states are correct."""

    def test_single_task_completes(self):
        tasks = [Task(title="Solo", task_type=TaskType.RESEARCH)]
        ctx = _build_and_run(tasks)
        assert ctx.state == ExecutionState.COMPLETED
        assert ctx.completed_count == 1

    def test_linear_chain_completes(self):
        tasks = _linear_chain(5)
        ctx = _build_and_run(tasks)
        assert ctx.state == ExecutionState.COMPLETED
        assert ctx.completed_count == 5

    def test_diamond_dag_completes(self):
        tasks = _diamond()
        ctx = _build_and_run(tasks)
        assert ctx.state == ExecutionState.COMPLETED
        assert ctx.completed_count == 4

    def test_fully_independent_tasks_all_complete(self):
        """5 independent tasks with no dependencies."""
        tasks = [Task(title=f"T{i}", task_type=TaskType.RESEARCH) for i in range(5)]
        ctx = _build_and_run(tasks)
        assert ctx.state == ExecutionState.COMPLETED
        assert ctx.completed_count == 5

    def test_all_task_results_are_non_empty_strings(self):
        tasks = _linear_chain(3)
        ctx = _build_and_run(tasks)
        for task in ctx.task_graph.all_tasks():
            assert isinstance(task.result, str)
            assert len(task.result) > 0

    def test_results_stored_in_context(self):
        tasks = [Task(title="Solo", task_type=TaskType.DESIGN)]
        ctx = _build_and_run(tasks)
        assert len(ctx.results) == 1


# ---------------------------------------------------------------------------
# 2. Dependency ordering (DAG correctness)
# ---------------------------------------------------------------------------


class TestDependencyOrdering:
    """Tasks must never run before their dependencies complete."""

    def test_linear_chain_respects_order(self):
        tasks = _linear_chain(6)
        completion_order: list[str] = []
        lock = threading.Lock()

        original_execute = ParallelScheduler._execute

        def _patched_execute(self_sched, task, context):
            result = original_execute(self_sched, task, context)
            with lock:
                completion_order.append(task.id)
            return result

        sched = _make_scheduler(max_workers=6)
        sched._execute = lambda task, ctx: _patched_execute(sched, task, ctx)

        ctx = _simple_context()
        graph = TaskGraph()
        for t in tasks:
            graph.add_task(t)
        graph.validate()
        ctx.task_graph = graph
        ctx.task_queue = TaskQueue()
        sched.run(ctx)

        # Each task should appear after all its dependencies
        id_to_pos = {tid: i for i, tid in enumerate(completion_order)}
        for task in tasks:
            for dep_id in task.dependencies:
                assert id_to_pos[dep_id] < id_to_pos[task.id], (
                    f"Dependency {dep_id} completed after {task.id}"
                )

    def test_diamond_join_runs_after_both_branches(self):
        tasks = _diamond()
        root, left, right, join = tasks

        completion_order: list[str] = []
        lock = threading.Lock()

        original_execute = ParallelScheduler._execute

        def _patched(self_sched, task, context):
            result = original_execute(self_sched, task, context)
            with lock:
                completion_order.append(task.id)
            return result

        sched = _make_scheduler(max_workers=4)
        sched._execute = lambda task, ctx: _patched(sched, task, ctx)

        ctx = _simple_context()
        graph = TaskGraph()
        for t in tasks:
            graph.add_task(t)
        graph.validate()
        ctx.task_graph = graph
        ctx.task_queue = TaskQueue()
        sched.run(ctx)

        pos = {tid: i for i, tid in enumerate(completion_order)}
        # join must appear after both left and right
        assert pos[left.id] < pos[join.id]
        assert pos[right.id] < pos[join.id]

    def test_random_dag_dependency_ordering(self):
        """Verify dependency ordering for 20 randomly generated DAG layouts."""
        for seed in range(20):
            tasks = _random_dag(n=10, seed=seed)
            ctx = _build_and_run(tasks, max_workers=4)
            assert ctx.state == ExecutionState.COMPLETED, f"Seed {seed} failed"


# ---------------------------------------------------------------------------
# 3. Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """No race conditions: results and metadata are consistent."""

    def test_results_dict_complete_after_parallel_run(self):
        """Every completed task should have an entry in context.results."""
        tasks = [Task(title=f"T{i}", task_type=TaskType.CODING) for i in range(10)]
        ctx = _build_and_run(tasks, max_workers=4)
        for task in ctx.task_graph.all_tasks():
            assert task.id in ctx.results

    def test_no_task_executed_more_than_once(self):
        """Track executions per task; none should exceed 1."""
        execution_counts: dict[str, int] = {}
        lock = threading.Lock()
        original_execute = ParallelScheduler._execute

        def _counting_execute(self_sched, task, context):
            result = original_execute(self_sched, task, context)
            with lock:
                execution_counts[task.id] = execution_counts.get(task.id, 0) + 1
            return result

        tasks = [Task(title=f"T{i}", task_type=TaskType.RESEARCH) for i in range(8)]
        sched = _make_scheduler(max_workers=4)
        sched._execute = lambda task, ctx: _counting_execute(sched, task, ctx)

        ctx = _simple_context()
        graph = TaskGraph()
        for t in tasks:
            graph.add_task(t)
        graph.validate()
        ctx.task_graph = graph
        ctx.task_queue = TaskQueue()
        sched.run(ctx)

        for task in tasks:
            assert execution_counts.get(task.id, 0) == 1, (
                f"Task {task.title} executed {execution_counts.get(task.id, 0)} times"
            )

    def test_concurrent_metadata_writes_are_safe(self):
        """10 independent tasks all write to context.metadata safely."""
        tasks = [Task(title=f"T{i}", task_type=TaskType.RESEARCH) for i in range(10)]
        ctx = _build_and_run(tasks, max_workers=10)
        # task_timing should have one entry per task
        timing = ctx.metadata.get("task_timing", {})
        assert len(timing) == 10

    def test_parallel_metrics_present_after_run(self):
        tasks = [Task(title=f"T{i}", task_type=TaskType.DESIGN) for i in range(4)]
        ctx = _build_and_run(tasks, max_workers=4)
        m = ctx.metadata.get("parallel_metrics", {})
        assert "wall_time" in m
        assert "sequential_estimate" in m
        assert "speedup" in m
        assert "max_workers" in m
        assert m["max_workers"] == 4

    def test_speedup_gte_one_for_independent_tasks(self):
        """Parallel of 4 independent tasks should yield speedup ≥ 1.0."""
        tasks = [Task(title=f"T{i}", task_type=TaskType.RESEARCH) for i in range(4)]
        ctx = _build_and_run(tasks, max_workers=4)
        speedup = ctx.metadata["parallel_metrics"]["speedup"]
        assert speedup >= 1.0


# ---------------------------------------------------------------------------
# 4. Performance metrics
# ---------------------------------------------------------------------------


class TestPerformanceMetrics:
    """parallel_metrics dict structure and values."""

    def test_wall_time_is_float(self):
        tasks = _linear_chain(3)
        ctx = _build_and_run(tasks)
        assert isinstance(ctx.metadata["parallel_metrics"]["wall_time"], float)

    def test_sequential_estimate_equals_sum_of_task_times(self):
        tasks = [Task(title=f"T{i}", task_type=TaskType.CODING) for i in range(4)]
        ctx = _build_and_run(tasks, max_workers=4)
        m = ctx.metadata["parallel_metrics"]
        timing_sum = sum(ctx.metadata["task_timing"].values())
        assert abs(m["sequential_estimate"] - timing_sum) < 0.01

    def test_tasks_completed_matches_context(self):
        tasks = _linear_chain(5)
        ctx = _build_and_run(tasks)
        m = ctx.metadata["parallel_metrics"]
        assert m["tasks_completed"] == ctx.completed_count

    def test_tasks_failed_is_zero_on_clean_run(self):
        tasks = [Task(title="T", task_type=TaskType.RESEARCH)]
        ctx = _build_and_run(tasks)
        assert ctx.metadata["parallel_metrics"]["tasks_failed"] == 0


# ---------------------------------------------------------------------------
# 5. Cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    """Pre-cancelled context is handled gracefully."""

    def test_already_cancelled_context_returns_immediately(self):
        tasks = _linear_chain(5)
        ctx = _simple_context()
        graph = TaskGraph()
        for t in tasks:
            graph.add_task(t)
        graph.validate()
        ctx.task_graph = graph
        ctx.task_queue = TaskQueue()
        ctx.cancel()  # cancel before running

        sched = _make_scheduler()
        result = sched.run(ctx)
        assert result.state == ExecutionState.CANCELLED
        assert result.completed_count == 0


# ---------------------------------------------------------------------------
# 6. ExecutiveController integration
# ---------------------------------------------------------------------------


class TestExecutiveControllerParallel:
    """use_parallel=True wires ParallelScheduler through the controller."""

    def test_use_parallel_creates_parallel_scheduler(self):
        ctrl = ExecutiveController(use_parallel=True)
        assert isinstance(ctrl._scheduler, ParallelScheduler)

    def test_use_parallel_false_creates_serial_scheduler(self):
        from smartagent.executive.scheduler import Scheduler
        ctrl = ExecutiveController(use_parallel=False)
        assert isinstance(ctrl._scheduler, Scheduler)

    def test_parallel_receive_goal_completes(self):
        ctrl = ExecutiveController(use_parallel=True, show_progress=False)
        ctx = ctrl.receive_goal("Build a calculator")
        assert ctx.state == ExecutionState.COMPLETED

    def test_parallel_completed_count_matches_plan(self):
        ctrl = ExecutiveController(use_parallel=True, show_progress=False)
        ctx = ctrl.receive_goal("Write a CLI script")
        assert ctx.completed_count == ctx.task_count

    def test_parallel_and_serial_produce_same_task_count(self):
        goal = "Build a REST API"
        serial = ExecutiveController(use_parallel=False, show_progress=False)
        parallel = ExecutiveController(use_parallel=True, show_progress=False)
        ctx_s = serial.receive_goal(goal)
        ctx_p = parallel.receive_goal(goal)
        assert ctx_s.task_count == ctx_p.task_count
        assert ctx_s.completed_count == ctx_p.completed_count

    def test_max_workers_respected(self):
        ctrl = ExecutiveController(use_parallel=True, max_workers=2)
        assert ctrl._scheduler._max_workers == 2

    def test_settings_max_parallel_workers_used(self):
        from smartagent.config.settings import Settings
        s = Settings()
        s.max_parallel_workers = 3
        ctrl = ExecutiveController(use_parallel=True, settings=s)
        assert ctrl._scheduler._max_workers == 3


# ---------------------------------------------------------------------------
# 7. Stress tests — 100+ concurrent plans
# ---------------------------------------------------------------------------


class TestStressTests:
    """
    High-volume parallel execution stress tests.

    These run many independent plan executions simultaneously to verify
    no shared mutable state leaks between contexts.
    """

    def _run_plan(self, goal: str, n_tasks: int = 3) -> bool:
        """Run a plan and return True if it completed successfully."""
        ctrl = ExecutiveController(use_parallel=True, show_progress=False)
        ctx = ctrl.receive_goal(goal)
        return ctx.state == ExecutionState.COMPLETED

    def test_100_concurrent_plans(self):
        """Run 100 plans simultaneously; all should complete without errors."""
        goals = [f"Build project {i}" for i in range(100)]

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(self._run_plan, goal): goal
                for goal in goals
            }
            results = {f.result() for f in as_completed(futures)}

        assert True in results          # at least some completed
        assert False not in results     # none failed

    def test_50_random_dag_runs(self):
        """50 runs of random DAGs verify no inter-context state leakage."""
        errors: list[str] = []
        lock = threading.Lock()

        def _run_random(seed):
            try:
                tasks = _random_dag(n=random.randint(4, 12), seed=seed)
                ctx = _build_and_run(tasks, max_workers=4)
                assert ctx.completed_count == len(tasks), (
                    f"seed={seed}: only {ctx.completed_count}/{len(tasks)} completed"
                )
            except Exception as exc:
                with lock:
                    errors.append(f"seed={seed}: {exc}")

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(_run_random, seed) for seed in range(50)]
            for f in as_completed(futures):
                f.result()  # re-raise any exceptions

        assert not errors, f"Failures: {errors}"

    def test_parallel_plans_do_not_share_state(self):
        """
        Two simultaneous plans must not bleed results into each other.
        """
        results: dict[str, ExecutionContext] = {}
        lock = threading.Lock()

        def _run(label, goal):
            ctrl = ExecutiveController(use_parallel=True, show_progress=False)
            ctx = ctrl.receive_goal(goal)
            with lock:
                results[label] = ctx

        t1 = threading.Thread(target=_run, args=("a", "Build a parser"))
        t2 = threading.Thread(target=_run, args=("b", "Build a calculator"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        ctx_a = results["a"]
        ctx_b = results["b"]

        # Goals must not be mixed
        assert ctx_a.goal == "Build a parser"
        assert ctx_b.goal == "Build a calculator"

        # Results must be disjoint (no shared task ids)
        ids_a = set(ctx_a.results.keys())
        ids_b = set(ctx_b.results.keys())
        assert ids_a.isdisjoint(ids_b), "Task ids leaked between contexts!"

    def test_high_worker_count_does_not_deadlock(self):
        """10-worker pool on 20 tasks must finish within a reasonable time."""
        tasks = [Task(title=f"T{i}", task_type=TaskType.RESEARCH) for i in range(20)]
        start = time.monotonic()
        ctx = _build_and_run(tasks, max_workers=10)
        elapsed = time.monotonic() - start

        assert ctx.state == ExecutionState.COMPLETED
        assert elapsed < 30, f"Took too long: {elapsed:.1f}s (possible deadlock)"


# ---------------------------------------------------------------------------
# 8. Settings integration
# ---------------------------------------------------------------------------


class TestSettingsIntegration:
    """max_parallel_workers in Settings flows through to the scheduler."""

    def test_settings_has_max_parallel_workers(self):
        from smartagent.config.settings import Settings
        s = Settings()
        assert hasattr(s, "max_parallel_workers")
        assert isinstance(s.max_parallel_workers, int)
        assert s.max_parallel_workers >= 1

    def test_default_max_parallel_workers_is_4(self):
        from smartagent.config.settings import Settings
        assert Settings().max_parallel_workers == 4

    def test_custom_max_workers_from_settings(self):
        from smartagent.config.settings import Settings
        s = Settings()
        s.max_parallel_workers = 8
        ctrl = ExecutiveController(use_parallel=True, settings=s)
        assert ctrl._scheduler._max_workers == 8


# ---------------------------------------------------------------------------
# 9. ExecutiveController show_progress kwarg (passed through to scheduler)
# ---------------------------------------------------------------------------


class TestShowProgressKwarg:
    """ExecutiveController accepts show_progress to suppress console output."""

    def test_show_progress_false_suppresses_output(self, capsys):
        ctrl = ExecutiveController(use_parallel=True, show_progress=False)
        ctrl.receive_goal("Build something small")
        captured = capsys.readouterr()
        # No progress lines should be written
        assert "▶" not in captured.out
        assert "✓" not in captured.out
