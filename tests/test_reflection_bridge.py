"""Tests for smartagent.server.reflection_bridge — wiring DevPipeline's real
mission results into the (previously dormant) reflection/ReflectionEngine.
See reflection_bridge.py's module docstring for why this translation
exists: DevPipeline and ReflectionEngine were built for two different,
never-reconciled pipelines."""

from __future__ import annotations

from smartagent.engineer.dev_pipeline import MilestoneResult, PipelineResult
from smartagent.server.reflection_bridge import (
    ReflectionBridge, _build_execution_context, get_reflection_bridge,
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


class TestReflectionBridge:
    def test_reflects_without_any_subsystems_wired(self):
        """memory/knowledge/model managers are all optional — reflection
        must still run and return a real result."""
        bridge = ReflectionBridge()
        result = bridge.reflect_on_pipeline_result(_pipeline_result())
        assert result is not None
        assert result.report.goal == "Build a Flask TODO API"
        assert result.report.task_count == 2
        assert result.report.completed_count == 2

    def test_never_raises_on_bad_input(self):
        bridge = ReflectionBridge()
        broken = PipelineResult(goal="", success=False, milestone_results=[])
        result = bridge.reflect_on_pipeline_result(broken)
        assert result is not None  # best-effort contract, same as ReflectionEngine itself

    def test_prompt_registry_and_learning_store_persist_across_calls(self):
        bridge = ReflectionBridge()
        bridge.reflect_on_pipeline_result(_pipeline_result())
        registry_after_first = bridge.prompt_registry
        store_after_first = bridge._learning_store
        bridge.reflect_on_pipeline_result(_pipeline_result())
        assert bridge.prompt_registry is registry_after_first
        assert bridge._learning_store is store_after_first
        assert len(store_after_first.execution_history()) == 2


class TestSingleton:
    def test_get_reflection_bridge_returns_same_instance(self):
        assert get_reflection_bridge() is get_reflection_bridge()
