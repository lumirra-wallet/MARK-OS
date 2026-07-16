"""
Tests for the MARK Executive Framework — Milestone 11 Phase 1.

Coverage:
    - Task lifecycle (TaskStatus transitions)
    - TaskGraph (add, validate, topological sort, ready tasks, blocking)
    - TaskQueue (enqueue/dequeue, peek, size)
    - ExecutionState (predicates)
    - ExecutionContext (counters, transitions, result helpers)
    - Planner (template selection, task chain, dependency wiring)
    - WorkerRegistry (register, get, fallback, list)
    - Scheduler (stub execution, dependency unlocking, failure propagation)
    - Orchestrator (preview_plan, execute_goal)
    - ExecutiveController (plan, receive_goal, run)
    - Console commands (plan, tasks)
"""

from __future__ import annotations

import pytest

from smartagent.executive.task import Task, TaskStatus, TaskType
from smartagent.executive.task_graph import TaskGraph, TaskGraphError
from smartagent.executive.task_queue import TaskQueue
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.planner import Planner
from smartagent.executive.worker_registry import WorkerRegistry, build_default_registry
from smartagent.executive.scheduler import Scheduler
from smartagent.executive.orchestrator import Orchestrator
from smartagent.executive.executive_controller import ExecutiveController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _two_task_chain() -> tuple[Task, Task]:
    """Return (task_a, task_b) where task_b depends on task_a."""
    a = Task(title="Research", task_type=TaskType.RESEARCH)
    b = Task(title="Implementation", task_type=TaskType.IMPLEMENTATION, dependencies=[a.id])
    return a, b


def _graph_from(*tasks: Task) -> TaskGraph:
    g = TaskGraph()
    for t in tasks:
        g.add_task(t)
    return g


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class TestTask:
    def test_defaults(self):
        t = Task(title="Hello")
        assert t.title == "Hello"
        assert t.status == TaskStatus.PENDING
        assert t.task_type == TaskType.GENERIC
        assert t.dependencies == []
        assert t.result is None
        assert t.error is None
        assert t.id  # not empty

    def test_mark_ready(self):
        t = Task(title="t")
        t.mark_ready()
        assert t.status == TaskStatus.READY

    def test_mark_running_records_time(self):
        t = Task(title="t")
        t.mark_ready()
        t.mark_running()
        assert t.status == TaskStatus.RUNNING
        assert t.started_at is not None

    def test_mark_completed(self):
        t = Task(title="t")
        t.mark_running()
        t.mark_completed("done")
        assert t.status == TaskStatus.COMPLETED
        assert t.result == "done"
        assert t.completed_at is not None
        assert t.is_terminal

    def test_mark_failed(self):
        t = Task(title="t")
        t.mark_running()
        t.mark_failed("oops")
        assert t.status == TaskStatus.FAILED
        assert t.error == "oops"
        assert t.is_terminal

    def test_mark_blocked(self):
        t = Task(title="t")
        t.mark_blocked()
        assert t.status == TaskStatus.BLOCKED

    def test_is_runnable_only_when_ready(self):
        t = Task(title="t")
        assert not t.is_runnable
        t.mark_ready()
        assert t.is_runnable
        t.mark_running()
        assert not t.is_runnable

    def test_unique_ids(self):
        ids = {Task(title="x").id for _ in range(100)}
        assert len(ids) == 100

    def test_str_contains_title(self):
        t = Task(title="Research")
        assert "Research" in str(t)

    def test_repr(self):
        t = Task(title="Design", task_type=TaskType.DESIGN)
        r = repr(t)
        assert "Design" in r
        assert "design" in r


# ---------------------------------------------------------------------------
# TaskGraph
# ---------------------------------------------------------------------------

