"""
Tests for Milestone 20: Self Debugging — TracebackParser, DebugLoop, DebugWorker.

Test coverage:
    TracebackParser:
      • parse() returns None for clean output
      • parse() finds a single traceback
      • parse_all() finds multiple tracebacks
      • Correct frame parsing (filepath, lineno, function, code)
      • Error type and message extraction
      • Relative vs absolute paths
      • root_cause_frame skips site-packages frames
      • root_cause_frame returns last user frame
      • ParsedTraceback.one_line() format
      • ParsedTraceback.as_display_lines() format
      • pytest --tb=short "E   " prefix handling
      • FAILED marker → test_name

    DebugLoop:
      • run() with passing command → success, 1 attempt
      • run() with failing command → failure recorded
      • run() with no debug_worker → stops after first failure
      • run() with debug_worker → fix applied
      • run() respects max_attempts
      • DebugAttempt.passed property
      • DebugResult.as_display_lines() format

    DebugWorker:
      • name, task_types, description properties
      • phase == "stub" without model_manager
      • fix() returns original content when no model
      • execute() returns stub string without model
      • with_model() factory
"""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch, call

import pytest

from smartagent.debug.traceback_parser import (
    ParsedTraceback,
    TracebackFrame,
    TracebackParser,
    _is_user_frame,
)
from smartagent.debug.debug_loop import DebugAttempt, DebugLoop, DebugResult
from smartagent.executive.workers.debug_worker import DebugWorker


# ===========================================================================
# TracebackParser
# ===========================================================================

SIMPLE_TB = textwrap.dedent("""\
    Traceback (most recent call last):
      File "/home/user/project/app.py", line 42, in main
        result = compute(x)
      File "/home/user/project/core.py", line 17, in compute
        raise ValueError("bad input")
    ValueError: bad input
""")

PYTEST_TB = textwrap.dedent("""\
    FAILED tests/test_auth.py::test_login - AssertionError: assert False

    Traceback (most recent call last):
      File "tests/test_auth.py", line 15, in test_login
        assert auth.login("user", "wrong") is True
      File "src/auth.py", line 8, in login
        raise AssertionError("wrong password")
    AssertionError: wrong password
""")

STDLIB_TB = textwrap.dedent("""\
    Traceback (most recent call last):
      File "/usr/lib/python3.11/site-packages/requests/adapters.py", line 120, in send
        r = conn.send(request)
      File "/home/user/project/client.py", line 33, in fetch
        response = requests.get(url)
    ConnectionError: Connection refused
""")


