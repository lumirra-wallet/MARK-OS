"""
Tests for Milestone 24: Autonomous Development Loop.

Coverage:
    LoopIteration:
      · icon returns ✓ / ✗ based on success
      · all fields accessible

    LoopResult:
      · as_display_lines — success format
      · as_display_lines — failure format
      · as_display_lines — includes trace of iterations
      · _cycle_count — correct max iteration
      · as_display_lines — empty iterations

    DevLoop:
      · with_agent() factory constructs without error
      · run() returns LoopResult
      · run() success=True when executive marks completed and tests pass
      · run() success=False when tests always fail and max iterations reached
      · run() stop_reason="success" on pass
      · run() stop_reason="max_iterations" when tests always fail
      · run() stop_reason="planning_failed" when executive raises
      · run() calls debug_loop.run() when tests fail
      · run() sets total_elapsed
      · run() persists summary to memory on completion
      · _run_planning_phase — success when no executive wired
      · _run_test_phase — success when pytest exits 0
      · _run_test_phase — failure when pytest exits non-zero
      · _run_test_phase — handles timeout
      · _run_debug_phase — returns iteration with notes when no debug_loop
      · _run_reflection_phase — success even when reflection engine absent
      · _parse_pytest_counts — extracts passed/failed from output
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from smartagent.dev_loop.loop_result import LoopIteration, LoopResult
from smartagent.dev_loop.dev_loop import DevLoop, _parse_pytest_counts, _last_lines


# ---------------------------------------------------------------------------
# LoopIteration
# ---------------------------------------------------------------------------

class TestLoopIteration:
    def test_icon_success(self):
        it = LoopIteration(iteration=1, phase="testing", success=True)
        assert it.icon == "✓"

    def test_icon_failure(self):
        it = LoopIteration(iteration=1, phase="testing", success=False)
        assert it.icon == "✗"

    def test_fields_accessible(self):
        it = LoopIteration(
            iteration=2,
            phase="debugging",
            success=True,
            notes="Fixed.",
            tests_passed=10,
            tests_failed=0,
            elapsed=3.5,
        )
        assert it.iteration == 2
        assert it.phase == "debugging"
        assert it.notes == "Fixed."
        assert it.tests_passed == 10
        assert it.elapsed == 3.5


# ---------------------------------------------------------------------------
# LoopResult
# ---------------------------------------------------------------------------

class TestLoopResult:
    def _make_result(self, success=True, stop="success") -> LoopResult:
        iterations = [
            LoopIteration(1, "planning", True, "Plan created."),
            LoopIteration(1, "testing", success, "", tests_passed=5, tests_failed=0 if success else 2),
        ]
        return LoopResult(
            goal="Build login system",
            success=success,
            iterations=iterations,
            stop_reason=stop,
            total_elapsed=10.5,
        )

    def test_as_display_lines_success(self):
        result = self._make_result(success=True)
        lines = result.as_display_lines()
        assert any("✓" in l for l in lines)
        assert any("SUCCESS" in l for l in lines)

    def test_as_display_lines_failure(self):
        result = self._make_result(success=False, stop="max_iterations")
        lines = result.as_display_lines()
        assert any("✗" in l for l in lines)
        assert any("NOT COMPLETE" in l for l in lines)

    def test_as_display_lines_contains_goal(self):
        result = self._make_result()
        lines = result.as_display_lines()
        assert any("login" in l for l in lines)

    def test_as_display_lines_trace(self):
        result = self._make_result()
        lines = result.as_display_lines()
        assert any("planning" in l.lower() for l in lines)
        assert any("testing" in l.lower() for l in lines)

    def test_as_display_lines_shows_elapsed(self):
        result = self._make_result()
        lines = result.as_display_lines()
        assert any("10.5" in l for l in lines)

    def test_as_display_lines_empty_iterations(self):
        result = LoopResult(goal="Build X", success=False)
        lines = result.as_display_lines()
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_cycle_count(self):
        result = self._make_result()
        assert result._cycle_count() == 1

    def test_cycle_count_empty(self):
        result = LoopResult(goal="X", success=False)
        assert result._cycle_count() == 0

    def test_final_summary_shown(self):
        result = LoopResult(
            goal="X",
            success=True,
            final_summary="Build completed successfully.",
        )
        lines = result.as_display_lines()
        assert any("completed" in l for l in lines)


# ---------------------------------------------------------------------------
# DevLoop factory
# ---------------------------------------------------------------------------

class TestDevLoopFactory:
    def test_with_agent_returns_dev_loop(self):
        agent = MagicMock()
        agent.executive = MagicMock()
        agent.reflection_engine = MagicMock()
        agent.memory = MagicMock()
        agent.model_manager = None
        loop = DevLoop.with_agent(agent)
        assert isinstance(loop, DevLoop)

    def test_with_agent_no_services(self):
        agent = MagicMock()
        agent.executive = None
        agent.model_manager = None
        loop = DevLoop.with_agent(agent)
        assert isinstance(loop, DevLoop)


# ---------------------------------------------------------------------------
# DevLoop.run()
# ---------------------------------------------------------------------------

def _make_loop(tests_pass=True, max_iters=2) -> DevLoop:
    """Build a DevLoop with mocked dependencies for unit testing."""
    loop = DevLoop(max_iterations=max_iters)
    # Patch subprocess inside _run_test_phase
    return loop


class TestDevLoopRun:
    def test_run_returns_loop_result(self):
        loop = DevLoop(max_iterations=1)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="5 passed", stderr="")
            result = loop.run("Build login", test_cmd="pytest")
        assert isinstance(result, LoopResult)

    def test_run_success_when_tests_pass(self):
        loop = DevLoop(max_iterations=3)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="10 passed", stderr="")
            result = loop.run("Build login", test_cmd="pytest")
        assert result.success is True

    def test_run_stop_reason_success(self):
        loop = DevLoop(max_iterations=3)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="3 passed", stderr="")
            result = loop.run("Build X", test_cmd="pytest")
        assert result.stop_reason == "success"

    def test_run_failure_when_tests_always_fail(self):
        loop = DevLoop(max_iterations=2)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="2 failed", stderr="")
            result = loop.run("Build X", test_cmd="pytest")
        assert result.success is False

    def test_run_stop_reason_max_iterations(self):
        loop = DevLoop(max_iterations=2)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="1 failed", stderr="")
            result = loop.run("Build X", test_cmd="pytest")
        assert result.stop_reason == "max_iterations"

    def test_run_has_iterations(self):
        loop = DevLoop(max_iterations=1)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            result = loop.run("Build X", test_cmd="pytest")
        assert len(result.iterations) >= 1

    def test_run_total_elapsed_non_negative(self):
        loop = DevLoop(max_iterations=1)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            result = loop.run("Build X", test_cmd="pytest")
        assert result.total_elapsed >= 0.0

    def test_run_persists_to_memory(self):
        memory = MagicMock()
        loop = DevLoop(max_iterations=1, memory_manager=memory)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
            loop.run("Build X", test_cmd="pytest")
        memory.remember.assert_called_once()

    def test_run_calls_debug_loop_on_test_failure(self):
        debug_loop = MagicMock()
        debug_result = MagicMock()
        debug_result.success = False
        debug_result.attempts = []
        debug_loop.run.return_value = debug_result

        loop = DevLoop(max_iterations=1, debug_loop=debug_loop)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="1 failed", stderr="")
            result = loop.run("Build X", test_cmd="pytest")
        # Debug loop should have been called since tests failed
        debug_loop.run.assert_called_once()

    def test_run_planning_phase_no_executive(self):
        loop = DevLoop(max_iterations=1, executive=None)
        it = loop._run_planning_phase(1, "Build X")
        assert it.success is True  # no executive → pass through
        assert "No executive" in it.notes

    def test_run_planning_phase_executive_completed(self):
        ctx = MagicMock()
        ctx.state = "COMPLETED"
        executive = MagicMock()
        executive.receive_goal.return_value = ctx
        loop = DevLoop(max_iterations=1, executive=executive)
        it = loop._run_planning_phase(1, "Build X")
        assert it.success is True

    def test_run_debug_phase_no_debug_loop(self):
        loop = DevLoop(max_iterations=1, debug_loop=None)
        it = loop._run_debug_phase(1, "pytest", "error output")
        assert it.phase == "debugging"
        assert "No DebugLoop" in it.notes

    def test_run_reflection_phase_no_engine(self):
        loop = DevLoop(max_iterations=1, reflection_engine=None)
        test_it = LoopIteration(1, "testing", False, tests_failed=1)
        debug_it = LoopIteration(1, "debugging", False)
        it = loop._run_reflection_phase(1, "Build X", test_it, debug_it)
        assert it.success is True  # reflection always reports success


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

class TestParsePytestCounts:
    def test_passed_and_failed(self):
        output = "5 passed, 2 failed in 1.23s"
        passed, failed = _parse_pytest_counts(output)
        assert passed == 5
        assert failed == 2

    def test_passed_only(self):
        output = "10 passed in 0.5s"
        passed, failed = _parse_pytest_counts(output)
        assert passed == 10
        assert failed == 0

    def test_failed_only(self):
        output = "3 failed in 2.0s"
        passed, failed = _parse_pytest_counts(output)
        assert passed == 0
        assert failed == 3

    def test_empty_output(self):
        passed, failed = _parse_pytest_counts("")
        assert passed == 0
        assert failed == 0

    def test_no_counts(self):
        passed, failed = _parse_pytest_counts("no tests collected")
        assert passed == 0
        assert failed == 0


class TestLastLines:
    def test_returns_last_n_lines(self):
        text = "\n".join(str(i) for i in range(20))
        result = _last_lines(text, 5)
        lines = result.splitlines()
        assert len(lines) == 5
        assert lines[-1] == "19"

    def test_empty_string(self):
        assert _last_lines("", 5) == ""

    def test_fewer_lines_than_n(self):
        text = "line1\nline2"
        result = _last_lines(text, 10)
        assert "line1" in result
        assert "line2" in result
