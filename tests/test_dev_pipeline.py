"""
Tests for smartagent.engineer.dev_pipeline — Planner→Executor→Tester→Reviewer→Fixer loop.

All tests mock the LLM and run against a temp workspace; no network calls.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from smartagent.engineer.dev_pipeline import (
    DevPipeline,
    PipelineResult,
    MilestoneResult,
    classify_intent,
    extract_file_targets,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_event_bus():
    bus = MagicMock()
    bus.publish = MagicMock()
    return bus


def make_model_manager(chat_stream_chunks=None, tool_calls=None):
    """
    Returns a mock ModelManager.
    chat_stream_chunks — iterable of strings for streaming calls (planner/reviewer).
    tool_calls         — list of mock tool_call objects for chat_with_tools().
    """
    mm = MagicMock()

    # chat_stream for planner and reviewer
    if chat_stream_chunks is None:
        chat_stream_chunks = ["PASS: milestone completed."]
    mm.chat_stream.return_value = iter(chat_stream_chunks)

    # chat_with_tools for agent_loop executor
    if tool_calls is None:
        msg = MagicMock()
        msg.tool_calls = []
        msg.content = "Done."
    else:
        msg = MagicMock()
        msg.tool_calls = tool_calls
        msg.content = ""
    mm.chat_with_tools.return_value = msg

    return mm


@pytest.fixture()
def ws(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    return str(tmp_path)


# ── classify_intent — engineering routing (complex_pipeline vs simple_agent) ──

class TestIsComplexGoal:
    """Same cases as the retired is_complex_goal(), now checking
    classify_intent(...).route instead of a bare bool."""

    def test_short_goal_never_complex(self):
        assert classify_intent("Create hello.py").route == "simple_agent"

    def test_create_file_not_complex(self):
        assert classify_intent("Write a Python script that sorts a list").route == "simple_agent"

    def test_full_stack_is_complex(self):
        assert classify_intent(
            "Build a full-stack TODO app with React frontend and Flask backend"
        ).route == "complex_pipeline"

    def test_project_keyword_is_complex(self):
        assert classify_intent(
            "Create a project with authentication, database models, and REST endpoints"
        ).route == "complex_pipeline"

    def test_with_tests_is_complex(self):
        assert classify_intent(
            "Build a Flask REST API for a blog system with tests and documentation"
        ).route == "complex_pipeline"

    def test_from_scratch_is_complex(self):
        assert classify_intent(
            "Build a microservice architecture from scratch with Docker and CI/CD"
        ).route == "complex_pipeline"

    def test_simple_command_not_complex(self):
        assert classify_intent("Run pytest and show me the output").route == "simple_agent"

    def test_empty_not_complex(self):
        assert classify_intent("").route == "conversational"


# ── DevPipeline initialisation ────────────────────────────────────────────────

class TestDevPipelineInit:
    def test_init_stores_params(self, ws):
        mm  = make_model_manager()
        eb  = make_event_bus()
        dp  = DevPipeline(mm, eb, ws, test_cmd="pytest", max_fix_attempts=2)
        assert dp._ws           == ws
        assert dp._test_cmd     == "pytest"
        assert dp._max_attempts == 2


# ── Planner ───────────────────────────────────────────────────────────────────

class TestPlanner:
    def test_plan_parses_numbered_list(self, ws):
        chunks = ["1. Create app.py\n2. Create tests\n3. Write README"]
        mm = make_model_manager(chat_stream_chunks=chunks)
        dp = DevPipeline(mm, make_event_bus(), ws)
        milestones = dp._plan("Build something")
        assert milestones == [
            "Create app.py",
            "Create tests",
            "Write README",
        ]

    def test_plan_parses_dash_list(self, ws):
        chunks = ["- First milestone\n- Second milestone"]
        mm = make_model_manager(chat_stream_chunks=chunks)
        dp = DevPipeline(mm, make_event_bus(), ws)
        milestones = dp._plan("Build something")
        assert milestones == ["First milestone", "Second milestone"]

    def test_plan_caps_at_5(self, ws):
        chunks = ["1. A\n2. B\n3. C\n4. D\n5. E\n6. F\n7. G"]
        mm = make_model_manager(chat_stream_chunks=chunks)
        dp = DevPipeline(mm, make_event_bus(), ws)
        milestones = dp._plan("Long goal")
        assert len(milestones) <= 5

    def test_plan_falls_back_on_llm_error(self, ws):
        mm = make_model_manager()
        mm.chat_stream.side_effect = RuntimeError("LLM down")
        dp = DevPipeline(mm, make_event_bus(), ws)
        milestones = dp._plan("Build something")
        assert milestones == ["Build something"]

    def test_plan_falls_back_on_empty_response(self, ws):
        mm = make_model_manager(chat_stream_chunks=[""])
        dp = DevPipeline(mm, make_event_bus(), ws)
        milestones = dp._plan("Build something")
        assert milestones == ["Build something"]


# ── Test detection ─────────────────────────────────────────────────────────────

class TestDetectTestCmd:
    def test_detects_pytest(self, tmp_path):
        (tmp_path / "test_app.py").write_text("def test_ok(): pass")
        mm = make_model_manager()
        dp = DevPipeline(mm, make_event_bus(), str(tmp_path))
        cmd = dp._detect_test_cmd()
        assert cmd and "pytest" in cmd

    def test_detects_npm(self, tmp_path):
        (tmp_path / "package.json").write_text('{"scripts":{"test":"jest"}}')
        dp = DevPipeline(make_model_manager(), make_event_bus(), str(tmp_path))
        cmd = dp._detect_test_cmd()
        assert cmd and "npm" in cmd

    def test_no_tests_returns_none(self, tmp_path):
        dp = DevPipeline(make_model_manager(), make_event_bus(), str(tmp_path))
        cmd = dp._detect_test_cmd()
        assert cmd is None


# ── Reviewer ──────────────────────────────────────────────────────────────────

class TestReviewer:
    def _loop_result(self, files=None, summary="done"):
        from smartagent.engineer.agent_loop import AgentLoopResult
        r = AgentLoopResult(goal="test milestone")
        r.files_created  = files or []
        r.final_summary  = summary
        r.success        = True
        return r

    def test_pass_review_returned(self, ws):
        mm = make_model_manager(chat_stream_chunks=["PASS: code looks correct."])
        dp = DevPipeline(mm, make_event_bus(), ws)
        lr = self._loop_result(files=["app.py"])
        review = dp._review("Create app.py", lr, "")
        assert review.startswith("PASS")

    def test_fail_review_returned(self, ws):
        mm = make_model_manager(chat_stream_chunks=["FAIL: missing error handling."])
        dp = DevPipeline(mm, make_event_bus(), ws)
        lr = self._loop_result(files=["app.py"])
        review = dp._review("Create app.py", lr, "FAILED test_app.py")
        assert review.startswith("FAIL")

    def test_no_files_auto_pass(self, ws):
        mm = make_model_manager()
        dp = DevPipeline(mm, make_event_bus(), ws)
        lr = self._loop_result(files=[])
        lr.success = True
        review = dp._review("Run git status", lr, "")
        # No files → auto-pass (conversational / query task)
        assert review.startswith("PASS")

    def test_reviewer_llm_error_returns_pass(self, ws):
        mm = make_model_manager()
        mm.chat_stream.side_effect = RuntimeError("LLM error")
        dp = DevPipeline(mm, make_event_bus(), ws)
        lr = self._loop_result(files=["x.py"])
        review = dp._review("Create x.py", lr, "")
        assert review.startswith("PASS")


# ── File-target extraction (permission scoping) ───────────────────────────────

class TestExtractFileTargets:
    def test_extracts_single_filename(self):
        assert extract_file_targets("Create app.py with a Flask app") == ["app.py"]

    def test_extracts_multiple_filenames(self):
        targets = extract_file_targets(
            "Create test_app.py with pytest tests and update requirements.txt"
        )
        assert targets == ["test_app.py", "requirements.txt"]

    def test_no_filenames_returns_empty(self):
        assert extract_file_targets("Refactor the authentication module") == []

    def test_dedupes_repeated_filenames(self):
        assert extract_file_targets("Update app.py, then re-check app.py") == ["app.py"]

    def test_extracts_nested_path(self):
        assert extract_file_targets("Add src/utils/helpers.py") == ["src/utils/helpers.py"]


# ── Swallowed-provider-error handling ──────────────────────────────────────────

class TestSwallowedProviderError:
    """
    GitHubProvider.chat_stream() deliberately yields a 'GitHub Models error: …'
    string instead of raising when the API call fails (rate limits, outages).
    Every chat_stream() consumer in DevPipeline must recognize that sentinel
    and fall back — otherwise a raw provider error streams to chat as if MARK
    had said it.
    """

    def test_plan_falls_back_on_swallowed_error(self, ws):
        mm = make_model_manager(chat_stream_chunks=["GitHub Models error: Too many requests."])
        dp = DevPipeline(mm, make_event_bus(), ws)
        assert dp._plan("Build something") == ["Build something"]

    def test_review_falls_back_on_swallowed_error(self, ws):
        mm = make_model_manager(chat_stream_chunks=["GitHub Models error: Too many requests."])
        dp = DevPipeline(mm, make_event_bus(), ws)
        from smartagent.engineer.agent_loop import AgentLoopResult
        lr = AgentLoopResult(goal="x")
        lr.files_created = ["app.py"]
        review = dp._review("Create app.py", lr, "")
        assert review == "PASS: (review skipped due to LLM error)"

    def test_synthesize_falls_back_on_swallowed_error(self, ws):
        mm = make_model_manager(chat_stream_chunks=["GitHub Models error: Too many requests."])
        dp = DevPipeline(mm, make_event_bus(), ws)
        text = dp._synthesize("some context", fallback="fallback text")
        assert text == "fallback text"


# ── Executive synthesis ────────────────────────────────────────────────────────

class TestExecutiveSynthesis:
    def test_synthesize_uses_llm_output(self, ws):
        mm = make_model_manager(chat_stream_chunks=["I had the team ship this cleanly."])
        dp = DevPipeline(mm, make_event_bus(), ws)
        text = dp._synthesize("some context", fallback="fallback text")
        assert text == "I had the team ship this cleanly."

    def test_synthesize_falls_back_on_llm_error(self, ws):
        mm = make_model_manager()
        mm.chat_stream.side_effect = RuntimeError("LLM down")
        dp = DevPipeline(mm, make_event_bus(), ws)
        text = dp._synthesize("some context", fallback="fallback text")
        assert text == "fallback text"

    def test_synthesize_falls_back_on_empty_response(self, ws):
        mm = make_model_manager(chat_stream_chunks=[""])
        dp = DevPipeline(mm, make_event_bus(), ws)
        text = dp._synthesize("some context", fallback="fallback text")
        assert text == "fallback text"

    def test_milestone_summary_never_raises(self, ws):
        mm = make_model_manager()
        mm.chat_stream.side_effect = RuntimeError("down")
        dp = DevPipeline(mm, make_event_bus(), ws)
        mr = MilestoneResult(milestone="Create app.py", success=True, attempts=1)
        text = dp._synthesize_milestone_summary(1, 1, mr)
        assert "app.py" in text or "1/1" in text

    def test_emits_reviewing_and_committing_reasoning_stages(self, ws):
        """Timeline's 8-stage stepper needs 'reviewing'/'committing' REASONING_STAGE
        events — DevPipeline didn't emit any REASONING_STAGE before this milestone."""
        done_msg = MagicMock()
        done_msg.tool_calls = []
        done_msg.content    = "Done."

        eb = make_event_bus()
        mm = MagicMock()
        mm.chat_stream.side_effect = [
            iter(["1. Create app.py"]),
            iter(["PASS: looks good."]),
            iter(["Shipped it."]),
            iter(["All done."]),
        ]
        mm.chat_with_tools.return_value = done_msg

        dp = DevPipeline(mm, eb, ws)
        dp.run("Create app.py")

        stages = [
            c.kwargs.get("stage") for c in eb.publish.call_args_list
            if c.args and c.args[0] == "ReasoningStage"
        ]
        assert "reviewing" in stages
        assert "committing" in stages

    def test_internal_phase_text_goes_to_activity_not_chat(self, ws):
        """Raw phase banners must publish ACTIVITY_FEED_ENTRY, not StreamingToken —
        chat only sees the one executive-composed message per milestone."""
        done_msg = MagicMock()
        done_msg.tool_calls = []
        done_msg.content    = "Done."

        eb = make_event_bus()
        mm = MagicMock()
        mm.chat_stream.side_effect = [
            iter(["1. Create app.py"]),          # planner
            iter(["PASS: looks good."]),          # reviewer
            iter(["CLEAR: no issues found."]),    # security
            iter(["SKIP: no doc update needed."]),# docs
            iter(["I shipped app.py cleanly."]),  # milestone synthesis
            iter(["All done — one file shipped."]),  # final synthesis
        ]
        mm.chat_with_tools.return_value = done_msg

        dp = DevPipeline(mm, eb, ws)
        dp.run("Create app.py")

        calls = eb.publish.call_args_list
        streamed_texts = [
            c.kwargs.get("text", "") for c in calls
            if c.args and c.args[0] == "StreamingToken"
        ]
        activity_texts = [
            c.kwargs.get("text", "") for c in calls
            if c.args and c.args[0] == "ActivityFeedEntry"
        ]
        # The raw internal banner text must NOT appear in chat.
        assert not any("Planning:" in t for t in streamed_texts)
        assert not any("Milestone 1/1" in t for t in streamed_texts)
        # But it must still be recorded for the Timeline/Activity Feed.
        assert any("Planning" in t for t in activity_texts)
        # And the executive-composed text is what reaches chat.
        assert any("shipped app.py cleanly" in t for t in streamed_texts)


