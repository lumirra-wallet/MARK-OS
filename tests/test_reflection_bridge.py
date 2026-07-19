"""Tests for smartagent.server.reflection_bridge — wiring DevPipeline's real
mission results into the (previously dormant) reflection/ReflectionEngine.
See reflection_bridge.py's module docstring for why this translation
exists: DevPipeline and ReflectionEngine were built for two different,
never-reconciled pipelines, and reflection_bridge is the seam between
them — not a place learning lives on its own (that's agent.reflection_engine,
now that smartagent.server.api keeps one persistent agent per process)."""

from __future__ import annotations

from types import SimpleNamespace

from smartagent.engineer.dev_pipeline import MilestoneResult, PipelineResult
from smartagent.reflection.reflection_engine import ReflectionEngine
from smartagent.server.reflection_bridge import (
    _build_execution_context, reflect_on_pipeline_result,
)


def _pipeline_result(*, all_pass: bool = True) -> PipelineResult:
    milestones = [
        MilestoneResult(milestone="Create app.py", success=True, elapsed=4.2, review="PASS: looks correct."),
        MilestoneResult(milestone="Write tests", success=all_pass, elapsed=2.1, review="PASS: tests cover the endpoints." if all_pass else "FAIL: missing edge case."),
    ]
    return PipelineResult(
        goal="Build a Flask TODO API",
        success=all_pass,
        milestones=[m.milestone for m in milestones],
        milestone_results=milestones,
        total_elapsed=6.3,
        summary="Built the API.",
    )


def _fake_agent() -> SimpleNamespace:
    return SimpleNamespace(reflection_engine=ReflectionEngine())


class TestBuildExecutionContext:
    def test_maps_each_milestone_to_a_task(self):
        context = _build_execution_context(_pipeline_result())
        assert context.task_count == 2
        assert context.goal == "Build a Flask TODO API"

    def test_success_and_failure_map_to_real_statuses(self):
        context = _build_execution_context(_pipeline_result(all_pass=False))
        assert context.completed_count == 1
        assert context.failed_count == 1
        assert context.has_failures

    def test_confidence_is_binary_not_fabricated(self):
        """DevPipeline has no graded confidence signal, only pass/fail —
        the adapter must not invent a number in between."""
        context = _build_execution_context(_pipeline_result(all_pass=False))
        confidences = set(context.metadata["task_confidence"].values())
        assert confidences <= {0.0, 1.0}

    def test_timing_comes_from_the_real_milestone_elapsed(self):
        context = _build_execution_context(_pipeline_result())
        timings = list(context.metadata["task_timing"].values())
        assert sorted(timings) == [2.1, 4.2]

    def test_overall_state_reflects_overall_success(self):
        ok = _build_execution_context(_pipeline_result(all_pass=True))
        bad = _build_execution_context(_pipeline_result(all_pass=False))
        assert ok.state.value == "completed"
        assert bad.state.value == "failed"


class TestReflectOnPipelineResult:
    def test_reflects_using_the_agents_own_reflection_engine(self):
        agent = _fake_agent()
        result = reflect_on_pipeline_result(_pipeline_result(), agent)
        assert result is not None
        assert result.report.goal == "Build a Flask TODO API"
        assert result.report.task_count == 2
        assert result.report.completed_count == 2

    def test_never_raises_on_bad_input(self):
        agent = _fake_agent()
        broken = PipelineResult(goal="", success=False, milestone_results=[])
        result = reflect_on_pipeline_result(broken, agent)
        assert result is not None  # best-effort contract, same as ReflectionEngine itself

    def test_accumulates_on_the_agents_persistent_engine_across_calls(self):
        """Learning persists because it lives on the one persistent agent,
        not inside this bridge — two calls against the same agent must
        both land in the same learning store."""
        agent = _fake_agent()
        reflect_on_pipeline_result(_pipeline_result(), agent)
        reflect_on_pipeline_result(_pipeline_result(), agent)
        assert len(agent.reflection_engine.learning_store.execution_history()) == 2

    def test_never_raises_if_the_agent_has_no_reflection_engine(self):
        broken_agent = SimpleNamespace()
        result = reflect_on_pipeline_result(_pipeline_result(), broken_agent)
        assert result is None
