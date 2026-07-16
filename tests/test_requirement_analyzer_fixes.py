"""
Tests for v2.0 RequirementAnalyzer domain classification fixes.

Verifies that CLI / script / utility goals are correctly classified as
backend, not frontend, and that other classifications remain accurate.
"""

import pytest
from smartagent.engineer.requirement_analyzer import RequirementAnalyzer


@pytest.fixture
def analyzer():
    return RequirementAnalyzer()


class TestCLIGoalsAreBackend:
    """Phase 6: CLI/script/calculator goals must never classify as frontend."""

    def test_calculator_cli(self, analyzer):
        report = analyzer.analyze("Build a calculator CLI")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_calculator_program(self, analyzer):
        report = analyzer.analyze("Write a calculator program")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_simple_calculator(self, analyzer):
        report = analyzer.analyze("Write a simple calculator")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_cli_tool(self, analyzer):
        report = analyzer.analyze("Build a CLI tool for file management")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_command_line(self, analyzer):
        report = analyzer.analyze("Create a command-line utility for batch processing")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_script(self, analyzer):
        report = analyzer.analyze("Write a Python script to process CSV files")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_utility(self, analyzer):
        report = analyzer.analyze("Build a utility to convert JSON to CSV")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_hello_world(self, analyzer):
        report = analyzer.analyze("Create hello.py that prints Hello World")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_function(self, analyzer):
        report = analyzer.analyze("Add a function to calculate compound interest")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_library(self, analyzer):
        report = analyzer.analyze("Build a Python library for data validation")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_parser(self, analyzer):
        report = analyzer.analyze("Write a Markdown parser")
        assert "backend" in report.domains
        assert "frontend" not in report.domains

    def test_algorithm(self, analyzer):
        report = analyzer.analyze("Implement a binary search algorithm")
        assert "backend" in report.domains
        assert "frontend" not in report.domains


class TestFrontendGoalsStillWork:
    """Frontend goals with unambiguous browser/UI keywords still classify correctly."""

    def test_react_app(self, analyzer):
        report = analyzer.analyze("Build a React dashboard for analytics")
        assert "frontend" in report.domains

    def test_html_css(self, analyzer):
        report = analyzer.analyze("Create an HTML and CSS landing page")
        assert "frontend" in report.domains

    def test_vue_app(self, analyzer):
        report = analyzer.analyze("Build a Vue.js component library")
        assert "frontend" in report.domains

    def test_tailwind(self, analyzer):
        report = analyzer.analyze("Style a website with Tailwind CSS")
        assert "frontend" in report.domains


class TestBackendGoalsCorrect:
    """Backend goals are correctly classified."""

    def test_rest_api(self, analyzer):
        report = analyzer.analyze("Build a REST API with FastAPI")
        assert "backend" in report.domains

    def test_flask_app(self, analyzer):
        report = analyzer.analyze("Create a Flask web app with routes")
        assert "backend" in report.domains

    def test_server(self, analyzer):
        report = analyzer.analyze("Build a server to handle HTTP requests")
        assert "backend" in report.domains


class TestDefaultDomain:
    """When no keywords match, backend is the default."""

    def test_unknown_goal_defaults_to_backend(self, analyzer):
        report = analyzer.analyze("xyz abc foo bar")
        assert "backend" in report.domains


class TestReportFields:
    """RequirementReport fields are always populated."""

    def test_goal_preserved(self, analyzer):
        goal = "Build a calculator CLI"
        report = analyzer.analyze(goal)
        assert report.goal == goal

    def test_complexity_present(self, analyzer):
        report = analyzer.analyze("Build a REST API")
        assert report.complexity in ("small", "medium", "large", "xlarge")

    def test_teams_not_empty(self, analyzer):
        report = analyzer.analyze("Build a service")
        assert len(report.teams) >= 1

    def test_as_display_lines_non_empty(self, analyzer):
        report = analyzer.analyze("Build a calculator")
        lines = report.as_display_lines()
        assert len(lines) >= 2

    def test_as_ai_context_non_empty(self, analyzer):
        report = analyzer.analyze("Build a calculator")
        ctx = report.as_ai_context()
        assert len(ctx) > 10