# ── Preview self-inspection (M8) ────────────────────────────────────────────────

class TestInspectActivePreview:
    def test_no_active_preview_returns_empty(self, ws):
        dp = DevPipeline(make_model_manager(), make_event_bus(), ws)
        with patch("smartagent.preview.browser_agent.browser_agent") as mock_agent:
            mock_agent.available = True
            with patch("smartagent.server.api_previews.preview_manager") as mock_mgr:
                mock_mgr.all_previews.return_value = []
                note = dp._inspect_active_preview(1, 1)
        assert note == ""

    def test_unavailable_returns_empty(self, ws):
        dp = DevPipeline(make_model_manager(), make_event_bus(), ws)
        with patch("smartagent.preview.browser_agent.browser_agent") as mock_agent:
            mock_agent.available = False
            note = dp._inspect_active_preview(1, 1)
        assert note == ""

    def test_active_preview_inspected_and_recorded(self, ws):
        from smartagent.preview.browser_agent import InspectionReport

        dp = DevPipeline(make_model_manager(), make_event_bus(), ws)
        fake_report = InspectionReport(
            url="http://localhost:3000",
            screenshot_path="/tmp/x/shot.png",
            success=True,
        )
        with patch("smartagent.preview.browser_agent.browser_agent") as mock_agent:
            mock_agent.available = True
            mock_agent.inspect.return_value = fake_report
            with patch("smartagent.server.api_previews.preview_manager") as mock_mgr:
                mock_mgr.all_previews.return_value = [
                    {"status": "active", "url": "http://localhost:3000"},
                ]
                with patch("smartagent.server.api_timeline.record_event") as mock_record:
                    note = dp._inspect_active_preview(2, 3)

        mock_agent.inspect.assert_called_once_with("http://localhost:3000", check_accessibility=True)
        mock_record.assert_called_once()
        assert mock_record.call_args.args[0] == "MilestoneScreenshot"
        assert mock_record.call_args.args[1]["screenshot_url"] == "/screenshots/shot.png"
        assert "Inspected" in note

    def test_failed_inspection_returns_empty(self, ws):
        from smartagent.preview.browser_agent import InspectionReport

        dp = DevPipeline(make_model_manager(), make_event_bus(), ws)
        fake_report = InspectionReport(url="http://localhost:3000", success=False, error="timeout")
        with patch("smartagent.preview.browser_agent.browser_agent") as mock_agent:
            mock_agent.available = True
            mock_agent.inspect.return_value = fake_report
            with patch("smartagent.server.api_previews.preview_manager") as mock_mgr:
                mock_mgr.all_previews.return_value = [
                    {"status": "active", "url": "http://localhost:3000"},
                ]
                note = dp._inspect_active_preview(1, 1)
        assert note == ""


