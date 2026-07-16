"""
Tests for Milestone 23: Long Running Execution.

Coverage:
    PhaseResult:
      · icon returns ✓ / ✗
      · __str__ includes name and elapsed

    CompletionReport:
      · as_display_lines with completed phases
      · as_display_lines with failed phases
      · as_display_lines with remaining
      · as_display_lines shows status
      · as_short_summary format

    LongRunningEngine:
      · run() returns CompletionReport even when CEO is None
      · run() calls CEO execute() with the goal
      · run() populates completed phases from team results
      · run() populates failed phases from team results
      · run() sets success=True when all phases completed
      · run() sets success=False when any phase failed
      · run() fires on_phase_done callback per phase
      · run() enriches goal when project_name + project_memory set
      · run() handles CEO.execute() raising exception
      · _build_report() maps team names to phase labels
      · _persist_summary() calls memory.remember()
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from smartagent.long_running.completion_report import CompletionReport, PhaseResult
from smartagent.long_running.long_running_engine import LongRunningEngine, _team_to_phase_name


# ---------------------------------------------------------------------------
# PhaseResult
# ---------------------------------------------------------------------------

class TestPhaseResult:
    def test_icon_success(self):
        phase = PhaseResult(name="Backend", success=True)
        assert phase.icon == "✓"

    def test_icon_failure(self):
        phase = PhaseResult(name="Backend", success=False)
        assert phase.icon == "✗"

    def test_str_includes_name(self):
        phase = PhaseResult(name="Tests", success=True, elapsed=12.5)
        s = str(phase)
        assert "Tests" in s

    def test_str_includes_elapsed(self):
        phase = PhaseResult(name="Tests", success=True, elapsed=12.5)
        s = str(phase)
        assert "12.5" in s


# ---------------------------------------------------------------------------
# CompletionReport
# ---------------------------------------------------------------------------

class TestCompletionReport:
    def test_as_display_lines_completed(self):
        report = CompletionReport(
            goal="Build SaaS",
            completed=[PhaseResult("Backend", success=True, elapsed=5.0)],
        )
        lines = report.as_display_lines()
        assert any("Backend" in l for l in lines)
        assert any("✓" in l for l in lines)

    def test_as_display_lines_failed(self):
        report = CompletionReport(
            goal="Build SaaS",
            failed=[PhaseResult("Tests", success=False, summary="Import error")],
        )
        lines = report.as_display_lines()
        assert any("Tests" in l for l in lines)
        assert any("✗" in l for l in lines)
        assert any("Import error" in l for l in lines)

    def test_as_display_lines_remaining(self):
        report = CompletionReport(goal="Build SaaS", remaining=["Deployment"])
        lines = report.as_display_lines()
        assert any("Deployment" in l for l in lines)

    def test_as_display_lines_status_success(self):
        report = CompletionReport(
            goal="Build SaaS",
            completed=[PhaseResult("Backend", success=True)],
            success=True,
        )
        lines = report.as_display_lines()
        assert any("SUCCESS" in l for l in lines)

    def test_as_display_lines_status_failed(self):
        report = CompletionReport(
            goal="Build SaaS",
            failed=[PhaseResult("Backend", success=False)],
            success=False,
        )
        lines = report.as_display_lines()
        assert any("FAILED" in l or "PARTIAL" in l for l in lines)

    def test_as_display_lines_shows_goal(self):
        report = CompletionReport(goal="Build a Trello clone")
        lines = report.as_display_lines()
        assert any("Trello" in l for l in lines)

    def test_as_display_lines_shows_summary(self):
        report = CompletionReport(
            goal="Build SaaS",
            summary="MARK completed the build successfully.",
        )
        lines = report.as_display_lines()
        assert any("MARK completed" in l for l in lines)

    def test_as_short_summary_success(self):
        report = CompletionReport(
            goal="Build SaaS",
            completed=[PhaseResult("Backend", success=True)],
            success=True,
            total_elapsed=30.0,
        )
        s = report.as_short_summary()
        assert "1 done" in s
        assert "30" in s

    def test_as_short_summary_failed(self):
        report = CompletionReport(
            goal="Build SaaS",
            completed=[PhaseResult("Backend", success=True)],
            failed=[PhaseResult("Tests", success=False)],
            remaining=["Docs"],
            success=False,
        )
        s = report.as_short_summary()
        assert "1 done" in s
        assert "1 failed" in s
        assert "1 remaining" in s


# ---------------------------------------------------------------------------
# _team_to_phase_name
# ---------------------------------------------------------------------------

class TestTeamToPhase:
    def test_engineering_maps_to_backend(self):
        assert _team_to_phase_name("engineering") == "Backend"

    def test_qa_maps_to_tests(self):
        assert _team_to_phase_name("qa") == "Tests"

    def test_documentation_maps_to_docs(self):
        assert _team_to_phase_name("documentation") == "Docs"

    def test_research_maps_to_research(self):
        assert _team_to_phase_name("research") == "Research"

    def test_unknown_team_title_cased(self):
        assert _team_to_phase_name("design") == "Frontend"

    def test_empty_string(self):
        result = _team_to_phase_name("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# LongRunningEngine — constructor and factory
# ---------------------------------------------------------------------------

class TestLongRunningEngineInit:
    def test_init_with_none_ceo(self):
        engine = LongRunningEngine(ceo_agent=None)
        assert engine is not None

    def test_with_agent_factory(self):
        agent = MagicMock()
        agent.ceo = MagicMock()
        agent.memory = MagicMock()
        engine = LongRunningEngine.with_agent(agent)
        assert engine is not None


# ---------------------------------------------------------------------------
# LongRunningEngine — run() behavior
# ---------------------------------------------------------------------------

def _make_team_result(team: str, state: str = "completed", summary: str = "done") -> MagicMock:
    tr = MagicMock()
    tr.team_name = team
    tr.state = state
    tr.summary = summary
    tr.elapsed = 1.0
    return tr


def _make_multi_result(*team_results) -> MagicMock:
    mr = MagicMock()
    mr.team_results = list(team_results)
    return mr


class TestLongRunningEngineRun:
    def test_run_returns_completion_report(self):
        engine = LongRunningEngine(ceo_agent=None)
        report = engine.run("Build SaaS")
        assert isinstance(report, CompletionReport)

    def test_run_with_no_ceo_returns_failed_report(self):
        engine = LongRunningEngine(ceo_agent=None)
        report = engine.run("Build SaaS")
        assert not report.success
        assert len(report.failed) == 1

    def test_run_calls_ceo_execute(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering"),
        )
        engine = LongRunningEngine(ceo_agent=ceo)
        engine.run("Build SaaS")
        ceo.execute.assert_called_once()
        assert "Build SaaS" in ceo.execute.call_args[0][0]

    def test_run_populates_completed_phases(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering", "completed"),
            _make_team_result("qa", "completed"),
        )
        engine = LongRunningEngine(ceo_agent=ceo)
        report = engine.run("Build SaaS")
        assert len(report.completed) == 2
        assert len(report.failed) == 0

    def test_run_populates_failed_phases(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering", "completed"),
            _make_team_result("qa", "failed"),
        )
        engine = LongRunningEngine(ceo_agent=ceo)
        report = engine.run("Build SaaS")
        assert len(report.completed) == 1
        assert len(report.failed) == 1

    def test_run_success_when_all_completed(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering", "completed"),
            _make_team_result("qa", "completed"),
        )
        engine = LongRunningEngine(ceo_agent=ceo)
        report = engine.run("Build SaaS")
        assert report.success is True

    def test_run_not_success_when_any_failed(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering", "completed"),
            _make_team_result("qa", "failed"),
        )
        engine = LongRunningEngine(ceo_agent=ceo)
        report = engine.run("Build SaaS")
        assert report.success is False

    def test_run_fires_callback_per_phase(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering", "completed"),
            _make_team_result("qa", "completed"),
        )
        engine = LongRunningEngine(ceo_agent=ceo)
        callbacks: list = []
        engine.run("Build SaaS", on_phase_done=lambda p, r: callbacks.append(p.name))
        assert len(callbacks) == 2

    def test_run_handles_ceo_exception(self):
        ceo = MagicMock()
        ceo.execute.side_effect = RuntimeError("CEO crashed")
        engine = LongRunningEngine(ceo_agent=ceo)
        report = engine.run("Build SaaS")
        assert isinstance(report, CompletionReport)
        assert not report.success
        assert len(report.failed) == 1

    def test_run_persists_summary_to_memory(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering", "completed"),
        )
        memory = MagicMock()
        engine = LongRunningEngine(ceo_agent=ceo, memory_manager=memory)
        engine.run("Build SaaS")
        memory.remember.assert_called_once()

    def test_run_total_elapsed_positive(self):
        ceo = MagicMock()
        ceo.execute.return_value = _make_multi_result(
            _make_team_result("engineering", "completed"),
        )
        engine = LongRunningEngine(ceo_agent=ceo)
        report = engine.run("Build SaaS")
        assert report.total_elapsed >= 0.0

    def test_run_enriches_goal_with_project_context(self):
        ceo = MagicMock()
        ceo.execute.return_value = MagicMock(team_results=[])
        pm = MagicMock()
        fake_profile = MagicMock()
        fake_profile.as_ai_context.return_value = "FastAPI / pytest"
        pm.load.return_value = fake_profile
        engine = LongRunningEngine(ceo_agent=ceo, project_memory=pm)
        engine.run("Build SaaS", project_name="my-api")
        # CEO should receive the enriched goal
        call_arg = ceo.execute.call_args[0][0]
        assert "FastAPI" in call_arg
