"""
Tests for QualityRunner (Phase 5 — Code Quality).
"""

import pytest
from unittest.mock import MagicMock, patch

from smartagent.quality.quality_runner import (
    QualityResult,
    QualityReport,
    QualityRunner,
    _looks_like_not_found,
)


# ---------------------------------------------------------------------------
# QualityResult
# ---------------------------------------------------------------------------

class TestQualityResult:
    def test_icon_passed(self):
        r = QualityResult(tool="pytest", passed=True)
        assert r.icon == "✓"

    def test_icon_failed(self):
        r = QualityResult(tool="pytest", passed=False)
        assert r.icon == "✗"

    def test_icon_skipped(self):
        r = QualityResult(tool="ruff", passed=False, skipped=True)
        assert r.icon == "–"

    def test_one_line_pass(self):
        r = QualityResult(tool="pytest", passed=True, elapsed=1.2)
        line = r.one_line()
        assert "PASS" in line
        assert "pytest" in line

    def test_one_line_fail(self):
        r = QualityResult(tool="ruff", passed=False, elapsed=0.5)
        line = r.one_line()
        assert "FAIL" in line

    def test_one_line_skipped(self):
        r = QualityResult(tool="mypy", passed=False, skipped=True, elapsed=0.1)
        line = r.one_line()
        assert "skipped" in line


# ---------------------------------------------------------------------------
# QualityReport
# ---------------------------------------------------------------------------

class TestQualityReport:
    def test_all_passed_true(self):
        results = [
            QualityResult(tool="pytest", passed=True),
            QualityResult(tool="ruff",   passed=True),
        ]
        report = QualityReport(results=results, all_passed=True)
        assert report.all_passed

    def test_all_passed_false(self):
        results = [
            QualityResult(tool="pytest", passed=True),
            QualityResult(tool="ruff",   passed=False),
        ]
        report = QualityReport(results=results, all_passed=False)
        assert not report.all_passed

    def test_failing_tools(self):
        results = [
            QualityResult(tool="pytest", passed=True),
            QualityResult(tool="ruff",   passed=False),
            QualityResult(tool="mypy",   passed=False),
        ]
        report = QualityReport(results=results, all_passed=False)
        failing = report.failing_tools()
        assert "ruff" in failing
        assert "mypy" in failing
        assert "pytest" not in failing

    def test_failing_tools_skips_skipped(self):
        results = [
            QualityResult(tool="black", passed=False, skipped=True),
        ]
        report = QualityReport(results=results, all_passed=False)
        assert report.failing_tools() == []

    def test_get_existing(self):
        r = QualityResult(tool="pytest", passed=True)
        report = QualityReport(results=[r])
        assert report.get("pytest") is r

    def test_get_missing(self):
        report = QualityReport(results=[])
        assert report.get("ruff") is None

    def test_as_display_lines_pass(self):
        report = QualityReport(
            results=[QualityResult(tool="pytest", passed=True, elapsed=1.0)],
            all_passed=True,
            total_elapsed=1.0,
        )
        lines = report.as_display_lines()
        assert any("ALL PASSED" in l for l in lines)

    def test_as_display_lines_fail(self):
        report = QualityReport(
            results=[QualityResult(tool="ruff", passed=False, output="E501 line too long", elapsed=0.2)],
            all_passed=False,
            total_elapsed=0.2,
        )
        lines = report.as_display_lines()
        assert any("ISSUES" in l for l in lines)

    def test_as_display_lines_includes_tool_output_on_fail(self):
        report = QualityReport(
            results=[
                QualityResult(tool="ruff", passed=False, output="error: E501", elapsed=0.1)
            ],
            all_passed=False,
        )
        lines = report.as_display_lines()
        combined = "\n".join(lines)
        assert "error: E501" in combined


# ---------------------------------------------------------------------------
# QualityRunner — unit tests with subprocess mocked
# ---------------------------------------------------------------------------