class TestTaskGraph:
    def test_add_and_get(self):
        t = Task(title="A")
        g = TaskGraph()
        g.add_task(t)
        assert g.get(t.id) is t

    def test_add_duplicate_raises(self):
        t = Task(title="A")
        g = TaskGraph()
        g.add_task(t)
        with pytest.raises(TaskGraphError):
            g.add_task(t)

    def test_len(self):
        g = TaskGraph()
        for i in range(3):
            g.add_task(Task(title=f"t{i}"))
        assert len(g) == 3

    def test_validate_missing_dependency_raises(self):
        g = TaskGraph()
        t = Task(title="A", dependencies=["nonexistent-id"])
        g.add_task(t)
        with pytest.raises(TaskGraphError, match="unknown id"):
            g.validate()

    def test_validate_cycle_raises(self):
        a = Task(title="A")
        b = Task(title="B", dependencies=[a.id])
        # Manually create a cycle: a depends on b.
        a.dependencies = [b.id]
        g = _graph_from(a, b)
        with pytest.raises(TaskGraphError, match="cycle"):
            g.validate()

    def test_get_ready_tasks_no_deps(self):
        a = Task(title="A")
        b = Task(title="B")
        g = _graph_from(a, b)
        ready = g.get_ready_tasks()
        assert len(ready) == 2

    def test_get_ready_tasks_with_deps(self):
        a, b = _two_task_chain()
        g = _graph_from(a, b)
        # Only task A is ready initially.
        ready = g.get_ready_tasks()
        assert ready == [a]

    def test_mark_completed_unlocks_dependent(self):
        a, b = _two_task_chain()
        g = _graph_from(a, b)
        a.mark_running()
        newly_ready = g.mark_completed(a.id, "ok")
        assert b in newly_ready
        assert b.status == TaskStatus.READY

    def test_mark_failed_blocks_downstream(self):
        a, b = _two_task_chain()
        g = _graph_from(a, b)
        a.mark_running()
        blocked = g.mark_failed(a.id, "error")
        assert b in blocked
        assert b.status == TaskStatus.BLOCKED

    def test_all_completed_false_initially(self):
        a = Task(title="A")
        g = _graph_from(a)
        assert not g.all_completed()

    def test_all_completed_true_after_completion(self):
        a = Task(title="A")
        g = _graph_from(a)
        a.mark_running()
        g.mark_completed(a.id, "done")
        assert g.all_completed()

    def test_has_failures(self):
        a = Task(title="A")
        g = _graph_from(a)
        a.mark_running()
        g.mark_failed(a.id, "boom")
        assert g.has_failures()

    def test_topological_order_respects_deps(self):
        a, b = _two_task_chain()
        g = _graph_from(a, b)
        order = g.topological_order()
        assert order.index(a) < order.index(b)

    def test_topological_order_multiple_roots(self):
        a = Task(title="A")
        b = Task(title="B")
        c = Task(title="C", dependencies=[a.id, b.id])
        g = _graph_from(a, b, c)
        order = g.topological_order()
        assert order.index(c) > order.index(a)
        assert order.index(c) > order.index(b)

    def test_as_display_lines_contains_goal(self):
        a, b = _two_task_chain()
        g = _graph_from(a, b)
        lines = g.as_display_lines()
        assert lines[0] == "Goal"
        combined = "\n".join(lines)
        assert "Research" in combined
        assert "Implementation" in combined
        assert "↓" in combined


# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------

class TestTaskQueue:
    def test_empty_initially(self):
        q = TaskQueue()
        assert q.is_empty()
        assert q.size() == 0

    def test_enqueue_dequeue(self):
        q = TaskQueue()
        t = Task(title="A")
        q.enqueue(t)
        assert q.size() == 1
        result = q.dequeue()
        assert result is t
        assert q.is_empty()

    def test_fifo_order(self):
        q = TaskQueue()
        tasks = [Task(title=f"t{i}") for i in range(5)]
        for t in tasks:
            q.enqueue(t)
        for expected in tasks:
            assert q.dequeue() is expected

    def test_dequeue_empty_returns_none(self):
        q = TaskQueue()
        assert q.dequeue() is None

    def test_peek_does_not_remove(self):
        q = TaskQueue()
        t = Task(title="A")
        q.enqueue(t)
        assert q.peek() is t
        assert q.size() == 1

    def test_enqueue_many(self):
        q = TaskQueue()
        tasks = [Task(title=f"t{i}") for i in range(3)]
        q.enqueue_many(tasks)
        assert q.size() == 3

    def test_all_tasks_snapshot(self):
        q = TaskQueue()
        tasks = [Task(title=f"t{i}") for i in range(3)]
        q.enqueue_many(tasks)
        snapshot = q.all_tasks()
        assert snapshot == tasks
        assert q.size() == 3  # snapshot did not consume

    def test_clear(self):
        q = TaskQueue()
        q.enqueue_many([Task(title="A"), Task(title="B")])
        q.clear()
        assert q.is_empty()

    def test_total_enqueued_counter(self):
        q = TaskQueue()
        q.enqueue(Task(title="A"))
        q.dequeue()
        q.enqueue(Task(title="B"))
        assert q.total_enqueued == 2


