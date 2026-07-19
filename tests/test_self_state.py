"""Tests for smartagent.server.self_state — Phase 5 (internal self-state)."""

from __future__ import annotations

from smartagent.server.self_state import Mode, SelfState, SelfStateTracker, get_self_state_tracker


class TestSelfState:
    def test_default_state_is_idle(self):
        s = SelfState()
        assert s.mode == Mode.IDLE
        assert s.active_tasks == 0

    def test_as_dict_shape(self):
        d = SelfState().as_dict()
        for key in ("identity", "mode", "active_tasks", "model", "memory", "voice"):
            assert key in d
        assert d["identity"] == "MARK"

    def test_voice_honestly_reports_disabled(self):
        """Phase 4 (voice) hasn't been built — self-state must not overclaim."""
        assert SelfState().as_dict()["voice"] == "disabled"


class TestSelfStateTracker:
    def test_task_started_increments_and_sets_executing(self):
        t = SelfStateTracker()
        t.task_started()
        snap = t.snapshot()
        assert snap["active_tasks"] == 1
        assert snap["mode"] == "executing"

    def test_task_finished_decrements_and_returns_to_idle(self):
        t = SelfStateTracker()
        t.task_started()
        t.task_finished()
        snap = t.snapshot()
        assert snap["active_tasks"] == 0
        assert snap["mode"] == "idle"

    def test_multiple_concurrent_tasks_stay_executing_until_all_finish(self):
        t = SelfStateTracker()
        t.task_started()
        t.task_started()
        assert t.snapshot()["active_tasks"] == 2
        t.task_finished()
        assert t.snapshot()["mode"] == "executing"  # one still active
        t.task_finished()
        assert t.snapshot()["mode"] == "idle"

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


class TestSelfStateSingleton:
    def test_get_self_state_tracker_returns_same_instance(self):
        assert get_self_state_tracker() is get_self_state_tracker()
