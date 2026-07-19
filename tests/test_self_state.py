"""Tests for smartagent.server.self_state — reads/updates MARK's real
self-state via agent.mind (a real ExecutiveController from
smartagent.mind), not a second, separate self-model. See self_state.py's
module docstring for why it's a thin stateless helper now, not a class
with its own singleton."""

from __future__ import annotations

from types import SimpleNamespace

from smartagent.mind.executive.executive_controller import ExecutiveController
from smartagent.server import self_state


def _fake_agent(active_model: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        mind=ExecutiveController(),
        model_manager=SimpleNamespace(_active_model_id=active_model),
    )


class TestSnapshot:
    def test_default_snapshot_is_idle(self):
        agent = _fake_agent()
        snap = self_state.snapshot(agent)
        assert snap["mode"] == "idle"
        assert snap["active_tasks"] == 0

    def test_snapshot_shape(self):
        d = self_state.snapshot(_fake_agent())
        for key in (
            "identity", "owner", "mode", "state", "current_activity",
            "active_tasks", "model", "memory", "voice", "confidence", "health",
        ):
            assert key in d
        assert d["identity"] == "MARK"

    def test_voice_honestly_reports_disabled(self):
        assert self_state.snapshot(_fake_agent())["voice"] == "disabled"

    def test_reads_the_live_agent_not_a_cached_copy(self):
        """Two snapshots of two different agents must never share state —
        this module holds nothing of its own."""
        a1, a2 = _fake_agent(), _fake_agent()
        self_state.task_started(a1, "task on agent one")
        assert self_state.snapshot(a1)["active_tasks"] == 1
        assert self_state.snapshot(a2)["active_tasks"] == 0


class TestTaskLifecycle:
    def test_task_started_increments_and_sets_executing(self):
        agent = _fake_agent()
        self_state.task_started(agent, "build the API")
        snap = self_state.snapshot(agent)
        assert snap["active_tasks"] == 1
        assert snap["mode"] == "executing"
        assert snap["current_activity"] == "build the API"

    def test_task_finished_returns_to_idle(self):
        agent = _fake_agent()
        self_state.task_started(agent, "build the API")
        self_state.task_finished(agent, "build the API", succeeded=True, what_happened="Built it.")
        snap = self_state.snapshot(agent)
        assert snap["active_tasks"] == 0
        assert snap["mode"] == "idle"

    def test_zero_arg_defaults_still_work(self):
        agent = _fake_agent()
        self_state.task_started(agent)
        self_state.task_finished(agent)
        assert self_state.snapshot(agent)["active_tasks"] == 0

    def test_a_failed_task_still_returns_to_idle(self):
        agent = _fake_agent()
        self_state.task_started(agent, "risky thing")
        self_state.task_finished(agent, "risky thing", succeeded=False, what_happened="It broke.")
        assert self_state.snapshot(agent)["mode"] == "idle"


class TestModelReporting:
    def test_active_model_reflected_in_snapshot(self):
        agent = _fake_agent(active_model="llama3.2:3b")
        assert self_state.snapshot(agent)["model"] == "llama3.2:3b"

    def test_no_active_model_reports_as_string_none(self):
        assert self_state.snapshot(_fake_agent())["model"] == "none"


class TestIdleSnapshot:
    def test_idle_snapshot_needs_no_agent(self):
        snap = self_state.idle_snapshot()
        assert snap["identity"] == "MARK"
        assert snap["mode"] == "idle"
        assert snap["current_activity"] == "not started"