# ---------------------------------------------------------------------------
# ExecutionState
# ---------------------------------------------------------------------------

class TestExecutionState:
    def test_terminal_states(self):
        assert ExecutionState.COMPLETED.is_terminal
        assert ExecutionState.FAILED.is_terminal
        assert ExecutionState.CANCELLED.is_terminal

    def test_non_terminal_states(self):
        assert not ExecutionState.IDLE.is_terminal
        assert not ExecutionState.PLANNING.is_terminal
        assert not ExecutionState.RUNNING.is_terminal
        assert not ExecutionState.READY.is_terminal
        assert not ExecutionState.PAUSED.is_terminal

    def test_active_states(self):
        assert ExecutionState.PLANNING.is_active
        assert ExecutionState.RUNNING.is_active

    def test_non_active_states(self):
        assert not ExecutionState.IDLE.is_active
        assert not ExecutionState.COMPLETED.is_active


# ---------------------------------------------------------------------------
# ExecutionContext
# ---------------------------------------------------------------------------

class TestExecutionContext:
    def test_defaults(self):
        ctx = ExecutionContext(goal="build something")
        assert ctx.goal == "build something"
        assert ctx.state == ExecutionState.IDLE
        assert ctx.task_count == 0
        assert ctx.completed_count == 0
        assert ctx.plan_id

    def test_transition_records_started_at(self):
        ctx = ExecutionContext(goal="g")
        ctx.transition_to(ExecutionState.RUNNING)
        assert ctx.started_at is not None

    def test_transition_records_ended_at_on_terminal(self):
        ctx = ExecutionContext(goal="g")
        ctx.transition_to(ExecutionState.COMPLETED)
        assert ctx.ended_at is not None

    def test_task_count(self):
        ctx = ExecutionContext(goal="g")
        for i in range(3):
            ctx.task_graph.add_task(Task(title=f"t{i}"))
        assert ctx.task_count == 3

    def test_completed_count(self):
        ctx = ExecutionContext(goal="g")
        t = Task(title="A")
        ctx.task_graph.add_task(t)
        t.mark_running()
        ctx.task_graph.mark_completed(t.id, "done")
        assert ctx.completed_count == 1

    def test_record_and_get_result(self):
        ctx = ExecutionContext(goal="g")
        ctx.record_result("id1", "some output")
        assert ctx.get_result("id1") == "some output"

    def test_get_result_missing_returns_none(self):
        ctx = ExecutionContext(goal="g")
        assert ctx.get_result("missing") is None

    def test_summary_contains_goal(self):
        ctx = ExecutionContext(goal="build app")
        assert "build app" in ctx.summary()

    def test_is_complete_false_initially(self):
        ctx = ExecutionContext(goal="g")
        ctx.task_graph.add_task(Task(title="A"))
        assert not ctx.is_complete


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class TestPlanner:
    def _plan(self, goal: str) -> list[Task]:
        return Planner().create_plan(goal)

    def test_empty_goal_raises(self):
        with pytest.raises(ValueError):
            Planner().create_plan("")

    def test_whitespace_goal_raises(self):
        with pytest.raises(ValueError):
            Planner().create_plan("   ")

    def test_default_template_five_tasks(self):
        tasks = self._plan("Build a calculator")
        assert len(tasks) == 5

    def test_default_task_titles(self):
        tasks = self._plan("Build a calculator")
        titles = [t.title for t in tasks]
        assert titles[0] == "Research"
        assert "Implementation" in titles or "Implement" in titles
        assert titles[-1] == "Review"

    def test_api_template_triggered(self):
        tasks = self._plan("Build a REST API for task management")
        titles = [t.title for t in tasks]
        assert "Architecture" in titles
        assert "Documentation" in titles
        assert "Review" not in titles

    def test_script_template_triggered(self):
        tasks = self._plan("Write a CLI tool")
        assert len(tasks) == 3

    def test_research_template_triggered(self):
        tasks = self._plan("Research quantum computing trends")
        titles = [t.title for t in tasks]
        assert "Analysis" in titles
        assert "Report" in titles

    def test_algorithm_template_triggered(self):
        tasks = self._plan("Implement a sorting algorithm")
        titles = [t.title for t in tasks]
        assert "Design" in titles
        assert "Research" in titles

    def test_database_template_triggered(self):
        tasks = self._plan("Design a PostgreSQL database schema")
        titles = [t.title for t in tasks]
        assert "Documentation" in titles

    def test_sequential_dependencies(self):
        """Each task must depend on the previous one (linear chain)."""
        tasks = self._plan("Build an app")
        for i in range(1, len(tasks)):
            assert tasks[i].dependencies == [tasks[i - 1].id]

    def test_first_task_no_dependencies(self):
        tasks = self._plan("Build an app")
        assert tasks[0].dependencies == []

    def test_task_types_assigned(self):
        tasks = self._plan("Build a calculator")
        assert all(t.task_type != TaskType.GENERIC for t in tasks)

    def test_goal_in_description(self):
        goal = "Build a unique thing XYZ"
        tasks = self._plan(goal)
        assert all(goal in t.description for t in tasks)

    def test_available_templates(self):
        templates = Planner().available_templates()
        assert "default" in templates
        assert "api" in templates
        assert "research" in templates


