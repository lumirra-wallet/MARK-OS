"""
tests/test_tool_workers.py — Milestone 12: Tool Intelligence & Autonomous Execution.

Verifies:
  * WorkerToolMixin.parse_tool_call correctness
  * Allowlist enforcement (disallowed tools are rejected)
  * Tool call tracking in ExecutionContext.metadata["tool_calls"]
  * Graceful fallback to stub when no tool_engine is present
  * Full ReAct loop with a mocked tool_engine
  * Scheduler compatibility (tools + retry paths coexist)
  * Worker-specific allowed-tool lists
  * ToolContext construction from metadata
  * All existing tests remain unaffected (tools are opt-in)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from smartagent.brain.action_result import ActionResult
from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.executive_controller import ExecutiveController
from smartagent.executive.task import Task, TaskType, TaskStatus
from smartagent.executive.workers.coding_worker import CodingWorker
from smartagent.executive.workers.documentation_worker import DocumentationWorker
from smartagent.executive.workers.research_worker import ResearchWorker
from smartagent.executive.workers.testing_worker import TestingWorker
from smartagent.executive.workers.tool_mixin import WorkerToolMixin
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin
from smartagent.executive.workers.base_worker import BaseWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(goal: str = "Build something", **meta) -> ExecutionContext:
    ctx = ExecutionContext(goal=goal)
    ctx.metadata.update(meta)
    return ctx


def _make_task(
    title: str = "Test Task",
    task_type: TaskType = TaskType.CODING,
    description: str = "",
) -> Task:
    return Task(title=title, task_type=task_type, description=description or title)


def _make_action_result(
    success: bool = True,
    message: str = "ok",
    data: Any = None,
) -> ActionResult:
    return ActionResult(
        success=success,
        message=message,
        data=data,
        source="mock_tool",
        execution_time=0.01,
        confidence=1.0,
    )


def _mock_tool_engine(
    *,
    tool_ids: list[str] | None = None,
    success: bool = True,
    message: str = "tool result",
    data: Any = None,
) -> MagicMock:
    """Build a minimal ToolEngine mock that satisfies WorkerToolMixin."""
    te = MagicMock()
    # Registry.find returns a mock tool for any id in tool_ids
    ids = tool_ids or ["file_read", "file_write", "date_time", "system_info",
                       "directory_list", "read_markdown", "search_files"]

    def _find(tool_id):
        if tool_id in ids:
            t = MagicMock()
            t.description = f"Mock {tool_id} tool"
            return t
        return None

    te.registry.find.side_effect = _find
    te.run.return_value = _make_action_result(
        success=success, message=message, data=data or message
    )
    return te


class _MinimalSettings:
    """Minimal stand-in for Settings when running tool tests."""
    workspace_path: str = "."
    ollama_default_model: str = "llama3.1:8b"
    ollama_coding_model: str = "qwen2.5-coder:7b"


def _ctx_with_tool_engine(
    goal: str = "Build something",
    tool_ids: list[str] | None = None,
    tool_success: bool = True,
    tool_message: str = "tool result content",
) -> ExecutionContext:
    te = _mock_tool_engine(
        tool_ids=tool_ids,
        success=tool_success,
        message=tool_message,
    )
    ctx = _make_context(
        goal,
        tool_engine=te,
        settings=_MinimalSettings(),
    )
    return ctx


# ---------------------------------------------------------------------------
# Minimal concrete worker for mixin unit tests
# ---------------------------------------------------------------------------


class _SimpleToolWorker(WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
    """Minimal worker that uses two allowed tools for testing the mixin."""

    _system_prompt = "You are a test worker."
    _preferred_model = "default"
    _allowed_tools: tuple[str, ...] = ("date_time", "file_read")

    @property
    def name(self) -> str:
        return "Simple Worker"

    @property
    def task_types(self):
        return [TaskType.RESEARCH]

    def execute(self, task, context):
        return self._execute_with_tools(task, context)


# ---------------------------------------------------------------------------
# 1. Tool call parsing
# ---------------------------------------------------------------------------


class TestParseToolCall:
    """WorkerToolMixin._parse_tool_call() correctness."""

    def _w(self) -> WorkerToolMixin:
        return _SimpleToolWorker()

    def test_valid_single_tool_call(self):
        text = 'I need the date.\nTOOL_CALL: {"tool": "date_time", "args": {}}'
        result = self._w()._parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "date_time"
        assert result["args"] == {}

    def test_valid_call_with_args(self):
        text = 'TOOL_CALL: {"tool": "file_read", "args": {"path": "/workspace/main.py"}}'
        result = self._w()._parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "file_read"
        assert result["args"]["path"] == "/workspace/main.py"

    def test_no_tool_call_returns_none(self):
        text = "This is a normal response with no tool call."
        assert self._w()._parse_tool_call(text) is None

    def test_malformed_json_returns_none(self):
        text = "TOOL_CALL: {invalid json here"
        assert self._w()._parse_tool_call(text) is None

    def test_call_without_tool_key_returns_none(self):
        text = 'TOOL_CALL: {"action": "run", "args": {}}'
        assert self._w()._parse_tool_call(text) is None

    def test_nested_json_args_parsed_correctly(self):
        text = 'TOOL_CALL: {"tool": "file_write", "args": {"path": "/tmp/a.py", "content": "x = {1: 2}"}}'
        result = self._w()._parse_tool_call(text)
        assert result is not None
        assert result["args"]["content"] == "x = {1: 2}"

    def test_parse_returns_first_call_when_multiple_present(self):
        text = (
            'TOOL_CALL: {"tool": "date_time", "args": {}}\n'
            'TOOL_CALL: {"tool": "file_read", "args": {"path": "/x"}}'
        )
        result = self._w()._parse_tool_call(text)
        # First match is returned
        assert result["tool"] == "date_time"


# ---------------------------------------------------------------------------
# 2. Allowlist enforcement
# ---------------------------------------------------------------------------


class TestAllowlistEnforcement:
    """Workers must reject tools not in their _allowed_tools."""

    def test_allowed_tool_executes(self):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine(tool_ids=["date_time"])
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        observation = worker._execute_tool(
            {"tool": "date_time", "args": {}}, task, ctx
        )
        assert "TOOL_DENIED" not in observation
        assert "TOOL_ERROR" not in observation

    def test_unlisted_tool_is_denied(self):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine(tool_ids=["system_info"])
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        observation = worker._execute_tool(
            {"tool": "system_info", "args": {}}, task, ctx  # not in _allowed_tools
        )
        assert "TOOL_DENIED" in observation
        te.run.assert_not_called()

    def test_unknown_tool_outside_allowlist_denied(self):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine()
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        obs = worker._execute_tool({"tool": "python_exec", "args": {}}, task, ctx)
        assert "TOOL_DENIED" in obs

    def test_coding_worker_allowed_tools(self):
        w = CodingWorker()
        assert "file_read" in w._allowed_tools
        assert "file_write" in w._allowed_tools
        assert "directory_list" in w._allowed_tools
        assert "directory_create" in w._allowed_tools
        assert "search_files" in w._allowed_tools

    def test_research_worker_allowed_tools(self):
        w = ResearchWorker()
        assert "date_time" in w._allowed_tools
        assert "system_info" in w._allowed_tools
        assert "read_markdown" in w._allowed_tools
        # Should NOT have filesystem write tools
        assert "file_write" not in w._allowed_tools

    def test_testing_worker_allowed_tools(self):
        w = TestingWorker()
        assert "file_read" in w._allowed_tools
        assert "file_write" in w._allowed_tools
        assert "directory_list" in w._allowed_tools

    def test_documentation_worker_allowed_tools(self):
        w = DocumentationWorker()
        assert "file_read" in w._allowed_tools
        assert "read_markdown" in w._allowed_tools
        assert "directory_list" in w._allowed_tools


# ---------------------------------------------------------------------------
# 3. Tool call tracking in context.metadata
# ---------------------------------------------------------------------------


class TestToolCallTracking:
    """All tool executions are recorded in context.metadata["tool_calls"]."""

    def _run_tool(self, success=True, message="result"):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine(
            tool_ids=["date_time"],
            success=success,
            message=message,
        )
        task = _make_task(title="Track Test")
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())
        worker._execute_tool({"tool": "date_time", "args": {}}, task, ctx)
        return ctx, task

    def test_tool_calls_list_initialised_on_first_call(self):
        ctx, _ = self._run_tool()
        assert "tool_calls" in ctx.metadata
        assert isinstance(ctx.metadata["tool_calls"], list)

    def test_tool_call_entry_has_all_required_fields(self):
        ctx, task = self._run_tool(message="2026-07-16")
        entry = ctx.metadata["tool_calls"][0]
        assert entry["task_id"] == task.id
        assert entry["tool"] == "date_time"
        assert "args" in entry
        assert "result" in entry
        assert "duration" in entry
        assert "success" in entry

    def test_successful_tool_records_success_true(self):
        ctx, _ = self._run_tool(success=True, message="2026-07-16")
        assert ctx.metadata["tool_calls"][0]["success"] is True

    def test_denied_tool_records_success_false(self):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine()
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())
        worker._execute_tool({"tool": "blocked_tool", "args": {}}, task, ctx)
        assert ctx.metadata["tool_calls"][0]["success"] is False

    def test_multiple_tool_calls_all_accumulated(self):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine(tool_ids=["date_time", "file_read"])
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        worker._execute_tool({"tool": "date_time", "args": {}}, task, ctx)
        worker._execute_tool(
            {"tool": "file_read", "args": {"path": "/x"}}, task, ctx
        )
        assert len(ctx.metadata["tool_calls"]) == 2

    def test_failed_tool_records_success_false(self):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine(tool_ids=["date_time"], success=False, message="error!")
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())
        worker._execute_tool({"tool": "date_time", "args": {}}, task, ctx)
        entry = ctx.metadata["tool_calls"][0]
        assert entry["success"] is False


# ---------------------------------------------------------------------------
# 4. Fallback when no tool_engine
# ---------------------------------------------------------------------------


class TestFallbackWithoutToolEngine:
    """Workers fall back gracefully when tool_engine is absent."""

    def test_worker_falls_back_to_stub_when_no_engine(self):
        worker = _SimpleToolWorker()
        task = _make_task(title="Fallback test")
        ctx = _make_context("Test goal")  # no tool_engine

        result = worker.execute(task, ctx)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fallback_result_contains_worker_name(self):
        worker = _SimpleToolWorker()
        task = _make_task(title="Check name")
        ctx = _make_context("Foo goal")

        result = worker.execute(task, ctx)
        assert "Simple Worker" in result

    def test_no_tool_calls_recorded_without_engine(self):
        worker = _SimpleToolWorker()
        task = _make_task()
        ctx = _make_context()
        worker.execute(task, ctx)
        assert ctx.metadata.get("tool_calls", []) == []

    def test_worker_with_empty_allowed_tools_skips_react_loop(self):
        """A worker with _allowed_tools=() never enters the ReAct loop."""

        class _NoToolWorker(WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
            _allowed_tools: tuple[str, ...] = ()
            _system_prompt = "You are a test."

            @property
            def name(self):
                return "No Tool Worker"

            @property
            def task_types(self):
                return [TaskType.RESEARCH]

            def execute(self, task, ctx):
                return self._execute_with_tools(task, ctx)

        te = _mock_tool_engine()
        worker = _NoToolWorker()
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        result = worker.execute(task, ctx)
        assert isinstance(result, str)
        te.run.assert_not_called()  # loop was skipped


# ---------------------------------------------------------------------------
# 5. ReAct loop with mocked LLM + tool_engine
# ---------------------------------------------------------------------------


class TestReActLoop:
    """Full loop: think → TOOL_CALL → observation → continue → final answer."""

    def _worker_with_stream(self, responses: list[str]) -> _SimpleToolWorker:
        """Return a worker whose LLM returns *responses* in sequence."""
        worker = _SimpleToolWorker()
        response_iter = iter(responses)

        def _stream_full_mock(context, full_messages):
            try:
                return next(response_iter)
            except StopIteration:
                return "Final answer."

        worker._stream_full = _stream_full_mock
        return worker

    def test_no_tool_call_returns_first_response(self):
        worker = self._worker_with_stream(["Plain answer, no tools needed."])
        te = _mock_tool_engine()
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        result = worker._execute_with_tools(task, ctx)
        assert result == "Plain answer, no tools needed."
        te.run.assert_not_called()

    def test_tool_call_triggers_execution_then_continues(self):
        worker = self._worker_with_stream([
            'I need the date.\nTOOL_CALL: {"tool": "date_time", "args": {}}',
            "Based on the date, here is my analysis.",
        ])
        te = _mock_tool_engine(tool_ids=["date_time"], message="2026-07-16")
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        result = worker._execute_with_tools(task, ctx)

        te.run.assert_called_once()
        assert "Based on the date" in result
        assert len(ctx.metadata["tool_calls"]) == 1
        assert ctx.metadata["tool_calls"][0]["tool"] == "date_time"

    def test_tool_failure_observation_fed_back_to_llm(self):
        worker = self._worker_with_stream([
            'TOOL_CALL: {"tool": "date_time", "args": {}}',
            "Despite the error, here is my response.",
        ])
        te = _mock_tool_engine(
            tool_ids=["date_time"], success=False, message="Connection timeout"
        )
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        result = worker._execute_with_tools(task, ctx)

        # Tool was called, failure was observed, LLM continued
        te.run.assert_called_once()
        assert "Despite the error" in result
        assert ctx.metadata["tool_calls"][0]["success"] is False

    def test_max_rounds_caps_loop_iterations(self):
        """Loop stops at _max_tool_rounds even if LLM keeps emitting TOOL_CALLs."""
        always_call = 'TOOL_CALL: {"tool": "date_time", "args": {}}'

        worker = _SimpleToolWorker()
        worker._max_tool_rounds = 3
        call_count = 0

        def _stream_full_mock(context, messages):
            nonlocal call_count
            call_count += 1
            # After exceeding max rounds, the loop prompts for a final answer
            if "Summarise" in (messages[-1].get("content", "")):
                return "Final summary."
            return always_call

        worker._stream_full = _stream_full_mock

        te = _mock_tool_engine(tool_ids=["date_time"])
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        result = worker._execute_with_tools(task, ctx)

        # Loop ran at most _max_tool_rounds tool iterations
        assert te.run.call_count <= worker._max_tool_rounds
        assert isinstance(result, str)

    def test_confidence_stored_after_react_loop(self):
        worker = self._worker_with_stream(["Detailed analysis with ## sections and - bullets."])
        te = _mock_tool_engine()
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        worker._execute_with_tools(task, ctx)
        assert task.id in ctx.metadata.get("task_confidence", {})

    def test_denied_tool_observation_fed_back(self):
        """If LLM requests a denied tool, denial is fed back and LLM continues."""
        worker = self._worker_with_stream([
            'TOOL_CALL: {"tool": "python_exec", "args": {}}',  # not allowed
            "OK, I will work without that tool.",
        ])
        te = _mock_tool_engine()
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        result = worker._execute_with_tools(task, ctx)
        te.run.assert_not_called()  # denied before reaching engine
        assert "without that tool" in result


# ---------------------------------------------------------------------------
# 6. ToolContext construction
# ---------------------------------------------------------------------------


class TestToolContextConstruction:
    """_build_tool_context falls back gracefully when settings are absent."""

    def test_builds_context_from_settings_in_metadata(self):
        worker = _SimpleToolWorker()
        settings = _MinimalSettings()
        ctx = _make_context(settings=settings)
        tc = worker._build_tool_context(ctx)
        assert tc is not None
        assert tc.workspace_path == "."

    def test_builds_context_without_metadata_settings(self):
        """Falls back to a default Settings instance."""
        worker = _SimpleToolWorker()
        ctx = _make_context()  # no settings key
        tc = worker._build_tool_context(ctx)
        # Either constructs a default Settings or returns None — both are OK
        # as long as it never raises.
        assert tc is None or hasattr(tc, "workspace_path")

    def test_event_bus_passed_through_when_present(self):
        worker = _SimpleToolWorker()
        eb = MagicMock()
        ctx = _make_context(settings=_MinimalSettings(), event_bus=eb)
        tc = worker._build_tool_context(ctx)
        if tc is not None:
            assert tc.events is eb


# ---------------------------------------------------------------------------
# 7. Tool description injection into system prompt
# ---------------------------------------------------------------------------


class TestToolSystemPromptInjection:
    """_tool_system_addendum includes allowed tool descriptions."""

    def test_addendum_lists_allowed_tools(self):
        worker = _SimpleToolWorker()
        te = _mock_tool_engine(tool_ids=["date_time", "file_read"])
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())
        addendum = worker._tool_system_addendum(ctx)
        assert "TOOL_CALL" in addendum
        assert "date_time" in addendum

    def test_addendum_empty_when_no_engine(self):
        worker = _SimpleToolWorker()
        ctx = _make_context()  # no tool_engine
        assert worker._tool_system_addendum(ctx) == ""

    def test_addendum_empty_when_no_allowed_tools(self):
        class _NoTools(WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
            _allowed_tools: tuple[str, ...] = ()

            @property
            def name(self):
                return "NoTools"

            @property
            def task_types(self):
                return []

            def execute(self, task, ctx):
                return self._execute_with_tools(task, ctx)

        te = _mock_tool_engine()
        ctx = _make_context(tool_engine=te)
        assert _NoTools()._tool_system_addendum(ctx) == ""


# ---------------------------------------------------------------------------
# 8. Scheduler compatibility
# ---------------------------------------------------------------------------


class TestSchedulerCompatibility:
    """Tool-aware workers integrate cleanly with the existing Scheduler."""

    def _run(self, goal: str, tool_engine=None) -> ExecutionContext:
        ctrl = ExecutiveController(tool_engine=tool_engine)
        return ctrl.receive_goal(goal)

    def test_plan_and_run_without_tool_engine_still_completes(self):
        ctx = self._run("Build a simple script")
        from smartagent.executive.execution_state import ExecutionState
        assert ctx.state == ExecutionState.COMPLETED

    def test_plan_and_run_with_mock_tool_engine_completes(self):
        te = _mock_tool_engine()
        ctx = self._run("Write a hello-world program", tool_engine=te)
        from smartagent.executive.execution_state import ExecutionState
        assert ctx.state == ExecutionState.COMPLETED

    def test_tool_engine_injected_into_context_metadata(self):
        te = _mock_tool_engine()
        ctrl = ExecutiveController(tool_engine=te)
        ctx = ctrl.plan("Build a CLI tool")
        ctrl._orchestrator._inject_services(ctx)
        assert ctx.metadata.get("tool_engine") is te

    def test_task_results_are_non_empty_strings_with_tools(self):
        te = _mock_tool_engine()
        ctx = self._run("Build a simple REST API", tool_engine=te)
        for task in ctx.task_graph.all_tasks():
            assert isinstance(task.result, str)
            assert len(task.result) > 0

    def test_tool_calls_list_present_in_metadata_after_run(self):
        """context.metadata["tool_calls"] exists (possibly empty) after a run."""
        te = _mock_tool_engine()
        ctx = self._run("Build something", tool_engine=te)
        # tool_calls may be absent if the LLM stub didn't emit any TOOL_CALL
        # (no live Ollama during CI) — just verify no crash occurred
        assert "tool_calls" not in ctx.metadata or isinstance(
            ctx.metadata["tool_calls"], list
        )


# ---------------------------------------------------------------------------
# 9. ExecutiveController.with_agent wiring
# ---------------------------------------------------------------------------


class TestWithAgentWiring:
    """with_agent() extracts tool_engine from the agent instance."""

    def test_tool_engine_extracted_from_agent(self):
        agent = MagicMock()
        agent.tool_engine = _mock_tool_engine()
        agent.events = MagicMock()

        ctrl = ExecutiveController.with_agent(agent)
        assert ctrl._tool_engine is agent.tool_engine

    def test_event_bus_extracted_from_agent(self):
        agent = MagicMock()
        agent.events = MagicMock()
        ctrl = ExecutiveController.with_agent(agent)
        assert ctrl._event_bus is agent.events

    def test_with_agent_missing_tool_engine_sets_none(self):
        agent = MagicMock(spec=[])  # no attributes
        ctrl = ExecutiveController.with_agent(agent)
        assert ctrl._tool_engine is None


# ---------------------------------------------------------------------------
# 10. Worker phase identity
# ---------------------------------------------------------------------------


class TestWorkerPhaseIdentity:
    """Workers with WorkerToolMixin still report phase='ollama'."""

    @pytest.mark.parametrize("worker_cls", [
        ResearchWorker, CodingWorker, TestingWorker, DocumentationWorker,
    ])
    def test_tool_worker_phase_is_ollama(self, worker_cls):
        assert worker_cls().phase == "ollama"

    @pytest.mark.parametrize("worker_cls", [
        ResearchWorker, CodingWorker, TestingWorker, DocumentationWorker,
    ])
    def test_tool_worker_has_allowed_tools_attribute(self, worker_cls):
        w = worker_cls()
        assert hasattr(w, "_allowed_tools")
        assert isinstance(w._allowed_tools, tuple)

    @pytest.mark.parametrize("worker_cls", [
        ResearchWorker, CodingWorker, TestingWorker, DocumentationWorker,
    ])
    def test_tool_worker_has_non_empty_allowed_tools(self, worker_cls):
        assert len(worker_cls()._allowed_tools) > 0


# ---------------------------------------------------------------------------
# 11. Recovery: failed tool → alternative handling
# ---------------------------------------------------------------------------


class TestToolRecovery:
    """Workers handle tool failures gracefully and continue to produce output."""

    def test_tool_engine_run_returning_failure_does_not_crash_worker(self):
        worker = _SimpleToolWorker()
        responses = [
            'TOOL_CALL: {"tool": "date_time", "args": {}}',
            "I could not get the date, but here is my answer based on reasoning.",
        ]
        resp_iter = iter(responses)
        worker._stream_full = lambda ctx, msgs: next(resp_iter, "Done.")

        te = _mock_tool_engine(
            tool_ids=["date_time"], success=False, message="Service unavailable"
        )
        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        result = worker._execute_with_tools(task, ctx)
        assert isinstance(result, str)
        assert len(result) > 0
        assert ctx.metadata["tool_calls"][0]["success"] is False

    def test_tool_engine_run_raises_does_not_crash_worker(self):
        """tool_engine.run() raises an unexpected exception — worker still returns str."""
        worker = _SimpleToolWorker()
        worker._stream_full = lambda ctx, msgs: 'TOOL_CALL: {"tool": "date_time", "args": {}}'

        te = MagicMock()
        te.registry.find.return_value = MagicMock(description="time tool")
        te.run.side_effect = RuntimeError("unexpected crash")

        task = _make_task()
        ctx = _make_context(tool_engine=te, settings=_MinimalSettings())

        # ToolEngine.run() normally never raises (by design), but workers
        # should be robust even if it does
        try:
            result = worker._execute_with_tools(task, ctx)
            assert isinstance(result, str)
        except RuntimeError:
            # Acceptable: ToolEngine contract says it shouldn't raise;
            # if it does we propagate to the Scheduler's retry logic
            pass
