"""
Tests for the validate command (Phase 9 — Validation).
"""

import pytest
from unittest.mock import MagicMock, patch

from smartagent.ui.commands.validate_cmd import (
    handle_validate,
    _list_scenarios,
    _find_scenario,
    _execute_scenario,
    Scenario,
    _SCENARIOS,
)


def _make_agent():
    agent = MagicMock()
    agent.software_engineer = None
    agent.model_manager = None
    agent.executive = None
    agent.memory = None
    return agent


class TestScenarios:
    def test_scenarios_exist(self):
        assert len(_SCENARIOS) == 5

    def test_scenario_names(self):
        names = [s.name for s in _SCENARIOS]
        assert "calculator-cli" in names
        assert "rest-api" in names
        assert "flask-blog" in names
        assert "markdown-parser" in names
        assert "jwt-auth" in names

    def test_all_have_goals(self):
        for s in _SCENARIOS:
            assert s.goal

    def test_find_exact(self):
        s = _find_scenario("rest-api")
        assert s is not None
        assert s.name == "rest-api"

    def test_find_prefix(self):
        s = _find_scenario("calc")
        assert s is not None
        assert s.name == "calculator-cli"

    def test_find_missing(self):
        assert _find_scenario("nonexistent") is None


class TestListScenarios:
    def test_returns_string(self):
        result = _list_scenarios()
        assert isinstance(result, str)

    def test_contains_all_names(self):
        result = _list_scenarios()
        for s in _SCENARIOS:
            assert s.name in result


class TestHandleValidate:
    def test_help(self):
        agent = _make_agent()
        result = handle_validate(agent, [])
        assert "validate" in result.lower()

    def test_help_explicit(self):
        agent = _make_agent()
        result = handle_validate(agent, ["help"])
        assert "scenario" in result.lower()

    def test_list(self):
        agent = _make_agent()
        result = handle_validate(agent, ["list"])
        assert "calculator" in result

    def test_run_missing_name(self):
        agent = _make_agent()
        result = handle_validate(agent, ["run"])
        assert "usage" in result.lower() or "Usage" in result

    def test_run_unknown_name(self):
        agent = _make_agent()
        result = handle_validate(agent, ["run", "unknown-scenario"])
        assert "error" in result.lower() or "Unknown" in result


class TestExecuteScenario:
    def test_no_engineer_creates_one(self):
        # When agent.software_engineer is None, _execute_scenario creates one.
        # Patch at the definition site of SoftwareEngineer.
        agent = _make_agent()
        scenario = Scenario(name="test", goal="Build a test")
        mock_report = MagicMock()
        mock_report.success = True
        mock_report.summary = "Done"
        mock_eng = MagicMock()
        mock_eng.build.return_value = mock_report
        with patch(
            "smartagent.engineer.software_engineer.SoftwareEngineer.with_agent",
            return_value=mock_eng,
        ):
            ok, detail = _execute_scenario(agent, scenario)
        assert ok is True

    def test_uses_agent_engineer_if_present(self):
        agent = _make_agent()
        mock_report = MagicMock()
        mock_report.success = True
        mock_report.summary = "Built"
        mock_eng = MagicMock()
        mock_eng.build.return_value = mock_report
        agent.software_engineer = mock_eng

        scenario = Scenario(name="test", goal="Build X")
        ok, detail = _execute_scenario(agent, scenario)
        assert ok is True
        mock_eng.build.assert_called_once()

    def test_exception_returns_failure(self):
        agent = _make_agent()
        scenario = Scenario(name="test", goal="Build X")

        with patch(
            "smartagent.engineer.software_engineer.SoftwareEngineer.with_agent",
            side_effect=RuntimeError("boom"),
        ):
            ok, detail = _execute_scenario(agent, scenario)

        assert ok is False
        assert "boom" in detail or "error" in detail.lower()

    def test_failed_report(self):
        agent = _make_agent()
        mock_report = MagicMock()
        mock_report.success = False
        mock_report.summary = ""
        mock_eng = MagicMock()
        mock_eng.build.return_value = mock_report
        agent.software_engineer = mock_eng

        scenario = Scenario(name="test", goal="Build X")
        ok, detail = _execute_scenario(agent, scenario)
        assert ok is False


class TestRegister:
    def test_registers_validate_command(self):
        from smartagent.ui.command_router import CommandRouter
        from smartagent.ui.commands.validate_cmd import register
        router = CommandRouter()
        register(router)
        agent = _make_agent()
        result = router.dispatch(agent, "validate help")
        assert isinstance(result, str)