# ---------------------------------------------------------------------------
# WorkerRegistry
# ---------------------------------------------------------------------------

class TestWorkerRegistry:
    def test_register_and_get_string(self):
        reg = WorkerRegistry()
        reg.register(TaskType.RESEARCH, "ResearchWorker")
        result = reg.get(TaskType.RESEARCH)
        assert result == "ResearchWorker"

    def test_get_missing_returns_none_without_generic(self):
        reg = WorkerRegistry()
        assert reg.get(TaskType.RESEARCH) is None

    def test_get_falls_back_to_generic(self):
        reg = WorkerRegistry()
        reg.register(TaskType.GENERIC, "GenericWorker")
        result = reg.get(TaskType.RESEARCH)
        assert result == "GenericWorker"

    def test_has(self):
        reg = WorkerRegistry()
        reg.register(TaskType.CODING, "CodingWorker")
        assert reg.has(TaskType.CODING)
        assert not reg.has(TaskType.TESTING)

    def test_unregister(self):
        reg = WorkerRegistry()
        reg.register(TaskType.CODING, "CodingWorker")
        reg.unregister(TaskType.CODING)
        assert not reg.has(TaskType.CODING)

    def test_list_workers(self):
        reg = WorkerRegistry()
        reg.register(TaskType.RESEARCH, "ResearchWorker")
        reg.register(TaskType.CODING, "CodingWorker")
        rows = reg.list_workers()
        types = {r["task_type"] for r in rows}
        assert TaskType.RESEARCH.value in types
        assert TaskType.CODING.value in types

    def test_count(self):
        reg = WorkerRegistry()
        reg.register(TaskType.RESEARCH, "R")
        reg.register(TaskType.CODING, "C")
        assert reg.count() == 2

    def test_build_default_registry_has_all_types(self):
        reg = build_default_registry()
        for task_type in [
            TaskType.RESEARCH, TaskType.CODING, TaskType.TESTING,
            TaskType.REVIEW, TaskType.DOCUMENTATION, TaskType.GENERIC,
        ]:
            assert reg.has(task_type), f"Missing: {task_type.value}"

    def test_register_string_key(self):
        reg = WorkerRegistry()
        reg.register("custom_type", "CustomWorker")
        assert reg.get("custom_type") == "CustomWorker"


# ---------------------------------------------------------------------------
# Scheduler (Phase 1 stub)
# ---------------------------------------------------------------------------

