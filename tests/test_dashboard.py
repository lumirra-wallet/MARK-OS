"""
Tests for ExecutionDashboard (Phase 6).
"""

import pytest
from smartagent.ui.dashboard import ExecutionDashboard, _elapsed, _trunc


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_start_sets_goal(self):
        dash = ExecutionDashboard()
        dash.start("Build a REST API")
        assert dash.state.goal == "Build a REST API"

    def test_start_resets_state(self):
        dash = ExecutionDashboard()
        dash.start("first")
        dash.add_completed("task1")
        dash.start("second")
        assert dash.state.completed == []
        assert dash.state.goal == "second"

    def test_complete_success(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.complete(True)
        assert dash.state.success is True
        assert dash.state.finished_at is not None

    def test_complete_failure(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.complete(False)
        assert dash.state.success is False

    def test_initial_state_none(self):
        dash = ExecutionDashboard()
        assert dash.state.success is None
        assert dash.state.started_at is None


# ---------------------------------------------------------------------------
# State mutators
# ---------------------------------------------------------------------------

class TestMutators:
    def test_set_current_worker(self):
        dash = ExecutionDashboard()
        dash.set("current_worker", "CodingWorker")
        assert dash.state.current_worker == "CodingWorker"

    def test_set_current_model(self):
        dash = ExecutionDashboard()
        dash.set("current_model", "llama3")
        assert dash.state.current_model == "llama3"

    def test_set_unknown_key_ignored(self):
        dash = ExecutionDashboard()
        dash.set("nonexistent_field", "value")  # must not raise

    def test_add_completed(self):
        dash = ExecutionDashboard()
        dash.add_completed("Planning")
        assert "Planning" in dash.state.completed

    def test_add_completed_no_duplicates(self):
        dash = ExecutionDashboard()
        dash.add_completed("A")
        dash.add_completed("A")
        assert dash.state.completed.count("A") == 1

    def test_add_completed_removes_from_running(self):
        dash = ExecutionDashboard()
        dash.add_running("Work")
        dash.add_completed("Work")
        assert "Work" not in dash.state.running
        assert "Work" in dash.state.completed

    def test_add_running(self):
        dash = ExecutionDashboard()
        dash.add_running("Testing")
        assert "Testing" in dash.state.running

    def test_add_queued(self):
        dash = ExecutionDashboard()
        dash.add_queued("Deploy")
        assert "Deploy" in dash.state.queued

    def test_add_running_removes_from_queued(self):
        dash = ExecutionDashboard()
        dash.add_queued("Step")
        dash.add_running("Step")
        assert "Step" not in dash.state.queued
        assert "Step" in dash.state.running

    def test_add_file(self):
        dash = ExecutionDashboard()
        dash.add_file("src/main.py")
        assert "src/main.py" in dash.state.files_modified

    def test_add_file_no_duplicates(self):
        dash = ExecutionDashboard()
        dash.add_file("f.py")
        dash.add_file("f.py")
        assert dash.state.files_modified.count("f.py") == 1

    def test_set_tests(self):
        dash = ExecutionDashboard()
        dash.set_tests(10, 2)
        assert dash.state.tests_passed == 10
        assert dash.state.tests_failed == 2

    def test_increment_retries(self):
        dash = ExecutionDashboard()
        dash.increment_retries()
        dash.increment_retries()
        assert dash.state.retries == 2

    def test_increment_tool_calls(self):
        dash = ExecutionDashboard()
        dash.increment_tool_calls(3)
        assert dash.state.tool_calls == 3

    def test_increment_memory(self):
        dash = ExecutionDashboard()
        dash.increment_memory()
        assert dash.state.memory_updates == 1

    def test_increment_knowledge(self):
        dash = ExecutionDashboard()
        dash.increment_knowledge()
        assert dash.state.knowledge_updates == 1

    def test_chaining(self):
        dash = ExecutionDashboard()
        # All mutators return self
        result = (
            dash.start("goal")
            .set("current_worker", "W")
            .add_completed("A")
            .add_file("f.py")
        )
        assert result is dash


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestRender:
    def test_render_returns_string(self):
        dash = ExecutionDashboard()
        dash.start("Test goal")
        output = dash.render()
        assert isinstance(output, str)
        assert len(output) > 0

    def test_render_contains_goal(self):
        dash = ExecutionDashboard()
        dash.start("Build a FastAPI app")
        output = dash.render()
        assert "Build a FastAPI app" in output

    def test_render_contains_running_status(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        output = dash.render()
        assert "RUNNING" in output

    def test_render_contains_complete_status(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.complete(True)
        output = dash.render()
        assert "COMPLETE" in output

    def test_render_contains_failed_status(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.complete(False)
        output = dash.render()
        assert "FAILED" in output

    def test_render_shows_files(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.add_file("auth.py")
        output = dash.render()
        assert "auth.py" in output

    def test_render_shows_tests(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.set_tests(15, 0)
        output = dash.render()
        assert "15" in output

    def test_render_shows_worker(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.set("current_worker", "CodingWorker")
        output = dash.render()
        assert "CodingWorker" in output

    def test_render_shows_model(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.set("current_model", "llama3")
        output = dash.render()
        assert "llama3" in output

    def test_render_shows_retries(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        dash.increment_retries()
        dash.increment_retries()
        output = dash.render()
        assert "2" in output

    def test_render_many_files_truncated(self):
        dash = ExecutionDashboard()
        dash.start("goal")
        for i in range(10):
            dash.add_file(f"file_{i}.py")
        output = dash.render()
        assert "more" in output.lower() or "…" in output

    def test_render_no_crash_empty_state(self):
        dash = ExecutionDashboard()
        output = dash.render()
        assert isinstance(output, str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_elapsed_none_started(self):
        result = _elapsed(None, None)
        assert result == "—"

    def test_elapsed_seconds(self):
        import time
        now = time.monotonic()
        result = _elapsed(now - 5.0, now)
        assert "s" in result

    def test_elapsed_minutes(self):
        import time
        now = time.monotonic()
        result = _elapsed(now - 125.0, now)
        assert "m" in result

    def test_trunc_short(self):
        assert _trunc("hello", 20) == "hello"

    def test_trunc_long(self):
        result = _trunc("a" * 50, 10)
        assert len(result) == 10
        assert result.endswith("…")
