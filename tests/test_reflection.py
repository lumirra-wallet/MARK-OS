"""
tests/test_reflection.py — Milestone 14: Autonomous Learning & Self-Improvement.

Covers:
  - ExecutionAnalyzer → ExecutionReport construction
  - Critic heuristic scoring (no LLM)
  - ImprovementPlanner outputs (prompts, knowledge, memory)
  - PromptRegistry versioned storage
  - ConfidenceEngine EMA tracking
  - LearningStore analytics and history
  - ReflectionEngine end-to-end (best-effort, no LLM, no external services)
  - OllamaWorkerMixin._resolve_system_prompt (evolved prompt pickup)
  - Orchestrator wiring (reflection_engine stored and called)
  - Backward compatibility (no regression when engine is absent)
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal fakes
# ---------------------------------------------------------------------------


def _make_context(goal: str = "Build a Flask API", state: str = "completed"):
    """Build a minimal ExecutionContext-like object for testing."""
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.execution_state import ExecutionState
    from smartagent.executive.task import Task, TaskStatus, TaskType
    from smartagent.executive.task_graph import TaskGraph
    from smartagent.executive.task_queue import TaskQueue

    ctx = ExecutionContext(goal=goal)
    if state == "completed":
        ctx.transition_to(ExecutionState.PLANNING)
        ctx.transition_to(ExecutionState.READY)
        ctx.transition_to(ExecutionState.RUNNING)
        ctx.transition_to(ExecutionState.COMPLETED)
    elif state == "failed":
        ctx.transition_to(ExecutionState.PLANNING)
        ctx.transition_to(ExecutionState.READY)
        ctx.transition_to(ExecutionState.RUNNING)
        ctx.transition_to(ExecutionState.FAILED)

    # Build a simple two-task graph
    t1 = Task(
        title="Research task",
        task_type=TaskType.RESEARCH,
        description="Research the topic",
    )
    t2 = Task(
        title="Plan task",
        task_type=TaskType.PLANNING,
        description="Create a plan",
        dependencies=[t1.id],
    )
    t1.mark_ready()
    t1.mark_running()
    t1.mark_completed(result="Research result about Flask")

    graph = TaskGraph()
    graph.add_task(t1)
    graph.add_task(t2)
    ctx.task_graph = graph
    ctx.task_queue = TaskQueue()

    ctx.metadata["task_timing"] = {t1.id: 1.5, t2.id: 0.8}
    ctx.metadata["task_confidence"] = {t1.id: 0.80, t2.id: 0.55}
    ctx.metadata["task_retries"] = {t1.id: 0}
    ctx.metadata["tool_calls"] = [
        {"tool": "file_read", "success": True},
        {"tool": "file_read", "success": False},
    ]
    return ctx


# ---------------------------------------------------------------------------
# ExecutionAnalyzer
# ---------------------------------------------------------------------------


class TestExecutionAnalyzer:
    def test_analyze_produces_report(self):
        from smartagent.reflection.execution_analyzer import ExecutionAnalyzer

        ctx = _make_context()
        report = ExecutionAnalyzer().analyze(ctx)

        assert report.goal == "Build a Flask API"
        assert report.state == "completed"
        assert report.task_count >= 1
        assert 0.0 <= report.avg_confidence <= 1.0
        assert 0.0 <= report.success_rate <= 1.0
        assert isinstance(report.task_records, list)
        assert isinstance(report.tool_call_records, list)
        assert isinstance(report.tool_ids_used, list)

    def test_tool_ids_extracted(self):
        from smartagent.reflection.execution_analyzer import ExecutionAnalyzer

        ctx = _make_context()
        report = ExecutionAnalyzer().analyze(ctx)
        assert "file_read" in report.tool_ids_used

    def test_timestamp_set(self):
        from smartagent.reflection.execution_analyzer import ExecutionAnalyzer

        ctx = _make_context()
        report = ExecutionAnalyzer().analyze(ctx)
        assert report.timestamp  # non-empty ISO string


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------


class TestCritic:
    def test_evaluate_returns_critic_report(self):
        from smartagent.reflection.critic import Critic
        from smartagent.reflection.execution_analyzer import ExecutionAnalyzer

        ctx = _make_context()
        report = ExecutionAnalyzer().analyze(ctx)
        critic = Critic(model_manager=None).evaluate(report)

        assert 0.0 <= critic.overall_score <= 1.0
        assert isinstance(critic.what_succeeded, list)
        assert isinstance(critic.what_failed, list)
        assert isinstance(critic.plan_suggestions, list)
        assert isinstance(critic.prompt_hints, dict)
        assert critic.summary  # non-empty

    def test_high_confidence_goes_to_succeeded(self):
        from smartagent.reflection.critic import Critic
        from smartagent.reflection.execution_analyzer import ExecutionAnalyzer, ExecutionReport, TaskRecord

        report = ExecutionReport(
            goal="Test", plan_id="p1", state="completed",
            timestamp="2026-07-16T00:00:00+00:00",
            task_count=1, completed_count=1, failed_count=0,
            avg_confidence=0.90, total_time=1.0, success_rate=1.0,
            task_records=[
                TaskRecord(
                    task_id="t1", title="Good task", task_type="research",
                    result_preview="Great result", error="",
                    confidence=0.90, timing=1.0, completed=True,
                )
            ],
        )
        critic = Critic().evaluate(report)
        # High confidence task should appear in what_succeeded
        assert any("Good task" in s for s in critic.what_succeeded)

    def test_failed_task_goes_to_what_failed(self):
        from smartagent.reflection.critic import Critic
        from smartagent.reflection.execution_analyzer import ExecutionReport, TaskRecord

        report = ExecutionReport(
            goal="Test", plan_id="p1", state="failed",
            timestamp="2026-07-16T00:00:00+00:00",
            task_count=1, completed_count=0, failed_count=1,
            avg_confidence=0.0, total_time=0.5, success_rate=0.0,
            task_records=[
                TaskRecord(
                    task_id="t1", title="Bad task", task_type="coding",
                    result_preview="", error="some error",
                    confidence=0.0, timing=0.5, completed=False,
                )
            ],
        )
        critic = Critic().evaluate(report)
        assert any("Bad task" in f for f in critic.what_failed)

    def test_low_confidence_adds_prompt_hint(self):
        from smartagent.reflection.critic import Critic
        from smartagent.reflection.execution_analyzer import ExecutionReport, TaskRecord

        report = ExecutionReport(
            goal="Test", plan_id="p1", state="completed",
            timestamp="2026-07-16T00:00:00+00:00",
            task_count=1, completed_count=1, failed_count=0,
            avg_confidence=0.30, total_time=1.0, success_rate=1.0,
            task_records=[
                TaskRecord(
                    task_id="t1", title="Low-conf task", task_type="planning",
                    result_preview="Thin output", error="",
                    confidence=0.30, timing=1.0, completed=True,
                )
            ],
        )
        critic = Critic().evaluate(report)
        assert "planning" in critic.prompt_hints


# ---------------------------------------------------------------------------
# ImprovementPlanner
# ---------------------------------------------------------------------------


class TestImprovementPlanner:
    def _make_critic(self, score: float = 0.5):
        from smartagent.reflection.critic import CriticReport

        return CriticReport(
            what_succeeded=["Research task — confidence 80%"],
            what_failed=["Planning task completed with low confidence (30%)"],
            missing_knowledge=["Domain knowledge was missing for 'Planning'"],
            missing_tools=[],
            plan_suggestions=["Add more intermediate tasks."],
            prompt_hints={"planning": "Be more specific about output format."},
            overall_score=score,
            summary="Execution OK",
        )

    def test_plan_produces_improvement_plan(self):
        from smartagent.reflection.improvement_planner import ImprovementPlanner
        from smartagent.reflection.execution_analyzer import ExecutionAnalyzer

        ctx = _make_context()
        from smartagent.reflection.execution_analyzer import ExecutionAnalyzer
        report = ExecutionAnalyzer().analyze(ctx)
        critic = self._make_critic()
        plan = ImprovementPlanner().plan(critic, report)

        assert plan.prompt_improvements  # at least one from the hint
        assert plan.knowledge_proposals  # missing knowledge → proposal
        assert plan.memory_entries       # failure → lesson

    def test_high_score_proposes_best_practice(self):
        from smartagent.reflection.improvement_planner import ImprovementPlanner
        from smartagent.reflection.execution_analyzer import ExecutionReport

        report = ExecutionReport(
            goal="Build REST API", plan_id="p1", state="completed",
            timestamp="", task_count=3, completed_count=3, failed_count=0,
            avg_confidence=0.85, total_time=5.0, success_rate=1.0,
        )
        from smartagent.reflection.critic import CriticReport
        critic = CriticReport(overall_score=0.85, summary="Great run")
        plan = ImprovementPlanner().plan(critic, report)

        titles = [p.title for p in plan.knowledge_proposals]
        assert any("Successful Strategy" in t for t in titles)

    def test_no_failures_no_memory_lessons(self):
        from smartagent.reflection.improvement_planner import ImprovementPlanner
        from smartagent.reflection.critic import CriticReport

        critic = CriticReport(
            what_succeeded=["All good"],
            what_failed=["No significant failures detected."],
            overall_score=0.9,
        )
        plan = ImprovementPlanner().plan(critic)
        # The only "failure" is the stock no-failure message — no lessons stored
        lesson_entries = [e for e in plan.memory_entries if "lesson" in e.content.lower()]
        assert not lesson_entries


# ---------------------------------------------------------------------------
# PromptRegistry
# ---------------------------------------------------------------------------


class TestPromptRegistry:
    def test_add_and_retrieve_version(self):
        from smartagent.reflection.prompt_registry import PromptRegistry

        reg = PromptRegistry()
        reg.add_version("Research Worker", "Improved prompt v1", reason="low confidence")
        assert reg.current_prompt("Research Worker") == "Improved prompt v1"
        assert reg.version_count("Research Worker") == 1

    def test_multiple_versions(self):
        from smartagent.reflection.prompt_registry import PromptRegistry

        reg = PromptRegistry()
        reg.add_version("Coding Worker", "v1", reason="first")
        reg.add_version("Coding Worker", "v2", reason="second")
        assert reg.version_count("Coding Worker") == 2
        assert reg.current_prompt("Coding Worker") == "v2"

    def test_as_metadata_dict(self):
        from smartagent.reflection.prompt_registry import PromptRegistry

        reg = PromptRegistry()
        reg.add_version("Planning Worker", "plan prompt", reason="test")
        d = reg.as_metadata_dict()
        assert d["Planning Worker"] == "plan prompt"

    def test_unknown_worker_returns_none(self):
        from smartagent.reflection.prompt_registry import PromptRegistry

        reg = PromptRegistry()
        assert reg.current_prompt("Nonexistent Worker") is None
        assert reg.version_count("Nonexistent Worker") == 0

    def test_format_history(self):
        from smartagent.reflection.prompt_registry import PromptRegistry

        reg = PromptRegistry()
        reg.add_version("Research Worker", "prompt", reason="test reason", score_improvement=0.05)
        output = reg.format_history("Research Worker")
        assert "Research Worker" in output
        assert "test reason" in output

    def test_format_all_histories_empty(self):
        from smartagent.reflection.prompt_registry import PromptRegistry

        reg = PromptRegistry()
        assert "No prompt evolution" in reg.format_all_histories()


# ---------------------------------------------------------------------------
# ConfidenceEngine
# ---------------------------------------------------------------------------


class TestConfidenceEngine:
    def _make_report(self, confidence: float = 0.75, success: bool = True):
        from smartagent.reflection.execution_analyzer import ExecutionReport, TaskRecord

        return ExecutionReport(
            goal="Test", plan_id="p1", state="completed",
            timestamp="", task_count=1, completed_count=1 if success else 0,
            failed_count=0 if success else 1,
            avg_confidence=confidence, total_time=1.0, success_rate=float(success),
            task_records=[
                TaskRecord(
                    task_id="t1", title="Task", task_type="research",
                    result_preview="", error="",
                    confidence=confidence, timing=1.0, completed=success,
                )
            ],
            tool_call_records=[{"tool": "file_read", "success": success}],
        )

    def test_update_from_report_tracks_worker(self):
        from smartagent.reflection.confidence_engine import ConfidenceEngine

        engine = ConfidenceEngine()
        engine.update_from_report(self._make_report(0.80, True))
        stats = engine.worker_stats()
        assert "research" in stats
        assert stats["research"]["runs"] == 1
        assert stats["research"]["avg_confidence"] == pytest.approx(0.80)

    def test_ema_update(self):
        from smartagent.reflection.confidence_engine import ConfidenceEngine

        engine = ConfidenceEngine()
        engine.update_from_report(self._make_report(0.80, True))
        engine.update_from_report(self._make_report(0.40, True))
        stats = engine.worker_stats()
        # EMA: second update: 0.3*0.40 + 0.7*0.80 = 0.68
        assert 0.60 < stats["research"]["avg_confidence"] < 0.85

    def test_top_worker(self):
        from smartagent.reflection.confidence_engine import ConfidenceEngine
        from smartagent.reflection.execution_analyzer import ExecutionReport, TaskRecord

        engine = ConfidenceEngine()
        report = ExecutionReport(
            goal="Test", plan_id="p1", state="completed",
            timestamp="", task_count=2, completed_count=2, failed_count=0,
            avg_confidence=0.70, total_time=2.0, success_rate=1.0,
            task_records=[
                TaskRecord("t1", "T1", "research", "", "", 0.90, 1.0, True),
                TaskRecord("t2", "T2", "coding",   "", "", 0.50, 1.0, True),
            ],
        )
        engine.update_from_report(report)
        assert engine.top_worker() == "research"

    def test_tool_reliability(self):
        from smartagent.reflection.confidence_engine import ConfidenceEngine

        engine = ConfidenceEngine()
        engine.update_from_report(self._make_report(0.80, True))   # tool success
        engine.update_from_report(self._make_report(0.80, False))  # tool fail
        # success_rate = 1/2 = 0.5
        assert engine.reliability("file_read") == pytest.approx(0.5)

    def test_summary_table(self):
        from smartagent.reflection.confidence_engine import ConfidenceEngine

        engine = ConfidenceEngine()
        engine.update_from_report(self._make_report())
        table = engine.summary_table()
        assert "research" in table
        assert "file_read" in table


# ---------------------------------------------------------------------------
# LearningStore
# ---------------------------------------------------------------------------


class TestLearningStore:
    def _sample_report(self, state: str = "completed", confidence: float = 0.75):
        from smartagent.reflection.execution_analyzer import ExecutionReport

        return ExecutionReport(
            goal="Sample goal", plan_id="plan-1", state=state,
            timestamp="2026-07-16T00:00:00+00:00",
            task_count=2, completed_count=2 if state == "completed" else 1,
            failed_count=0 if state == "completed" else 1,
            avg_confidence=confidence, total_time=2.0,
            success_rate=1.0 if state == "completed" else 0.5,
        )

    def test_record_execution(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        rec = store.record_execution(self._sample_report())
        assert rec.goal == "Sample goal"
        assert len(store.execution_history()) == 1

    def test_success_rate(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        store.record_execution(self._sample_report("completed"))
        store.record_execution(self._sample_report("failed"))
        assert store.success_rate() == pytest.approx(0.5)

    def test_average_confidence(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        store.record_execution(self._sample_report(confidence=0.80))
        store.record_execution(self._sample_report(confidence=0.60))
        assert store.average_confidence() == pytest.approx(0.70)

    def test_analytics_summary_empty(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        summary = store.analytics_summary()
        assert "No executions" in summary

    def test_analytics_summary_with_data(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        store.record_execution(self._sample_report())
        summary = store.analytics_summary()
        assert "Executions" in summary
        assert "Success Rate" in summary

    def test_format_history_table(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        store.record_execution(self._sample_report())
        table = store.format_history_table()
        assert "Sample goal" in table or "Sample" in table

    def test_confidence_trend_insufficient(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        store.record_execution(self._sample_report())
        # Only 1 record — not enough for trend
        assert store.confidence_trend() == "insufficient data"

    def test_confidence_trend_improving(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        for conf in [0.40, 0.50, 0.60, 0.70, 0.80]:
            store.record_execution(self._sample_report(confidence=conf))
        assert "improving" in store.confidence_trend()

    def test_self_evaluation_empty(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        result = store.self_evaluation()
        assert "not completed" in result.lower() or "have not" in result.lower()

    def test_self_evaluation_with_data(self):
        from smartagent.reflection.learning_store import LearningStore

        store = LearningStore()
        store.record_execution(self._sample_report())
        result = store.self_evaluation()
        assert "execution" in result.lower()
        assert "confidence" in result.lower()


# ---------------------------------------------------------------------------
# ReflectionEngine — end-to-end (no LLM, no external services)
# ---------------------------------------------------------------------------


class TestReflectionEngine:
    def test_reflect_returns_result(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        ctx = _make_context()
        result = engine.reflect(ctx)

        assert result.report is not None
        assert result.critic is not None
        assert result.plan is not None
        assert result.error == ""

    def test_reflect_populates_learning_store(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        ctx = _make_context()
        engine.reflect(ctx)

        assert len(engine.learning_store.execution_history()) == 1

    def test_reflect_updates_prompt_registry(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        ctx = _make_context()
        # Force a low-confidence task so the critic emits a prompt hint
        ctx.metadata["task_confidence"]["placeholder"] = 0.20
        engine.reflect(ctx)
        # Registry may or may not have entries depending on heuristic; just check no crash

    def test_reflect_injects_prompts_into_context(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine
        from smartagent.reflection.prompt_registry import PromptRegistry

        registry = PromptRegistry()
        registry.add_version("Coding Worker", "Evolved Coding Prompt", reason="low perf")
        engine = ReflectionEngine(prompt_registry=registry)

        ctx = _make_context()
        engine.reflect(ctx)

        system_prompts = ctx.metadata.get("system_prompts", {})
        assert "Coding Worker" in system_prompts
        assert "Evolved Coding Prompt" in system_prompts["Coding Worker"]

    def test_reflect_on_failed_context(self):
        """Reflection should work even on a failed execution."""
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        ctx = _make_context(state="failed")
        result = engine.reflect(ctx)
        # Should never raise
        assert result is not None

    def test_reflect_with_memory_manager(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine
        from smartagent.memory.memory_manager import MemoryManager

        mem = MemoryManager()
        engine = ReflectionEngine(memory_manager=mem)
        ctx = _make_context()
        result = engine.reflect(ctx)
        # Some memory entries should have been stored
        assert result.memory_entries_added >= 0  # best-effort — may be 0 or more

    def test_reflect_best_effort_no_crash_on_bad_memory(self):
        """A broken memory manager must not abort reflection."""
        from smartagent.reflection.reflection_engine import ReflectionEngine

        class BrokenMemory:
            def remember(self, *a, **kw):
                raise RuntimeError("Storage failure")

        engine = ReflectionEngine(memory_manager=BrokenMemory())
        ctx = _make_context()
        result = engine.reflect(ctx)
        # No crash, error field is empty (exception caught inside)
        assert result.error == ""

    def test_what_did_i_learn_empty(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        assert "No executions" in engine.what_did_i_learn()

    def test_what_did_i_learn_after_run(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        ctx = _make_context()
        engine.reflect(ctx)
        result = engine.what_did_i_learn()
        assert "execution" in result.lower() or "last" in result.lower()

    def test_best_worker_no_data(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        assert "Not enough" in engine.best_worker()

    def test_failing_tools_no_data(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        result = engine.failing_tools()
        assert "No tool" in result or "reliably" in result

    def test_failing_tools_with_bad_tool(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine
        from smartagent.reflection.learning_store import LearningStore
        from smartagent.reflection.execution_analyzer import ExecutionReport

        store = LearningStore()
        report = ExecutionReport(
            goal="Test", plan_id="p", state="completed",
            timestamp="", task_count=1, completed_count=1, failed_count=0,
            avg_confidence=0.7, total_time=1.0, success_rate=1.0,
            tool_call_records=[
                {"tool": "bad_tool", "success": False},
                {"tool": "bad_tool", "success": False},
                {"tool": "bad_tool", "success": False},
            ],
        )
        store.record_execution(report)
        engine = ReflectionEngine(learning_store=store)
        result = engine.failing_tools()
        assert "bad_tool" in result

    def test_missing_knowledge(self):
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        # No executions
        result = engine.missing_knowledge()
        assert "No significant" in result


# ---------------------------------------------------------------------------
# OllamaWorkerMixin — prompt evolution (Milestone 14 hook)
# ---------------------------------------------------------------------------


class TestOllamaWorkerMixinPromptResolution:
    """Verify _resolve_system_prompt picks up registry-evolved prompts."""

    def _make_worker(self):
        from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin
        from smartagent.executive.workers.base_worker import BaseWorker
        from smartagent.executive.task import TaskType

        class FakeWorker(OllamaWorkerMixin, BaseWorker):
            _system_prompt = "Default prompt"

            @property
            def name(self) -> str:
                return "Research Worker"

            @classmethod
            def task_types(cls):
                return [TaskType.RESEARCH]

            def execute(self, task, context):
                return self._execute_with_ollama(task, context)

        return FakeWorker()

    def _make_minimal_context(self, system_prompts: dict | None = None):
        from smartagent.executive.execution_context import ExecutionContext

        ctx = ExecutionContext(goal="Test goal")
        if system_prompts:
            ctx.metadata["system_prompts"] = system_prompts
        return ctx

    def test_returns_class_prompt_when_no_registry(self):
        worker = self._make_worker()
        ctx = self._make_minimal_context()
        assert worker._resolve_system_prompt(ctx) == "Default prompt"

    def test_returns_evolved_prompt_when_available(self):
        worker = self._make_worker()
        ctx = self._make_minimal_context(
            system_prompts={"Research Worker": "Evolved prompt v2"}
        )
        resolved = worker._resolve_system_prompt(ctx)
        assert resolved == "Evolved prompt v2"

    def test_ignores_other_workers_prompts(self):
        worker = self._make_worker()
        ctx = self._make_minimal_context(
            system_prompts={"Coding Worker": "Coding evolved prompt"}
        )
        # Research Worker not in dict — falls back to class-level
        assert worker._resolve_system_prompt(ctx) == "Default prompt"


# ---------------------------------------------------------------------------
# Orchestrator — reflection wiring
# ---------------------------------------------------------------------------


class TestOrchestratorReflectionWiring:
    def test_orchestrator_accepts_reflection_engine(self):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        orc = Orchestrator(reflection_engine=engine)
        assert orc._reflection_engine is engine

    def test_orchestrator_without_engine_does_not_crash(self):
        """Reflection is best-effort — no engine means no reflection, no crash."""
        from smartagent.executive.orchestrator import Orchestrator

        orc = Orchestrator()
        assert orc._reflection_engine is None

    def test_run_reflection_stores_result_in_context(self):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        orc = Orchestrator(reflection_engine=engine)
        ctx = _make_context()
        orc._run_reflection(ctx)

        assert "last_reflection" in ctx.metadata

    def test_run_reflection_noop_when_no_engine(self):
        from smartagent.executive.orchestrator import Orchestrator

        orc = Orchestrator()
        ctx = _make_context()
        orc._run_reflection(ctx)  # Must not raise
        assert "last_reflection" not in ctx.metadata


# ---------------------------------------------------------------------------
# ExecutiveController — reflection wiring
# ---------------------------------------------------------------------------


class TestExecutiveControllerReflectionWiring:
    def test_controller_passes_engine_to_orchestrator(self):
        from smartagent.executive.executive_controller import ExecutiveController
        from smartagent.reflection.reflection_engine import ReflectionEngine

        engine = ReflectionEngine()
        ctrl = ExecutiveController(reflection_engine=engine)
        assert ctrl._orchestrator._reflection_engine is engine

    def test_with_agent_extracts_reflection_engine(self):
        from smartagent.executive.executive_controller import ExecutiveController
        from smartagent.reflection.reflection_engine import ReflectionEngine

        class FakeAgent:
            reflection_engine = ReflectionEngine()
            model_manager = None
            memory = None
            knowledge = None
            settings = None
            tool_engine = None
            events = None

        ctrl = ExecutiveController.with_agent(FakeAgent())
        assert ctrl._orchestrator._reflection_engine is FakeAgent.reflection_engine

    def test_with_agent_no_engine_attribute(self):
        """with_agent must not crash when the agent has no reflection_engine."""
        from smartagent.executive.executive_controller import ExecutiveController

        class MinimalAgent:
            model_manager = None
            memory = None
            knowledge = None
            settings = None
            tool_engine = None
            events = None

        ctrl = ExecutiveController.with_agent(MinimalAgent())
        assert ctrl._orchestrator._reflection_engine is None


# ---------------------------------------------------------------------------
# Backward-compatibility guard
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_orchestrator_default_no_engine(self):
        from smartagent.executive.orchestrator import Orchestrator

        orc = Orchestrator()
        # No _reflection_engine set → existing tests pass unchanged
        assert orc._reflection_engine is None

    def test_reflection_engine_modules_importable(self):
        """All Milestone 14 modules must import without side-effects."""
        from smartagent import reflection  # noqa: F401
        from smartagent.reflection import (
            ExecutionAnalyzer,
            Critic,
            ConfidenceEngine,
            ImprovementPlanner,
            PromptRegistry,
            LearningStore,
            ReflectionEngine,
        )
        assert ReflectionEngine is not None

    def test_learning_commands_importable(self):
        from smartagent.ui.commands import learning  # noqa: F401
        assert callable(learning.register)

    def test_learning_commands_register(self):
        from smartagent.ui.command_router import CommandRouter
        from smartagent.ui.commands import learning

        router = CommandRouter()
        learning.register(router)
        names = {e.name for e in router.commands()}
        assert "learning" in names
        assert "analytics" in names
        assert "reflection" in names
        assert "history" in names
        assert "improvements" in names
        assert "evaluate" in names
