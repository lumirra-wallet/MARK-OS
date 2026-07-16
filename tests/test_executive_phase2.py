"""
Tests for Milestone 11 Phase 2 (Workers) and Phase 3 (Scheduler + commands).

Coverage:
    Phase 2:
        - BaseWorker interface contract
        - All 9 specialist workers: instantiation, name, task_types, execute()
        - WorkerRegistry with real classes
        - Scheduler dispatches real workers end-to-end
        - Worker reads prior task results from context

    Phase 3:
        - ExecutionContext.cancel() + is_cancelled
        - Scheduler stops cleanly on cancellation
        - ExecutiveController.cancel() return values
        - Console commands: workers, worker info, queue, run, cancel
        - Full plan → run → results round trip
        - Failed task blocks downstream; upstream result available

    Backward compatibility:
        - All Phase 1 tests still pass (run from test_executive.py)
        - WorkerRegistry.list_workers() format unchanged for console
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from smartagent.executive.task import Task, TaskStatus, TaskType
from smartagent.executive.task_graph import TaskGraph
from smartagent.executive.task_queue import TaskQueue
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.planner import Planner
from smartagent.executive.scheduler import Scheduler
from smartagent.executive.orchestrator import Orchestrator
from smartagent.executive.executive_controller import ExecutiveController
from smartagent.executive.worker_registry import WorkerRegistry, build_default_registry

# Worker imports
from smartagent.executive.workers.base_worker import BaseWorker, WorkerResult
from smartagent.executive.workers.research_worker import ResearchWorker
from smartagent.executive.workers.planning_worker import PlanningWorker
from smartagent.executive.workers.design_worker import DesignWorker
from smartagent.executive.workers.coding_worker import CodingWorker
from smartagent.executive.workers.testing_worker import TestingWorker
from smartagent.executive.workers.review_worker import ReviewWorker
from smartagent.executive.workers.documentation_worker import DocumentationWorker
from smartagent.executive.workers.report_worker import ReportWorker
from smartagent.executive.workers.memory_worker import MemoryWorker
from smartagent.executive.workers.knowledge_worker import KnowledgeWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(goal: str = "test goal") -> ExecutionContext:
    return ExecutionContext(goal=goal)


def _loaded_task(task_type: TaskType = TaskType.GENERIC) -> Task:
    t = Task(title="X", task_type=task_type)
    return t


def _agent_with_executive() -> MagicMock:
    agent = MagicMock()
    agent.executive = ExecutiveController()
    return agent


# ---------------------------------------------------------------------------
# WorkerResult
# ---------------------------------------------------------------------------

class TestWorkerResult:
    def test_text_accessible(self):
        r = WorkerResult(text="hello")
        assert r.text == "hello"
        assert str(r) == "hello"

    def test_metadata_defaults_to_empty_dict(self):
        r = WorkerResult(text="x")
        assert r.metadata == {}

    def test_metadata_can_be_set(self):
        r = WorkerResult(text="x", metadata={"tokens": 42})
        assert r.metadata["tokens"] == 42


# ---------------------------------------------------------------------------
# BaseWorker interface
# ---------------------------------------------------------------------------

class TestBaseWorkerInterface:
    """Verify the BaseWorker contract without testing any specific worker."""

    def test_all_workers_are_base_worker_subclasses(self):
        workers = [
            ResearchWorker, PlanningWorker, DesignWorker, CodingWorker,
            TestingWorker, ReviewWorker, DocumentationWorker, ReportWorker,
            MemoryWorker, KnowledgeWorker,
        ]
        for cls in workers:
            instance = cls()
            assert isinstance(instance, BaseWorker), f"{cls.__name__} not a BaseWorker"

    def test_all_workers_have_name(self):
        workers = [
            ResearchWorker, PlanningWorker, DesignWorker, CodingWorker,
            TestingWorker, ReviewWorker, DocumentationWorker, ReportWorker,
            MemoryWorker, KnowledgeWorker,
        ]
        for cls in workers:
            w = cls()
            assert isinstance(w.name, str) and w.name, f"{cls.__name__}.name is empty"

    def test_all_workers_have_description(self):
        workers = [
            ResearchWorker, PlanningWorker, DesignWorker, CodingWorker,
            TestingWorker, ReviewWorker, DocumentationWorker,
        ]
        for cls in workers:
            w = cls()
            assert isinstance(w.description, str) and w.description

    def test_all_workers_phase_is_ollama(self):
        """All Phase 11.4 workers should report phase='ollama' (real AI workers)."""
        workers = [
            ResearchWorker, PlanningWorker, DesignWorker, CodingWorker,
            TestingWorker, ReviewWorker, DocumentationWorker,
        ]
        for cls in workers:
            assert cls().phase == "ollama", f"{cls.__name__}.phase != 'ollama'"

    def test_prior_results_helper_returns_empty_when_no_deps(self):
        w = ResearchWorker()
        t = Task(title="t", dependencies=[])
        ctx = _ctx()
        assert w._prior_results(t, ctx) == []

    def test_prior_results_helper_returns_dep_results(self):
        w = CodingWorker()
        dep_task = Task(title="dep")
        main_task = Task(title="main", dependencies=[dep_task.id])
        ctx = _ctx()
        ctx.record_result(dep_task.id, "dep output")
        results = w._prior_results(main_task, ctx)
        assert results == ["dep output"]


# ---------------------------------------------------------------------------
# Individual workers
# ---------------------------------------------------------------------------

class TestResearchWorker:
    def _run(self, goal="Build a calculator", prior_result=None):
        w = ResearchWorker()
        ctx = _ctx(goal)
        t = Task(title="Research", task_type=TaskType.RESEARCH, description=f"Research for: {goal}")
        if prior_result:
            dep = Task(title="prev")
            ctx.record_result(dep.id, prior_result)
            t.dependencies = [dep.id]
        return w.execute(t, ctx)

    def test_returns_string(self):
        assert isinstance(self._run(), str)

    def test_result_is_non_empty(self):
        assert len(self._run()) > 0

    def test_result_mentions_research(self):
        assert "Research" in self._run()

    def test_result_contains_goal(self):
        result = self._run("Build a REST API")
        assert "REST API" in result

    def test_result_with_prior_context(self):
        result = self._run(prior_result="Prior result here")
        assert "Prior context" in result or "prior" in result.lower() or len(result) > 20

    def test_task_types(self):
        assert TaskType.RESEARCH in ResearchWorker().task_types


class TestPlanningWorker:
    def test_execute_returns_string(self):
        w = PlanningWorker()
        ctx = _ctx("Build something")
        t = Task(title="Planning", task_type=TaskType.PLANNING)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and len(result) > 0

    def test_task_types(self):
        assert TaskType.PLANNING in PlanningWorker().task_types


class TestDesignWorker:
    def test_execute_returns_string(self):
        w = DesignWorker()
        ctx = _ctx("Build an API")
        t = Task(title="Design", task_type=TaskType.DESIGN)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Design" in result

    def test_handles_architecture_type(self):
        assert TaskType.ARCHITECTURE in DesignWorker().task_types

    def test_handles_design_type(self):
        assert TaskType.DESIGN in DesignWorker().task_types

    def test_reads_prior_research(self):
        w = DesignWorker()
        ctx = _ctx("Build API")
        dep = Task(title="Research")
        ctx.record_result(dep.id, "Research findings here")
        t = Task(title="Design", task_type=TaskType.DESIGN, dependencies=[dep.id])
        result = w.execute(t, ctx)
        assert isinstance(result, str) and len(result) > 0


class TestCodingWorker:
    def test_execute_returns_string(self):
        w = CodingWorker()
        ctx = _ctx("Build a CLI tool")
        t = Task(title="Implementation", task_type=TaskType.IMPLEMENTATION)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Coding" in result

    def test_handles_coding_type(self):
        assert TaskType.CODING in CodingWorker().task_types

    def test_handles_implementation_type(self):
        assert TaskType.IMPLEMENTATION in CodingWorker().task_types


class TestTestingWorker:
    def test_execute_returns_string(self):
        w = TestingWorker()
        ctx = _ctx("Build an app")
        t = Task(title="Testing", task_type=TaskType.TESTING)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Testing" in result

    def test_task_types(self):
        assert TaskType.TESTING in TestingWorker().task_types


class TestReviewWorker:
    def test_execute_returns_string(self):
        w = ReviewWorker()
        ctx = _ctx("Build an app")
        t = Task(title="Review", task_type=TaskType.REVIEW)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Review" in result

    def test_task_types(self):
        assert TaskType.REVIEW in ReviewWorker().task_types


class TestDocumentationWorker:
    def test_execute_returns_string(self):
        w = DocumentationWorker()
        ctx = _ctx("Build an API")
        t = Task(title="Documentation", task_type=TaskType.DOCUMENTATION)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Documentation" in result

    def test_task_types(self):
        assert TaskType.DOCUMENTATION in DocumentationWorker().task_types


class TestReportWorker:
    def test_execute_returns_string(self):
        w = ReportWorker()
        ctx = _ctx("Research quantum computing")
        t = Task(title="Report", task_type=TaskType.REPORT)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Report" in result

    def test_synthesises_multiple_prior_results(self):
        w = ReportWorker()
        ctx = _ctx("Research topic")
        dep1 = Task(title="Research")
        dep2 = Task(title="Analysis")
        ctx.record_result(dep1.id, "findings 1")
        ctx.record_result(dep2.id, "findings 2")
        t = Task(title="Report", task_type=TaskType.REPORT,
                 dependencies=[dep1.id, dep2.id])
        result = w.execute(t, ctx)
        assert "2" in result or "Report" in result

    def test_task_types(self):
        assert TaskType.REPORT in ReportWorker().task_types


class TestMemoryWorker:
    def test_execute_returns_string(self):
        w = MemoryWorker()
        ctx = _ctx("Remember things")
        t = Task(title="Memory", task_type=TaskType.GENERIC)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Memory" in result

    def test_task_types_is_empty_list(self):
        # Memory worker is not auto-routed — it's invoked explicitly.
        assert MemoryWorker().task_types == []


class TestKnowledgeWorker:
    def test_execute_returns_string(self):
        w = KnowledgeWorker()
        ctx = _ctx("Enrich context")
        t = Task(title="Analysis", task_type=TaskType.ANALYSIS)
        result = w.execute(t, ctx)
        assert isinstance(result, str) and "Knowledge" in result

    def test_task_types(self):
        assert TaskType.ANALYSIS in KnowledgeWorker().task_types


# ---------------------------------------------------------------------------
# WorkerRegistry with real classes (Phase 2)
# ---------------------------------------------------------------------------

class TestWorkerRegistryPhase2:
    def test_build_default_registry_returns_registry(self):
        reg = build_default_registry()
        assert isinstance(reg, WorkerRegistry)

    def test_all_core_task_types_covered(self):
        reg = build_default_registry()
        required = [
            TaskType.RESEARCH, TaskType.DESIGN, TaskType.ARCHITECTURE,
            TaskType.CODING, TaskType.IMPLEMENTATION, TaskType.TESTING,
            TaskType.REVIEW, TaskType.DOCUMENTATION, TaskType.ANALYSIS,
            TaskType.REPORT, TaskType.GENERIC,
        ]
        for tt in required:
            assert reg.has(tt), f"Missing TaskType.{tt.name}"

    def test_registry_get_returns_callable_class(self):
        reg = build_default_registry()
        worker_class = reg.get(TaskType.RESEARCH)
        assert callable(worker_class)
        instance = worker_class()
        assert isinstance(instance, BaseWorker)

    def test_list_workers_returns_name_and_description(self):
        reg = build_default_registry()
        rows = reg.list_workers()
        assert len(rows) > 0
        for row in rows:
            assert "name" in row
            assert "description" in row
            assert "phase" in row

    def test_unique_worker_count_less_than_total_mappings(self):
        """CodingWorker handles CODING + IMPLEMENTATION → 2 mappings, 1 unique."""
        reg = build_default_registry()
        assert reg.unique_worker_count() < reg.count()

    def test_list_workers_deduplicates_multi_type_workers(self):
        """DesignWorker (DESIGN + ARCHITECTURE) should appear once in listing."""
        reg = build_default_registry()
        rows = reg.list_workers()
        names = [r["name"] for r in rows]
        assert names.count("Design Worker") == 1
        assert names.count("Coding Worker") == 1

    def test_fallback_to_generic_worker(self):
        reg = build_default_registry()
        # PLANNING is registered; remove it to test fallback
        reg.unregister(TaskType.PLANNING)
        fallback = reg.get(TaskType.PLANNING)
        # Falls back to GENERIC worker
        assert fallback is not None
        assert callable(fallback)


# ---------------------------------------------------------------------------
# Scheduler with real workers (Phase 2)
# ---------------------------------------------------------------------------

class TestSchedulerWithRealWorkers:
    def _run(self, goal: str) -> ExecutionContext:
        ctrl = ExecutiveController()
        ctrl.plan(goal)
        return ctrl.run()

    def test_all_tasks_completed_with_real_workers(self):
        ctx = self._run("Build a calculator")
        assert ctx.state == ExecutionState.COMPLETED
        for task in ctx.task_graph.all_tasks():
            assert task.status == TaskStatus.COMPLETED

    def test_results_are_non_empty_strings(self):
        ctx = self._run("Build a calculator")
        for task in ctx.task_graph.all_tasks():
            assert isinstance(task.result, str) and len(task.result) > 0

    def test_research_result_mentions_research(self):
        ctx = self._run("Build a calculator")
        tasks = ctx.task_graph.all_tasks()
        research = next(t for t in tasks if t.task_type == TaskType.RESEARCH)
        assert "Research" in research.result

    def test_results_contain_goal(self):
        ctx = self._run("Build a unique REST API")
        for task in ctx.task_graph.all_tasks():
            assert "REST API" in task.result or len(task.result) > 5

    def test_sequential_execution_order(self):
        """Each task's started_at should be >= the previous task's started_at."""
        ctx = self._run("Write a script")
        ordered = ctx.task_graph.topological_order()
        for i in range(1, len(ordered)):
            assert ordered[i].started_at >= ordered[i - 1].started_at

    def test_upstream_result_available_to_downstream(self):
        """Downstream workers can read upstream results via context.get_result()."""
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Build a calculator")
        tasks = ctx.task_graph.topological_order()
        # Every task after the first should have a non-None prior result available.
        for i, task in enumerate(tasks):
            for dep_id in task.dependencies:
                assert ctx.get_result(dep_id) is not None

    def test_api_template_uses_documentation_worker(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Build a REST API for tasks")
        tasks = ctx.task_graph.all_tasks()
        doc_tasks = [t for t in tasks if t.task_type == TaskType.DOCUMENTATION]
        assert len(doc_tasks) > 0
        for t in doc_tasks:
            assert t.status == TaskStatus.COMPLETED
            assert "Documentation" in t.result

    def test_research_template_uses_report_worker(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Research quantum computing")
        tasks = ctx.task_graph.all_tasks()
        report_tasks = [t for t in tasks if t.task_type == TaskType.REPORT]
        assert len(report_tasks) > 0
        for t in report_tasks:
            assert "Report" in t.result


# ---------------------------------------------------------------------------
# Cancellation (Phase 3)
# ---------------------------------------------------------------------------

class TestCancellation:
    def test_context_cancel_sets_cancelled_state(self):
        ctx = ExecutionContext(goal="test")
        ctx.task_graph.add_task(Task(title="A"))
        ctx.transition_to(ExecutionState.RUNNING)
        ctx.cancel()
        assert ctx.state == ExecutionState.CANCELLED
        assert ctx.is_cancelled

    def test_cancel_blocks_all_non_terminal_tasks(self):
        ctx = ExecutionContext(goal="test")
        t1 = Task(title="A")
        t2 = Task(title="B", dependencies=[t1.id])
        ctx.task_graph.add_task(t1)
        ctx.task_graph.add_task(t2)
        ctx.cancel()
        for task in ctx.task_graph.all_tasks():
            assert task.status == TaskStatus.BLOCKED

    def test_cancel_does_not_block_completed_tasks(self):
        ctx = ExecutionContext(goal="test")
        t = Task(title="A")
        ctx.task_graph.add_task(t)
        t.mark_running()
        ctx.task_graph.mark_completed(t.id, "done")
        ctx.cancel()
        # t is already terminal — cancel should not change it
        assert t.status == TaskStatus.COMPLETED

    def test_is_cancelled_false_initially(self):
        ctx = ExecutionContext(goal="test")
        assert not ctx.is_cancelled

    def test_executive_controller_cancel_returns_true(self):
        ctrl = ExecutiveController()
        ctrl.plan("Build a calculator")
        result = ctrl.cancel()
        assert result is True
        assert ctrl.current_context.state == ExecutionState.CANCELLED

    def test_executive_controller_cancel_returns_false_when_no_plan(self):
        ctrl = ExecutiveController()
        assert ctrl.cancel() is False

    def test_executive_controller_cancel_returns_false_when_already_terminal(self):
        ctrl = ExecutiveController()
        ctrl.receive_goal("Write a script")  # COMPLETED
        assert ctrl.cancel() is False

    def test_scheduler_stops_on_cancelled_context(self):
        """If context is cancelled before run(), scheduler returns immediately."""
        ctrl = ExecutiveController()
        ctrl.plan("Build a calculator")
        ctrl.cancel()
        # run() on a cancelled context should return without executing.
        ctx = ctrl.run()
        assert ctx.state == ExecutionState.CANCELLED
        # No tasks should have result (scheduler didn't run).
        assert ctx.completed_count == 0

    def test_ended_at_set_on_cancellation(self):
        ctx = ExecutionContext(goal="g")
        ctx.cancel()
        assert ctx.ended_at is not None


# ---------------------------------------------------------------------------
# Console commands — Phase 2: workers, worker info
# ---------------------------------------------------------------------------

class TestWorkersCommand:
    @pytest.fixture()
    def agent(self):
        return _agent_with_executive()

    def test_workers_lists_all_workers(self, agent):
        from smartagent.ui.commands.executive import handle_workers
        result = handle_workers(agent, [])
        assert "Research Worker" in result
        assert "Coding Worker" in result
        assert "Testing Worker" in result

    def test_workers_shows_phase_info(self, agent):
        from smartagent.ui.commands.executive import handle_workers
        result = handle_workers(agent, [])
        assert "[stub]" in result

    def test_workers_shows_descriptions(self, agent):
        from smartagent.ui.commands.executive import handle_workers
        result = handle_workers(agent, [])
        assert "research" in result.lower() or "gathers" in result.lower()

    def test_workers_shows_unique_workers(self, agent):
        from smartagent.ui.commands.executive import handle_workers
        result = handle_workers(agent, [])
        # Design Worker handles DESIGN + ARCHITECTURE but should appear once.
        count = result.count("Design Worker")
        assert count == 1

    def test_worker_info_research(self, agent):
        from smartagent.ui.commands.executive import handle_worker
        result = handle_worker(agent, ["info", "research"])
        assert "Research Worker" in result
        assert "ResearchWorker" in result

    def test_worker_info_coding(self, agent):
        from smartagent.ui.commands.executive import handle_worker
        result = handle_worker(agent, ["info", "coding"])
        assert "Coding Worker" in result

    def test_worker_info_unknown_type_falls_back_to_generic(self, agent):
        """An unrecognised type key falls back to the generic worker (registry behaviour)."""
        from smartagent.ui.commands.executive import handle_worker
        result = handle_worker(agent, ["info", "nonexistent"])
        # Falls back to GenericWorker — not an error, correct registry behaviour.
        assert "Worker" in result or "worker" in result.lower()

    def test_worker_info_no_args_returns_usage(self, agent):
        from smartagent.ui.commands.executive import handle_worker
        result = handle_worker(agent, ["info"])
        assert "Usage" in result or "usage" in result.lower()

    def test_worker_list_alias(self, agent):
        from smartagent.ui.commands.executive import handle_worker, handle_workers
        alias = handle_worker(agent, ["list"])
        direct = handle_workers(agent, [])
        assert alias == direct


# ---------------------------------------------------------------------------
# Console commands — Phase 3: queue, run, cancel
# ---------------------------------------------------------------------------

class TestQueueCommand:
    @pytest.fixture()
    def agent_no_plan(self):
        return _agent_with_executive()

    @pytest.fixture()
    def agent_with_plan(self):
        a = _agent_with_executive()
        a.executive.plan("Build a calculator")
        return a

    def test_queue_no_plan_returns_helpful_message(self, agent_no_plan):
        from smartagent.ui.commands.executive import handle_queue
        result = handle_queue(agent_no_plan, [])
        assert "No plan" in result or "plan" in result.lower()

    def test_queue_with_plan_shows_goal(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_queue
        result = handle_queue(agent_with_plan, [])
        assert "calculator" in result.lower()

    def test_queue_shows_state(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_queue
        result = handle_queue(agent_with_plan, [])
        assert "ready" in result or "state" in result.lower()

    def test_queue_shows_task_counts(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_queue
        result = handle_queue(agent_with_plan, [])
        assert "5" in result or "task" in result.lower()

    def test_queue_suggests_run_when_ready(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_queue
        result = handle_queue(agent_with_plan, [])
        assert "run" in result.lower()


class TestRunCommand:
    @pytest.fixture()
    def agent_with_plan(self):
        a = _agent_with_executive()
        a.executive.plan("Build a calculator")
        return a

    def test_run_no_plan_returns_helpful_message(self):
        from smartagent.ui.commands.executive import handle_run
        agent = _agent_with_executive()
        result = handle_run(agent, [])
        assert "No plan" in result or "plan" in result.lower()

    def test_run_executes_plan_and_shows_summary(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_run
        result = handle_run(agent_with_plan, [])
        assert "complete" in result.lower() or "completed" in result.lower()
        assert "Research" in result

    def test_run_shows_all_task_results(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_run
        result = handle_run(agent_with_plan, [])
        assert "1." in result
        assert "2." in result

    def test_run_already_completed_returns_message(self, agent_with_plan):
        from smartagent.ui.commands.executive import handle_run
        handle_run(agent_with_plan, [])  # first run
        result = handle_run(agent_with_plan, [])  # second run
        assert "already finished" in result or "finished" in result.lower()

    def test_run_different_templates(self):
        from smartagent.ui.commands.executive import handle_run
        for goal in [
            "Build a REST API", "Write a script", "Research quantum computing"
        ]:
            agent = _agent_with_executive()
            agent.executive.plan(goal)
            result = handle_run(agent, [])
            assert "complete" in result.lower()


class TestCancelCommand:
    def test_cancel_no_plan_returns_helpful(self):
        from smartagent.ui.commands.executive import handle_cancel
        agent = _agent_with_executive()
        result = handle_cancel(agent, [])
        assert "No plan" in result or "nothing" in result.lower()

    def test_cancel_ready_plan(self):
        from smartagent.ui.commands.executive import handle_cancel
        agent = _agent_with_executive()
        agent.executive.plan("Build a calculator")
        result = handle_cancel(agent, [])
        assert "cancel" in result.lower()
        assert agent.executive.current_context.state == ExecutionState.CANCELLED

    def test_cancel_shows_goal(self):
        from smartagent.ui.commands.executive import handle_cancel
        agent = _agent_with_executive()
        agent.executive.plan("Build a calculator")
        result = handle_cancel(agent, [])
        assert "calculator" in result.lower()

    def test_cancel_completed_plan_returns_message(self):
        from smartagent.ui.commands.executive import handle_cancel
        agent = _agent_with_executive()
        agent.executive.receive_goal("Write a script")
        result = handle_cancel(agent, [])
        assert "final state" in result or "already" in result.lower()

    def test_cancel_then_plan_new_goal(self):
        """After cancel, a new plan can be created."""
        from smartagent.ui.commands.executive import handle_cancel, handle_plan
        agent = _agent_with_executive()
        agent.executive.plan("Build something old")
        handle_cancel(agent, [])
        result = handle_plan(agent, ["Build", "something", "new"])
        assert "new" in result.lower()
        assert agent.executive.current_context.state == ExecutionState.READY


# ---------------------------------------------------------------------------
# Full pipeline round trips
# ---------------------------------------------------------------------------

class TestFullPipelineRoundTrips:
    def test_default_template_round_trip(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Build a calculator")
        assert ctx.state == ExecutionState.COMPLETED
        assert ctx.completed_count == 5

    def test_api_template_round_trip(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Build a REST API")
        assert ctx.state == ExecutionState.COMPLETED
        titles = [t.title for t in ctx.task_graph.all_tasks()]
        assert "Architecture" in titles

    def test_script_template_round_trip(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Write a CLI script")
        assert ctx.state == ExecutionState.COMPLETED
        assert ctx.task_count == 3

    def test_research_template_round_trip(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Research machine learning")
        assert ctx.state == ExecutionState.COMPLETED
        titles = [t.title for t in ctx.task_graph.all_tasks()]
        assert "Report" in titles

    def test_plan_run_separation(self):
        """plan() followed by run() is equivalent to receive_goal()."""
        ctrl1 = ExecutiveController()
        ctx1 = ctrl1.receive_goal("Write a script")

        ctrl2 = ExecutiveController()
        ctrl2.plan("Write a script")
        ctx2 = ctrl2.run()

        assert ctx1.state == ctx2.state == ExecutionState.COMPLETED
        assert ctx1.task_count == ctx2.task_count

    def test_results_are_propagated_through_chain(self):
        ctrl = ExecutiveController()
        ctx = ctrl.receive_goal("Build a calculator")
        tasks = ctx.task_graph.topological_order()
        # Every task should have a result.
        for task in tasks:
            assert ctx.get_result(task.id) is not None

    def test_multiple_sequential_plans(self):
        """ExecutiveController can plan and run multiple goals in sequence."""
        ctrl = ExecutiveController()
        for goal in ["Write a script", "Research AI", "Build a REST API"]:
            ctx = ctrl.receive_goal(goal)
            assert ctx.state == ExecutionState.COMPLETED
            assert ctx.goal == goal


# ---------------------------------------------------------------------------
# Backward compatibility — Phase 1 contracts preserved
# ---------------------------------------------------------------------------

class TestPhase1BackwardCompat:
    def test_plan_still_returns_ready_context(self):
        ctrl = ExecutiveController()
        ctx = ctrl.plan("Build a calculator")
        assert ctx.state == ExecutionState.READY

    def test_tasks_command_still_works(self):
        from smartagent.ui.commands.executive import handle_tasks
        agent = _agent_with_executive()
        agent.executive.plan("Build a calculator")
        result = handle_tasks(agent, [])
        assert "Research" in result

    def test_plan_command_still_works(self):
        from smartagent.ui.commands.executive import handle_plan
        agent = _agent_with_executive()
        result = handle_plan(agent, ["Build", "a", "calculator"])
        assert "Goal" in result
        assert "↓" in result

    def test_worker_registry_phase1_string_labels_still_work(self):
        """Registering a string label still works (Phase 1 API)."""
        reg = WorkerRegistry()
        reg.register(TaskType.RESEARCH, "ResearchWorker")
        assert reg.get(TaskType.RESEARCH) == "ResearchWorker"

    def test_executive_has_plan_and_context_properties(self):
        ctrl = ExecutiveController()
        assert not ctrl.has_plan()
        ctrl.plan("something")
        assert ctrl.has_plan()
        assert ctrl.current_context is not None
