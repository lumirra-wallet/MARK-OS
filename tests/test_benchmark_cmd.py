"""Tests for smartagent.ui.commands.benchmark_cmd — v2.0 Phase 7."""

import pytest
from unittest.mock import MagicMock

from smartagent.ui.commands.benchmark_cmd import (
    BenchmarkScenario,
    _find_scenario,
    _run_scenario,
    _format_result,
    handle_benchmark,
    register,
    _SCENARIOS,
)
from smartagent.ui.command_router import CommandRouter


def _agent():
    return MagicMock()


class TestScenarios:
    def test_four_scenarios_defined(self):
        assert len(_SCENARIOS) == 4

    def test_scenario_names(self):
        names = {s.name for s in _SCENARIOS}
        assert "hello-world" in names
        assert "calculator" in names
        assert "rest-api" in names
        assert "bug-fix" in names

    def test_find_existing(self):
        s = _find_scenario("hello-world")
        assert s is not None
        assert s.name == "hello-world"

    def test_find_missing_returns_none(self):
        assert _find_scenario("nonexistent") is None

    def test_scenario_has_goal(self):
        for s in _SCENARIOS:
            assert s.goal
            assert len(s.goal) > 5


class TestRunScenario:
    def test_returns_dict(self):
        s = _SCENARIOS[0]
        r = _run_scenario(s, _agent())
        assert isinstance(r, dict)

    def test_result_has_name(self):
        r = _run_scenario(_SCENARIOS[0], _agent())
        assert r["name"] == _SCENARIOS[0].name

    def test_result_has_complexity(self):
        r = _run_scenario(_SCENARIOS[0], _agent())
        assert "complexity" in r
        assert r["complexity"] is not None

    def test_result_has_task_count(self):
        r = _run_scenario(_SCENARIOS[0], _agent())
        assert r["task_count"] is not None
        assert r["task_count"] >= 1

    def test_result_has_timing(self):
        r = _run_scenario(_SCENARIOS[0], _agent())
        assert r["total_ms"] >= 0
        assert r["planning_ms"] >= 0
        assert r["complexity_ms"] >= 0

    def test_hello_world_trivial(self):
        s = _find_scenario("hello-world")
        r = _run_scenario(s, _agent())
        assert r["complexity"] in ("trivial", "small")

    def test_hello_world_two_tasks(self):
        s = _find_scenario("hello-world")
        r = _run_scenario(s, _agent())
        assert r["task_count"] == 2

    def test_calculator_trivial(self):
        s = _find_scenario("calculator")
        r = _run_scenario(s, _agent())
        assert r["complexity"] in ("trivial", "small")


class TestFormatResult:
    def _result(self):
        return {
            "name": "hello-world",
            "goal": "Create hello.py",
            "complexity": "trivial",
            "task_count": 2,
            "task_names": ["Implementation", "Testing"],
            "complexity_ms": 0.1,
            "planning_ms": 1.0,
            "total_ms": 1.1,
            "error": None,
        }

    def test_returns_list(self):
        lines = _format_result(self._result())
        assert isinstance(lines, list)
        assert len(lines) >= 3

    def test_contains_name(self):
        text = "\n".join(_format_result(self._result()))
        assert "hello-world" in text

    def test_contains_complexity(self):
        text = "\n".join(_format_result(self._result()))
        assert "trivial" in text

    def test_pass_icon(self):
        text = "\n".join(_format_result(self._result()))
        assert "✓" in text

    def test_error_icon(self):
        r = self._result()
        r["error"] = "something failed"
        text = "\n".join(_format_result(r))
        assert "✗" in text


class TestHandleBenchmark:
    def test_list_command(self):
        result = handle_benchmark(["list"], _agent())
        assert "hello-world" in result
        assert "calculator" in result

    def test_run_single(self):
        result = handle_benchmark(["hello-world"], _agent())
        assert "hello-world" in result

    def test_run_unknown(self):
        result = handle_benchmark(["unknown-scenario"], _agent())
        assert "Unknown" in result or "unknown" in result.lower()

    def test_run_all(self):
        result = handle_benchmark([], _agent())
        assert "hello-world" in result
        assert "calculator" in result

    def test_returns_string(self):
        result = handle_benchmark([], _agent())
        assert isinstance(result, str)


class TestRegister:
    def test_registers_benchmark(self):
        router = CommandRouter()
        register(router)
        assert router.has_command("benchmark")