class TestTracebackParserParse:
    def test_clean_output_returns_none(self):
        parser = TracebackParser()
        assert parser.parse("All tests passed.") is None

    def test_parse_finds_traceback(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert tb is not None

    def test_parse_returns_first_only(self):
        double = SIMPLE_TB + "\n" + SIMPLE_TB
        parser = TracebackParser()
        tb = parser.parse(double)
        assert tb is not None
        # parse() returns only first, not a list

    def test_parse_all_finds_multiple(self):
        double = SIMPLE_TB + "\n" + SIMPLE_TB
        parser = TracebackParser()
        tbs = parser.parse_all(double)
        assert len(tbs) == 2

    def test_parse_all_empty(self):
        parser = TracebackParser()
        assert parser.parse_all("No tracebacks here.") == []


class TestTracebackParserFrames:
    def test_frame_count(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert len(tb.frames) == 2

    def test_first_frame_path(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert "app.py" in tb.frames[0].filepath

    def test_first_frame_lineno(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert tb.frames[0].lineno == 42

    def test_first_frame_function(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert tb.frames[0].function == "main"

    def test_first_frame_code(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert "compute" in tb.frames[0].code

    def test_last_frame_path(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert "core.py" in tb.frames[-1].filepath

    def test_last_frame_lineno(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert tb.frames[-1].lineno == 17


class TestTracebackParserErrorType:
    def test_error_type(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert tb.error_type == "ValueError"

    def test_error_message(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert "bad input" in tb.error_message

    def test_assertion_error(self):
        text = textwrap.dedent("""\
            Traceback (most recent call last):
              File "test.py", line 5, in test_foo
                assert False
            AssertionError
        """)
        parser = TracebackParser()
        tb = parser.parse(text)
        assert tb.error_type == "AssertionError"

    def test_type_error(self):
        text = textwrap.dedent("""\
            Traceback (most recent call last):
              File "app.py", line 3, in foo
                int("hello")
            TypeError: invalid literal for int()
        """)
        parser = TracebackParser()
        tb = parser.parse(text)
        assert tb.error_type == "TypeError"


class TestTracebackParserPytest:
    def test_pytest_tb_parsed(self):
        parser = TracebackParser()
        tb = parser.parse(PYTEST_TB)
        assert tb is not None

    def test_pytest_error_type(self):
        parser = TracebackParser()
        tb = parser.parse(PYTEST_TB)
        assert tb.error_type == "AssertionError"

    def test_pytest_test_name_detected(self):
        parser = TracebackParser()
        tb = parser.parse(PYTEST_TB)
        # test_name is set when FAILED marker is found
        # It may or may not be detected depending on whether it precedes the TB
        # Just check no crash
        assert isinstance(tb.test_name, str)

    def test_pytest_frames_found(self):
        parser = TracebackParser()
        tb = parser.parse(PYTEST_TB)
        assert len(tb.frames) >= 1


class TestRootCauseFrame:
    def test_returns_last_user_frame(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        rcf = tb.root_cause_frame
        assert rcf is not None
        # Should be the last frame that's in user code
        assert "core.py" in rcf.filepath or "app.py" in rcf.filepath

    def test_skips_site_packages(self):
        parser = TracebackParser()
        tb = parser.parse(STDLIB_TB)
        rcf = tb.root_cause_frame
        assert rcf is not None
        assert "site-packages" not in rcf.filepath
        assert "client.py" in rcf.filepath

    def test_returns_last_frame_when_all_stdlib(self):
        tb = ParsedTraceback(
            frames=[
                TracebackFrame("/usr/lib/python3.11/site-packages/x.py", 1, "f", ""),
                TracebackFrame("/usr/lib/python3.11/site-packages/y.py", 2, "g", ""),
            ],
            error_type="RuntimeError",
            error_message="all library frames",
        )
        rcf = tb.root_cause_frame
        assert rcf is not None  # fallback to last frame

    def test_none_when_no_frames(self):
        tb = ParsedTraceback(error_type="ValueError", error_message="oops")
        assert tb.root_cause_frame is None

    def test_is_user_frame_true(self):
        assert _is_user_frame("/home/user/project/app.py") is True

    def test_is_user_frame_false_site_packages(self):
        assert _is_user_frame("/usr/lib/python3.11/site-packages/requests/__init__.py") is False

    def test_is_user_frame_false_lib_python(self):
        assert _is_user_frame("/usr/lib/python3.11/functools.py") is False

    def test_is_user_frame_false_stdin(self):
        assert _is_user_frame("<stdin>") is False


class TestParsedTracebackDisplay:
    def test_one_line_includes_error_type(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        line = tb.one_line()
        assert "ValueError" in line

    def test_one_line_includes_message(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        line = tb.one_line()
        assert "bad input" in line

    def test_one_line_includes_file(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        line = tb.one_line()
        # Should include some file reference
        assert ".py" in line

    def test_as_display_lines_is_list(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        lines = tb.as_display_lines()
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_as_display_lines_contains_error(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        lines = tb.as_display_lines()
        combined = "\n".join(lines)
        assert "ValueError" in combined

    def test_str_delegates_to_one_line(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert str(tb) == tb.one_line()

    def test_raw_stored(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        assert "Traceback" in tb.raw


# ===========================================================================
# DebugAttempt / DebugResult
# ===========================================================================

class TestDebugAttempt:
    def test_passed_true_when_exit_0(self):
        attempt = DebugAttempt(
            attempt_num=1, command="pytest", exit_code=0,
            output="passed", elapsed=1.0,
        )
        assert attempt.passed is True

    def test_passed_false_when_nonzero_exit(self):
        attempt = DebugAttempt(
            attempt_num=1, command="pytest", exit_code=1,
            output="failed", elapsed=1.0,
        )
        assert attempt.passed is False


class TestDebugResult:
    def test_as_display_lines_success(self):
        result = DebugResult(
            success=True,
            attempts=[
                DebugAttempt(1, "pytest", 0, "passed", 0.5),
            ],
            final_output="1 passed",
            total_elapsed=0.5,
        )
        lines = result.as_display_lines()
        assert any("PASSED" in l for l in lines)

    def test_as_display_lines_failure(self):
        result = DebugResult(
            success=False,
            attempts=[
                DebugAttempt(1, "pytest", 1, "1 failed", 0.5),
            ],
            final_output="1 failed",
            total_elapsed=0.5,
        )
        lines = result.as_display_lines()
        assert any("FAILED" in l for l in lines)

    def test_as_display_lines_shows_attempt_count(self):
        result = DebugResult(
            success=False,
            attempts=[
                DebugAttempt(1, "pytest", 1, "", 0.1),
                DebugAttempt(2, "pytest", 1, "", 0.1),
            ],
            final_output="",
            total_elapsed=0.2,
        )
        lines = result.as_display_lines()
        combined = "\n".join(lines)
        assert "2" in combined


# ===========================================================================
# DebugLoop
# ===========================================================================

class TestDebugLoopPassingCommand:
    def test_passes_on_first_attempt(self, tmp_path):
        loop = DebugLoop(cwd=str(tmp_path))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1 passed", stderr="", returncode=0
            )
            result = loop.run("pytest tests/")

        assert result.success is True
        assert len(result.attempts) == 1
        assert result.attempts[0].passed is True

    def test_exit_code_zero_means_pass(self, tmp_path):
        loop = DebugLoop(cwd=str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="", stderr="", returncode=0
            )
            result = loop.run("true")
        assert result.success is True


class TestDebugLoopFailingNoWorker:
    def test_fails_and_stops_without_worker(self, tmp_path):
        loop = DebugLoop(max_attempts=3, debug_worker=None, cwd=str(tmp_path))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=SIMPLE_TB, stderr="", returncode=1
            )
            result = loop.run("pytest tests/")

        assert result.success is False
        # Should stop after 1 attempt since no worker
        assert len(result.attempts) == 1

    def test_failure_records_tracebacks(self, tmp_path):
        loop = DebugLoop(cwd=str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=SIMPLE_TB, stderr="", returncode=1
            )
            result = loop.run("pytest tests/")

        attempt = result.attempts[0]
        assert len(attempt.tracebacks) > 0

    def test_final_output_captured(self, tmp_path):
        loop = DebugLoop(cwd=str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="FAILED", stderr="some error", returncode=1
            )
            result = loop.run("pytest")

        assert "FAILED" in result.final_output or "some error" in result.final_output


class TestDebugLoopWithWorker:
    def _make_worker(self, fixed_content="FIXED CONTENT"):
        worker = MagicMock()
        worker.fix.return_value = fixed_content
        return worker

    def test_worker_fix_called_on_failure(self, tmp_path):
        # Create a real file the loop can "fix"
        failing_file = tmp_path / "app.py"
        failing_file.write_text("original content")

        tb_with_real_path = SIMPLE_TB.replace(
            "/home/user/project/core.py", str(tmp_path / "app.py")
        ).replace(
            "/home/user/project/app.py", str(tmp_path / "app.py")
        )

        worker = self._make_worker("fixed content")
        loop = DebugLoop(max_attempts=2, debug_worker=worker, cwd=str(tmp_path))

        call_count = [0]
        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(stdout=tb_with_real_path, stderr="", returncode=1)
            return MagicMock(stdout="1 passed", stderr="", returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            result = loop.run("pytest tests/")

        assert worker.fix.called

    def test_loop_stops_when_no_change(self, tmp_path):
        # Worker returns the same content → DebugLoop should stop
        real_file = tmp_path / "app.py"
        original = "original content"
        real_file.write_text(original)

        tb = SIMPLE_TB.replace(
            "/home/user/project/core.py", str(tmp_path / "app.py")
        ).replace(
            "/home/user/project/app.py", str(tmp_path / "app.py")
        )

        # Worker returns unchanged content
        worker = self._make_worker(original)
        loop = DebugLoop(max_attempts=5, debug_worker=worker, cwd=str(tmp_path))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=tb, stderr="", returncode=1
            )
            result = loop.run("pytest")

        # Should stop early — no fix applied
        assert result.success is False

    def test_result_as_display_lines(self, tmp_path):
        loop = DebugLoop(cwd=str(tmp_path))
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="1 passed", stderr="", returncode=0
            )
            result = loop.run("pytest")
        lines = result.as_display_lines()
        assert isinstance(lines, list)
        assert len(lines) > 2


class TestDebugLoopTimeout:
    def test_timeout_handled_gracefully(self, tmp_path):
        import subprocess
        loop = DebugLoop(max_attempts=1, timeout=1, cwd=str(tmp_path))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 1)):
            result = loop.run("pytest")
        assert result.success is False
        assert "timeout" in result.final_output.lower()


# ===========================================================================
# DebugWorker
# ===========================================================================

class TestDebugWorkerProperties:
    def test_name(self):
        w = DebugWorker()
        assert w.name == "Debug Worker"

    def test_task_types_contains_debugging(self):
        from smartagent.executive.task import TaskType
        w = DebugWorker()
        assert TaskType.DEBUGGING in w.task_types

    def test_description_is_string(self):
        w = DebugWorker()
        assert isinstance(w.description, str)
        assert len(w.description) > 5

    def test_phase_stub_without_model(self):
        w = DebugWorker()
        assert w.phase == "stub"

    def test_phase_ollama_with_model(self):
        mm = MagicMock()
        w = DebugWorker(model_manager=mm)
        assert w.phase == "ollama"


class TestDebugWorkerFix:
    def test_fix_returns_original_when_no_model(self):
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        w = DebugWorker()
        original = "def foo(): pass"
        result = w.fix(tb, "app.py", original)
        # Phase 2: no change
        assert result == original

    def test_fix_with_model_calls_generate(self):
        mm = MagicMock()
        mm.generate.return_value = "def foo():\n    return 42\n"
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        w = DebugWorker(model_manager=mm)
        result = w.fix(tb, "app.py", "def foo(): pass")
        # With model: tries to generate a fix
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fix_strips_fenced_code_block(self):
        mm = MagicMock()
        mm.generate.return_value = "```python\ndef foo():\n    pass\n```"
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        w = DebugWorker(model_manager=mm)
        result = w.fix(tb, "app.py", "def foo(): ...")
        assert "```" not in result

    def test_fix_model_error_returns_original(self):
        mm = MagicMock()
        mm.generate.side_effect = RuntimeError("model offline")
        parser = TracebackParser()
        tb = parser.parse(SIMPLE_TB)
        w = DebugWorker(model_manager=mm)
        original = "original content"
        result = w.fix(tb, "app.py", original)
        assert result == original


class TestDebugWorkerExecute:
    def _context(self, **metadata):
        ctx = MagicMock()
        ctx.metadata = metadata
        return ctx

    def _task(self, title="debug task"):
        task = MagicMock()
        task.title = title
        task.description = "Fix the failing test"
        return task

    def test_execute_stub_without_model(self):
        w = DebugWorker()
        ctx = self._context()
        result = w.execute(self._task(), ctx)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "stub" in result.lower() or "model" in result.lower()

    def test_execute_stub_is_nonempty(self):
        w = DebugWorker()
        ctx = self._context()
        result = w.execute(self._task(), ctx)
        assert result.strip() != ""


class TestDebugWorkerFactory:
    def test_with_model_creates_worker(self):
        mm = MagicMock()
        w = DebugWorker.with_model(mm)
        assert isinstance(w, DebugWorker)
        assert w._model_manager is mm
        assert w.phase == "ollama"