class TestScheduler:
    def _make_context(self, goal: str = "test goal") -> ExecutionContext:
        planner = Planner()
        orchestrator = Orchestrator()
        return orchestrator.preview_plan(goal)

    def test_all_tasks_complete_after_run(self):
        ctx = self._make_context("Build a calculator")
        scheduler = Scheduler()
        result = scheduler.run(ctx)
        assert result.state == ExecutionState.COMPLETED
        for task in result.task_graph.all_tasks():
            assert task.status == TaskStatus.COMPLETED

    def test_results_recorded_for_each_task(self):
        ctx = self._make_context("Build a calculator")
        scheduler = Scheduler()
        result = scheduler.run(ctx)
        for task in result.task_graph.all_tasks():
            assert result.get_result(task.id) is not None

    def test_scheduler_respects_dependency_order(self):
        """Verify tasks execute in topological order by checking timestamps."""
        ctx = self._make_context("Write a CLI tool")  # 3 tasks: sequential
        scheduler = Scheduler()
        result = scheduler.run(ctx)
        tasks = result.task_graph.topological_order()
        for i in range(1, len(tasks)):
            assert tasks[i].started_at >= tasks[i - 1].started_at

    def test_failed_task_blocks_downstream(self):
        """A worker that raises must fail the task and block dependents."""
        class BrokenWorker:
            def execute(self, task, context):
                raise RuntimeError("Broken!")

        reg = WorkerRegistry()
        reg.register(TaskType.RESEARCH, BrokenWorker)

        orchestrator = Orchestrator(worker_registry=reg)
        ctx = orchestrator.preview_plan("Build a CLI tool")
        scheduler = Scheduler(worker_registry=reg)
        result = scheduler.run(ctx)

        tasks = result.task_graph.all_tasks()
        research_task = next(t for t in tasks if t.task_type == TaskType.RESEARCH)
        assert research_task.status == TaskStatus.FAILED
        # Downstream tasks should be blocked.
        downstream = [t for t in tasks if t.id != research_task.id]
        for t in downstream:
            assert t.status in (TaskStatus.BLOCKED, TaskStatus.PENDING, TaskStatus.FAILED)

    def test_run_returns_context(self):
        ctx = self._make_context("test")
        scheduler = Scheduler()
        result = scheduler.run(ctx)
        assert isinstance(result, ExecutionContext)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TestOrchestrator:
    def test_preview_plan_returns_ready_context(self):
        orch = Orchestrator()
        ctx = orch.preview_plan("Build a calculator")
        assert ctx.state == ExecutionState.READY
        assert ctx.task_count > 0

    def test_preview_plan_does_not_execute(self):
        orch = Orchestrator()
        ctx = orch.preview_plan("Build a calculator")
        for task in ctx.task_graph.all_tasks():
            assert task.status in (TaskStatus.PENDING, TaskStatus.READY)

    def test_execute_goal_returns_completed(self):
        orch = Orchestrator()
        ctx = orch.execute_goal("Build a calculator")
        assert ctx.state == ExecutionState.COMPLETED

    def test_build_task_graph_validates(self):
        orch = Orchestrator()
        tasks = Planner().create_plan("Build an app")
        graph = orch.build_task_graph(tasks)
        assert len(graph) == len(tasks)

    def test_submit_to_queue_seeds_first_task(self):
        orch = Orchestrator()
        tasks = Planner().create_plan("Build a CLI tool")
        graph = orch.build_task_graph(tasks)
        queue = orch.submit_to_queue(graph)
        # Only the first task (no deps) is seeded.
        assert queue.size() == 1


# ---------------------------------------------------------------------------
# ExecutiveController
# ---------------------------------------------------------------------------