# ── Fixer goal builder ─────────────────────────────────────────────────────────

class TestFixerGoalBuilder:
    def test_includes_fail_reason(self):
        goal = DevPipeline._build_fix_goal(
            "Create app.py",
            "FAIL: missing import statement.",
            "ImportError: cannot import name 'foo'",
        )
        assert "missing import statement" in goal
        assert "ImportError" in goal

    def test_includes_milestone(self):
        goal = DevPipeline._build_fix_goal("Create app.py", "FAIL: x", "")
        assert "Create app.py" in goal


# ── Named worker dispatch ──────────────────────────────────────────────────────

class TestWorkerDispatch:
    """
    DevPipeline must dispatch real named workers (Engineer/QA/Reviewer/
    Security/Docs/Git) with actual WorkerStarted/WorkerFinished events —
    this is what drives the dashboard's Active Workers panel; before this,
    those events were never published by the live pipeline at all.
    """

    def _run_simple_pipeline(self, ws):
        write_tc = MagicMock()
        write_tc.id = "tc1"
        write_tc.function.name      = "write_file"
        write_tc.function.arguments = '{"path": "hello.py", "content": "print(1)\\n"}'

        done_msg = MagicMock()
        done_msg.tool_calls = []
        done_msg.content    = "Created hello.py."

        write_msg = MagicMock()
        write_msg.tool_calls = [write_tc]
        write_msg.content    = ""

        eb = make_event_bus()
        mm = MagicMock()
        mm.chat_stream.side_effect = [
            iter(["1. Create hello.py"]),            # planner
            iter(["PASS: file created correctly."]), # reviewer
            iter(["CLEAR: no issues."]),              # security
            iter(["SKIP: no docs needed."]),          # docs
            iter(["Shipped it."]),                    # milestone synthesis
            iter(["All done."]),                      # final synthesis
        ]
        mm.chat_with_tools.side_effect = [write_msg, done_msg]

        dp = DevPipeline(mm, eb, ws)
        dp.run("Build a hello world script")
        return eb

    def test_named_workers_fire_started_and_finished(self, ws):
        eb = self._run_simple_pipeline(ws)

        started = {
            c.kwargs.get("worker") for c in eb.publish.call_args_list
            if c.args and c.args[0] == "WorkerStarted"
        }
        finished = {
            c.kwargs.get("worker") for c in eb.publish.call_args_list
            if c.args and c.args[0] == "WorkerFinished"
        }
        expected = {"Engineer", "QA", "Reviewer", "Security", "Docs", "Git"}
        assert expected.issubset(started)
        assert expected.issubset(finished)
        # MARK itself is the executive, never a dispatched worker.
        assert "MARK" not in started

    def test_every_started_worker_also_finishes(self, ws):
        """A WorkerStarted with no matching WorkerFinished would leave a
        dashboard card stuck 'running' forever."""
        eb = self._run_simple_pipeline(ws)

        started = [
            c.kwargs.get("worker") for c in eb.publish.call_args_list
            if c.args and c.args[0] == "WorkerStarted"
        ]
        finished = [
            c.kwargs.get("worker") for c in eb.publish.call_args_list
            if c.args and c.args[0] == "WorkerFinished"
        ]
        assert sorted(started) == sorted(finished)

    def test_engineer_dispatch_suppresses_direct_reply(self, ws):
        """The Executor/Fixer phases must not let a worker's own text stream
        straight to chat — only MARK's executive-composed summaries should."""
        eb = self._run_simple_pipeline(ws)

        streamed_texts = [
            c.kwargs.get("text", "") for c in eb.publish.call_args_list
            if c.args and c.args[0] == "StreamingToken"
        ]
        # The Engineer's raw final reply ("Created hello.py.") must never
        # reach chat directly — only the executive-composed milestone/final
        # summaries (from the mocked "Shipped it."/"All done." responses).
        assert not any("Created hello.py." == t.strip() for t in streamed_texts)