def _make_proc(returncode: int, stdout: str = "", stderr: str = ""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestQualityRunner:
    def test_init_defaults(self):
        runner = QualityRunner()
        assert runner._path == "."

    def test_init_custom(self, tmp_path):
        runner = QualityRunner(cwd=str(tmp_path), path="src/")
        assert runner._path == "src/"

    @patch("subprocess.run")
    def test_run_pytest_pass(self, mock_run):
        mock_run.return_value = _make_proc(0, stdout="5 passed")
        runner = QualityRunner()
        result = runner.run_pytest()
        assert result.tool == "pytest"
        assert result.passed
        assert not result.skipped

    @patch("subprocess.run")
    def test_run_pytest_fail(self, mock_run):
        mock_run.return_value = _make_proc(1, stdout="2 failed")
        runner = QualityRunner()
        result = runner.run_pytest()
        assert not result.passed
        assert not result.skipped

    @patch("subprocess.run")
    def test_run_ruff_pass(self, mock_run):
        mock_run.return_value = _make_proc(0)
        runner = QualityRunner()
        result = runner.run_ruff()
        assert result.tool == "ruff"
        assert result.passed

    @patch("subprocess.run")
    def test_run_black_check_mode(self, mock_run):
        mock_run.return_value = _make_proc(0)
        runner = QualityRunner()
        result = runner.run_black(check=True)
        assert result.tool == "black"
        # Verify --check flag was in the command
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "--check" in cmd

    @patch("subprocess.run")
    def test_run_mypy_pass(self, mock_run):
        mock_run.return_value = _make_proc(0)
        runner = QualityRunner()
        result = runner.run_mypy()
        assert result.tool == "mypy"
        assert result.passed

    @patch("subprocess.run")
    def test_tool_not_found_marked_skipped(self, mock_run):
        mock_run.return_value = _make_proc(127, stderr="command not found")
        runner = QualityRunner()
        result = runner.run_ruff()
        assert result.skipped

    @patch("subprocess.run")
    def test_run_all_returns_report(self, mock_run):
        mock_run.return_value = _make_proc(0)
        runner = QualityRunner()
        report = runner.run_all(tools=["pytest", "ruff"])
        assert isinstance(report, QualityReport)
        assert len(report.results) == 2

    @patch("subprocess.run")
    def test_run_all_all_passed(self, mock_run):
        mock_run.return_value = _make_proc(0)
        runner = QualityRunner()
        report = runner.run_all(tools=["pytest", "ruff"])
        assert report.all_passed

    @patch("subprocess.run")
    def test_run_all_partial_failure(self, mock_run):
        responses = [_make_proc(0), _make_proc(1, stderr="lint error")]
        mock_run.side_effect = responses
        runner = QualityRunner()
        report = runner.run_all(tools=["pytest", "ruff"])
        assert not report.all_passed
        assert "ruff" in report.failing_tools()

    @patch("subprocess.run")
    def test_run_all_custom_tools(self, mock_run):
        mock_run.return_value = _make_proc(0)
        runner = QualityRunner()
        report = runner.run_all(tools=["pytest"])
        assert len(report.results) == 1
        assert report.results[0].tool == "pytest"

    @patch("subprocess.run")
    def test_timeout_handled(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=300)
        runner = QualityRunner()
        result = runner.run_pytest()
        assert not result.passed
        assert "timeout" in result.output.lower()

    @patch("subprocess.run")
    def test_oserror_handled(self, mock_run):
        mock_run.side_effect = OSError("no such file")
        runner = QualityRunner()
        result = runner.run_pytest()
        assert result.skipped

    @patch("subprocess.run")
    def test_unknown_tool_in_run_all(self, mock_run):
        runner = QualityRunner()
        report = runner.run_all(tools=["nonexistent_tool"])
        assert len(report.results) == 1
        assert report.results[0].skipped

    def test_elapsed_tracked(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(0)
            runner = QualityRunner()
            result = runner.run_pytest()
            assert result.elapsed >= 0.0

    def test_total_elapsed_in_report(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_proc(0)
            runner = QualityRunner()
            report = runner.run_all(tools=["pytest"])
            assert report.total_elapsed >= 0.0


# ---------------------------------------------------------------------------
# _looks_like_not_found
# ---------------------------------------------------------------------------

class TestLooksLikeNotFound:
    def test_command_not_found(self):
        assert _looks_like_not_found("bash: ruff: command not found")

    def test_no_such_file(self):
        assert _looks_like_not_found("No such file or directory")

    def test_is_not_recognized(self):
        assert _looks_like_not_found("'ruff' is not recognized as an internal or external command")

    def test_normal_output(self):
        assert not _looks_like_not_found("5 passed, 0 failed")

    def test_empty(self):
        assert not _looks_like_not_found("")
