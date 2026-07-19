"""Tests for smartagent.server.self_state — MARK's internal self-state.

Wraps a real smartagent.mind.executive.executive_controller.ExecutiveController
(attention/confidence/homeostasis/state machine), not a bare dataclass — see
self_state.py's module docstring for why. Tests assert on the tracker's own
public contract, not on ExecutiveController's internals directly."""

from __future__ import annotations

from smartagent.server.self_state import SelfStateTracker, get_self_state_tracker


class TestSelfStateTracker:
    def test_default_snapshot_is_idle(self):
        t = SelfStateTracker()
        snap = t.snapshot()
        assert snap["mode"] == "idle"
        assert snap["active_tasks"] == 0

    def test_snapshot_shape(self):
        d = SelfStateTracker().snapshot()
        for key in (
            "identity", "owner", "mode", "state", "current_activity",
            "active_tasks", "model", "memory", "voice", "confidence", "health",
        ):
            assert key in d
        assert d["identity"] == "MARK"

    def test_voice_honestly_reports_disabled(self):
        """Voice hasn't been built — self-state must not overclaim."""
        assert SelfStateTracker().snapshot()["voice"] == "disabled"

    def test_task_started_increments_and_sets_executing(self):
        t = SelfStateTracker()
        t.task_started("build the API")
        snap = t.snapshot()
        assert snap["active_tasks"] == 1
        assert snap["mode"] == "executing"
        assert snap["current_activity"] == "build the API"

    def test_task_finished_decrements_and_returns_to_idle(self):
        t = SelfStateTracker()
        t.task_started("build the API")
        t.task_finished(succeeded=True, what_happened="Built it.")
        snap = t.snapshot()
        assert snap["active_tasks"] == 0
        assert snap["mode"] == "idle"

    def test_task_started_and_finished_use_sensible_defaults(self):
        """Zero-arg calls (as api.py used to make before it started passing
        the real goal/outcome) must still work without raising."""
        t = SelfStateTracker()
        t.task_started()
        t.task_finished()
        assert t.snapshot()["active_tasks"] == 0

    def test_multiple_concurrent_tasks_stay_executing_until_all_finish(self):
        t = SelfStateTracker()
        t.task_started("task one")
        t.task_started("task two")
        assert t.snapshot()["active_tasks"] == 2
        t.task_finished()
        assert t.snapshot()["active_tasks"] == 1
        t.task_finished()
        assert t.snapshot()["active_tasks"] == 0

    def test_active_tasks_never_goes_negative(self):
        t = SelfStateTracker()
        t.task_finished()  # no task_started() first
        assert t.snapshot()["active_tasks"] == 0

    def test_set_model_reflected_in_snapshot(self):
        t = SelfStateTracker()
        t.set_model("llama3.2:3b")
        assert t.snapshot()["model"] == "llama3.2:3b"

    def test_set_model_none_reports_as_string_none(self):
        t = SelfStateTracker()
        assert t.snapshot()["model"] == "none"

    def test_set_memory_status_reflected_in_snapshot(self):
        t = SelfStateTracker()
        t.set_memory_status("degraded")
        assert t.snapshot()["memory"] == "degraded"

    def test_a_failed_task_still_returns_to_idle(self):
        t = SelfStateTracker()
        t.task_started("risky thing")
        t.task_finished(succeeded=False, what_happened="It broke.")
        assert t.snapshot()["mode"] == "idle"


class TestSelfStateSingleton:
    def test_get_self_state_tracker_returns_same_instance(self):
        assert get_self_state_tracker() is get_self_state_tracker()