# ── Full pipeline run (mocked LLM + real filesystem) ──────────────────────────

class TestPipelineRun:
    def test_single_milestone_pass(self, ws):
        """Pipeline writes a file and reviewer says PASS — result is successful."""
        # Prepare: chat_with_tools returns write_file tool call on first LLM call,
        # then empty (done) on second call
        write_tc = MagicMock()
        write_tc.id = "tc1"
        write_tc.function.name      = "write_file"
        write_tc.function.arguments = '{"path": "hello.py", "content": "print(1)\\n"}'

        done_msg = MagicMock()
        done_msg.tool_calls = []
        done_msg.content    = "Created hello.py."

        write_msg = MagicMock()
        write_msg.tool_calls = [write_tc]
        write_msg.content    = ""

        mm = MagicMock()
        # chat_stream: first call = planner ("1. Create hello.py"), second call = reviewer ("PASS: ...")
        mm.chat_stream.side_effect = [
            iter(["1. Create hello.py"]),
            iter(["PASS: file created correctly."]),
        ]
        # chat_with_tools: first call writes file, second call is final answer
        mm.chat_with_tools.side_effect = [write_msg, done_msg]

        dp     = DevPipeline(mm, make_event_bus(), ws)
        result = dp.run("Build a hello world script")

        assert isinstance(result, PipelineResult)
        assert result.success is True
        assert len(result.milestones) == 1
        assert len(result.milestone_results) == 1
        assert result.milestone_results[0].success is True
        assert Path(ws, "hello.py").exists()

    def test_no_milestones_fallback(self, ws):
        """When planner returns nothing, the original goal is used as one milestone."""
        done_msg = MagicMock()
        done_msg.tool_calls = []
        done_msg.content    = "Done."

        mm = MagicMock()
        mm.chat_stream.side_effect = [
            iter([""]),                         # planner → empty → fallback
            iter(["PASS: task completed."]),    # reviewer
        ]
        mm.chat_with_tools.return_value = done_msg

        dp     = DevPipeline(mm, make_event_bus(), ws)
        result = dp.run("Do something simple")

        assert result.milestones == ["Do something simple"]

    def test_pipeline_result_has_required_fields(self, ws):
        done_msg = MagicMock()
        done_msg.tool_calls = []
        done_msg.content    = "Done."

        mm = MagicMock()
        mm.chat_stream.side_effect = [
            iter(["1. Step one"]),
            iter(["PASS: done."]),
        ]
        mm.chat_with_tools.return_value = done_msg

        dp     = DevPipeline(mm, make_event_bus(), ws)
        result = dp.run("Simple goal with complex trigger words project test")

        assert result.goal          == "Simple goal with complex trigger words project test"
        assert result.total_elapsed >= 0
        assert isinstance(result.files_created,  list)
        assert isinstance(result.files_modified, list)
        assert result.final_summary != ""

    def test_event_bus_receives_tokens(self, ws):
        done_msg = MagicMock()
        done_msg.tool_calls = []
        done_msg.content    = "Done."

        eb = make_event_bus()
        mm = MagicMock()
        mm.chat_stream.side_effect = [
            iter(["1. Step one"]),
            iter(["PASS: done."]),
        ]
        mm.chat_with_tools.return_value = done_msg

        dp = DevPipeline(mm, eb, ws)
        dp.run("Simple project goal test run create")

        assert eb.publish.called, "event_bus.publish() was never called"
        calls = eb.publish.call_args_list
        # ServerEvents.STREAMING_TOKEN == "StreamingToken"
        streaming_calls = [c for c in calls if "StreamingToken" in str(c)]
        assert streaming_calls, "No STREAMING_TOKEN (StreamingToken) events emitted"