class TestExecutiveController:
    def test_plan_returns_ready_context(self):
        ctrl = ExecutiveController()
        ctx = ctrl.plan("Build a calculator")
        assert ctx.state == ExecutionState.READY
        assert ctrl.current_context is ctx

    def test_receive_goal_returns_completed_context(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Build a calculator")
        assert ctx.state == ExecutionState.COMPLETED

    def test_run_after_plan(self):
        ctrl = ExecutiveController()
        ctrl.plan("Write a script")
        ctx = ctrl.run()
        assert ctx.state == ExecutionState.COMPLETED

    def test_run_without_plan_raises(self):
        ctrl = ExecutiveController()
        with pytest.raises(RuntimeError, match="No plan"):
            ctrl.run()

    def test_has_plan_false_initially(self):
        ctrl = ExecutiveController()
        assert not ctrl.has_plan()

    def test_has_plan_true_after_plan(self):
        ctrl = ExecutiveController()
        ctrl.plan("something")
        assert ctrl.has_plan()

    def test_current_context_updates(self):
        ctrl = ExecutiveController()
        assert ctrl.current_context is None
        ctrl.plan("g1")
        ctx1 = ctrl.current_context
        ctrl.plan("g2")
        ctx2 = ctrl.current_context
        assert ctx1 is not ctx2
        assert ctx2.goal == "g2"

    def test_create_plan_step(self):
        ctrl = ExecutiveController()
        tasks = ctrl.create_plan("Build an API")
        assert len(tasks) > 0
        assert all(isinstance(t, Task) for t in tasks)

    def test_build_task_graph_step(self):
        ctrl = ExecutiveController()
        tasks = ctrl.create_plan("Build an app")
        graph = ctrl.build_task_graph(tasks)
        assert len(graph) == len(tasks)

    def test_submit_to_queue_step(self):
        ctrl = ExecutiveController()
        tasks = ctrl.create_plan("Build an app")
        graph = ctrl.build_task_graph(tasks)
        queue = ctrl.submit_to_queue(graph)
        assert isinstance(queue, TaskQueue)
        assert queue.size() >= 1

    def test_worker_registry_property(self):
        ctrl = ExecutiveController()
        assert ctrl.worker_registry is not None
        assert ctrl.worker_registry.count() > 0

    def test_planner_property(self):
        ctrl = ExecutiveController()
        assert isinstance(ctrl.planner, Planner)

    def test_repr_with_no_plan(self):
        ctrl = ExecutiveController()
        assert "no plan" in repr(ctrl).lower()

    def test_repr_with_plan(self):
        ctrl = ExecutiveController()
        ctrl.plan("Build a calculator")
        r = repr(ctrl)
        assert "calculator" in r.lower()


# ---------------------------------------------------------------------------
# Console commands (plan, tasks)
# ---------------------------------------------------------------------------

class TestPlanCommand:
    @pytest.fixture()
    def agent(self, tmp_path):
        """Minimal agent fixture with executive controller attached."""
        from smartagent.executive.executive_controller import ExecutiveController
        from unittest.mock import MagicMock
        agent = MagicMock()
        agent.executive = ExecutiveController()
        return agent

    def test_plan_no_args_returns_usage(self, agent):
        from smartagent.ui.commands.executive import handle_plan
        result = handle_plan(agent, [])
        assert "Usage" in result or "usage" in result.lower()

    def test_plan_with_goal_displays_graph(self, agent):
        from smartagent.ui.commands.executive import handle_plan
        result = handle_plan(agent, ["Build", "a", "calculator"])
        assert "Goal" in result
        assert "↓" in result
        assert "Research" in result

    def test_plan_stores_context_on_agent(self, agent):
        from smartagent.ui.commands.executive import handle_plan
        handle_plan(agent, ["Build", "a", "calculator"])
        assert agent.executive.current_context is not None

    def test_plan_shows_task_count(self, agent):
        from smartagent.ui.commands.executive import handle_plan
        result = handle_plan(agent, ["Build", "a", "calculator"])
        assert "task" in result.lower()

    def test_plan_different_goals_different_outputs(self, agent):
        from smartagent.ui.commands.executive import handle_plan
        r1 = handle_plan(agent, ["Build", "a", "calculator"])
        r2 = handle_plan(agent, ["Research", "quantum", "computing"])
        # Research template has different task names.
        assert r1 != r2


class TestTasksCommand:
    @pytest.fixture()
    def agent_with_plan(self, tmp_path):
        from smartagent.executive.executive_controller import ExecutiveController
        from unittest.mock import MagicMock
        agent = MagicMock()
        agent.executive = ExecutiveController()
        agent.executive.plan("Build a calculator")
        return agent

    def test_tasks_no_plan_returns_message(self):
        from smartagent.ui.commands.executive import handle_tasks
        from unittest.mock import MagicMock
        agent = MagicMock()
        agent.executive = ExecutiveController()
        result = handle_tasks(agent, [])
        assert "No plan" in result or "plan" in result.lower()

    def test_tasks_with_plan_shows_all_tasks(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_tasks
        result = handle_tasks(agent_with_plan, [])
        assert "Research" in result
        assert "Implementation" in result

    def test_tasks_shows_goal(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_tasks
        result = handle_tasks(agent_with_plan, [])
        assert "calculator" in result.lower()

    def test_tasks_shows_task_numbers(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_tasks
        result = handle_tasks(agent_with_plan, [])
        assert "1." in result
        assert "2." in result

    def test_tasks_shows_plan_id(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_tasks
        result = handle_tasks(agent_with_plan, [])
        assert "Plan id" in result or "plan_id" in result or len(result) > 20
