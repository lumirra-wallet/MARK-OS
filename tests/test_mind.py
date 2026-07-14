"""
Tests for Milestone 6 — MARK Mind OS v1.

Covers:
    - IdentityEngine: default identity, round-trip load/save via Markdown,
      graceful fallback for a missing file, `update()`.
    - SelfModelEngine: initial seeding from Identity, `update()` diffing +
      recent_changes bounding, `SelfModelUpdated` events, `describe()`.
    - WorkingMemory: put/get, TTL expiration (via an injectable clock),
      category filtering, purge_expired, forget, clear.
    - AttentionManager: ranking, max_concurrent eviction, interrupt/resume,
      `AttentionShifted` events.
    - ContextManager: assembly, per-source truncation, `render()` truncation.
    - ConfidenceEngine: scoring heuristic (evidence/conflicts/missing/
      unknowns), history bounding, `ConfidenceChanged` events, never a
      flat/fabricated default.
    - StateMachine: transitions, history, `is_in()`, `StateChanged` events.
    - ReflectionEngine: reflect(), should_become_memory/could_improve
      heuristics, `ReflectionFinished` events, memory_worthy filtering.
    - HealthMetrics/HomeostasisEngine: score(), band thresholds,
      `HealthChanged` only fires on band changes.
    - DigitalSensorySystem: detect(), history filtering, `SensorySignalDetected` events.
    - DigitalHomeostasisLoop: tick() answers (healthy/overloaded/progress/
      goals-match-mission/failing/notify).
    - ExecutiveController: composition root wiring, goal/task coordination,
      priority queue, interrupt/resume passthrough, decide(), build_context(),
      health_check(), describe(), MindProviders defaults and binding.
    - SmartAgent integration: `agent.mind` exists and observes
      `handle_message()` (state transitions, reflections, self-model sync)
      WITHOUT changing `handle_message()`'s returned message — zero
      regression to Brain/Skills/Tools/Model Framework behavior.
"""

from __future__ import annotations

import pytest

from smartagent.brain.agent import SmartAgent
from smartagent.brain.events import EventBus, Events
from smartagent.config.settings import Settings
from smartagent.mind.attention.attention_manager import AttentionManager, FocusItem
from smartagent.mind.confidence.confidence_engine import ConfidenceEngine
from smartagent.mind.context.context_manager import ContextManager
from smartagent.mind.executive.executive_controller import ExecutiveController, MindProviders
from smartagent.mind.homeostasis.health_metrics import HealthMetrics
from smartagent.mind.homeostasis.homeostasis_engine import HomeostasisEngine
from smartagent.mind.homeostasis.loop import DigitalHomeostasisLoop
from smartagent.mind.homeostasis.sensory import DigitalSensorySystem, SensorySignal
from smartagent.mind.identity.identity_engine import IdentityEngine, default_identity
from smartagent.mind.identity.identity_model import Identity
from smartagent.mind.reflection.reflection_engine import ReflectionEngine
from smartagent.mind.self_model.self_model_engine import SelfModelEngine
from smartagent.mind.state.state_machine import InternalState, StateMachine
from smartagent.mind.working_memory.working_memory import WorkingMemory


def _settings(tmp_path):
    s = Settings.load()
    s.vault_path = str(tmp_path / "vault")
    return s


def _agent(tmp_path, **overrides) -> SmartAgent:
    settings = _settings(tmp_path)
    for key, value in overrides.items():
        setattr(settings, key, value)
    return SmartAgent(settings=settings)


# ---------------------------------------------------------------------------
# IdentityEngine
# ---------------------------------------------------------------------------

class TestIdentityEngine:
    def test_default_identity_matches_smartagent_shape(self):
        identity = default_identity()
        assert identity.name == "MARK"
        assert identity.owner == "Mr. Smart"
        assert "AI Operating System" in identity.mission
        assert len(identity.core_values) == 7
        assert "Mind" in identity.architecture_vision

    def test_missing_file_falls_back_to_default(self, tmp_path):
        engine = IdentityEngine(path=str(tmp_path / "does_not_exist.md"))
        assert engine.identity.name == "MARK"
        assert engine.identity == default_identity()

    def test_round_trip_save_then_load(self, tmp_path):
        path = tmp_path / "identity.md"
        custom = Identity(
            name="TestBot",
            owner="Tester",
            mission="Test everything.",
            core_values=["Be correct.", "Be fast."],
            operating_principles=["Follow instructions."],
            safety_rules=["Ask before deleting."],
            architecture_vision=["Brain", "Mind"],
            personality="Meticulous.",
            long_term_objectives=["Full coverage."],
        )
        engine = IdentityEngine(path=str(path), identity=custom)
        engine.save()

        reloaded = IdentityEngine(path=str(path))
        assert reloaded.identity.name == "TestBot"
        assert reloaded.identity.owner == "Tester"
        assert "Test everything." in reloaded.identity.mission
        assert reloaded.identity.core_values == ["Be correct.", "Be fast."]
        assert reloaded.identity.architecture_vision == ["Brain", "Mind"]
        assert reloaded.identity.long_term_objectives == ["Full coverage."]

    def test_parses_real_smartagent_md(self):
        engine = IdentityEngine(path="SMARTAGENT.md")
        assert engine.identity.name == "MARK"
        assert engine.identity.owner == "Mr. Smart"
        assert len(engine.identity.core_values) >= 1
        assert len(engine.identity.safety_rules) >= 1

    def test_update_mutates_identity(self, tmp_path):
        engine = IdentityEngine(path=str(tmp_path / "id.md"))
        engine.update(personality="Snarky.")
        assert engine.identity.personality == "Snarky."

    def test_update_unknown_field_raises(self, tmp_path):
        engine = IdentityEngine(path=str(tmp_path / "id.md"))
        with pytest.raises(AttributeError):
            engine.update(not_a_real_field=True)

    def test_to_dict(self, tmp_path):
        engine = IdentityEngine(path=str(tmp_path / "id.md"))
        d = engine.to_dict()
        assert d["name"] == "MARK"
        assert isinstance(d["core_values"], list)

    def test_identity_summary(self):
        identity = default_identity()
        assert "MARK" in identity.summary()
        assert "Mr. Smart" in identity.summary()


# ---------------------------------------------------------------------------
# SelfModelEngine
# ---------------------------------------------------------------------------

class TestSelfModelEngine:
    def test_seeded_from_identity(self):
        identity = default_identity()
        engine = SelfModelEngine(identity=identity)
        snapshot = engine.snapshot()
        assert snapshot.name == "MARK"
        assert snapshot.owner == "Mr. Smart"
        assert snapshot.mission == identity.mission

    def test_update_changes_fields_and_records_change_log(self):
        engine = SelfModelEngine(identity=default_identity())
        engine.update(current_activity="thinking", confidence=0.75)
        snapshot = engine.snapshot()
        assert snapshot.current_activity == "thinking"
        assert snapshot.confidence == 0.75
        assert len(snapshot.recent_changes) == 2

    def test_update_noop_for_unchanged_values_skips_change_log(self):
        engine = SelfModelEngine(identity=default_identity())
        engine.update(current_activity="idle")  # already "idle" — no-op
        assert engine.snapshot().recent_changes == []

    def test_update_unknown_field_raises(self):
        engine = SelfModelEngine(identity=default_identity())
        with pytest.raises(AttributeError):
            engine.update(not_a_field="x")

    def test_recent_changes_bounded(self):
        engine = SelfModelEngine(identity=default_identity())
        for i in range(30):
            engine.update(current_activity=f"activity-{i}")
        assert len(engine.snapshot().recent_changes) <= 20

    def test_publishes_self_model_updated_event(self):
        bus = EventBus()
        engine = SelfModelEngine(identity=default_identity(), event_bus=bus)
        engine.update(confidence=0.9)
        names = [e.name for e in bus.history()]
        assert Events.SELF_MODEL_UPDATED in names

    def test_describe_answers_key_questions(self):
        engine = SelfModelEngine(identity=default_identity())
        description = engine.describe()
        assert "MARK" in description
        assert "Mr. Smart" in description
        assert "Confidence" in description
        assert "Health" in description


# ---------------------------------------------------------------------------
# WorkingMemory
# ---------------------------------------------------------------------------

class TestWorkingMemory:
    def test_put_and_get(self):
        wm = WorkingMemory()
        wm.put("k1", "v1", category="fact")
        assert wm.get("k1") == "v1"

    def test_get_missing_returns_none(self):
        wm = WorkingMemory()
        assert wm.get("nope") is None

    def test_ttl_expiration_via_fake_clock(self):
        now = [0.0]
        wm = WorkingMemory(default_ttl_seconds=10, clock=lambda: now[0])
        wm.put("k1", "v1")
        assert wm.get("k1") == "v1"
        now[0] = 11.0
        assert wm.get("k1") is None

    def test_category_filtering(self):
        wm = WorkingMemory()
        wm.put("a", 1, category="fact")
        wm.put("b", 2, category="plan")
        facts = wm.all(category="fact")
        assert len(facts) == 1
        assert facts[0].key == "a"

    def test_purge_expired_removes_only_expired(self):
        now = [0.0]
        wm = WorkingMemory(clock=lambda: now[0])
        wm.put("expiring", 1, ttl_seconds=5)
        wm.put("fresh", 2, ttl_seconds=1000)
        now[0] = 6.0
        removed = wm.purge_expired()
        assert removed == 1
        assert wm.get("fresh") == 2

    def test_forget_and_clear(self):
        wm = WorkingMemory()
        wm.put("a", 1)
        assert wm.forget("a") is True
        assert wm.forget("a") is False
        wm.put("b", 2)
        wm.clear()
        assert len(wm) == 0

    def test_len_purges_expired(self):
        now = [0.0]
        wm = WorkingMemory(clock=lambda: now[0])
        wm.put("a", 1, ttl_seconds=1)
        now[0] = 5.0
        assert len(wm) == 0

    def test_not_permanent_by_default(self):
        """Working memory must never claim to be durable storage."""
        wm = WorkingMemory()
        assert wm.default_ttl_seconds > 0


# ---------------------------------------------------------------------------
# AttentionManager
# ---------------------------------------------------------------------------

class TestAttentionManager:
    def test_rank_orders_by_importance_desc(self):
        am = AttentionManager()
        items = [FocusItem("low", 0.1), FocusItem("high", 0.9), FocusItem("mid", 0.5)]
        ranked = am.rank(items)
        assert [i.name for i in ranked] == ["high", "mid", "low"]

    def test_focus_on_respects_max_concurrent(self):
        am = AttentionManager(max_concurrent=2)
        am.focus_on(FocusItem("a", 0.3))
        am.focus_on(FocusItem("b", 0.9))
        am.focus_on(FocusItem("c", 0.5))
        focus_names = [i.name for i in am.current_focus()]
        assert len(focus_names) == 2
        assert "b" in focus_names  # highest importance always survives
        assert "a" not in focus_names  # lowest importance evicted

    def test_drop(self):
        am = AttentionManager()
        am.focus_on(FocusItem("a", 0.5))
        assert am.drop("a") is True
        assert am.drop("a") is False
        assert am.current_focus() == []

    def test_interrupt_and_resume(self):
        am = AttentionManager(max_concurrent=3)
        am.focus_on(FocusItem("original", 0.5))
        am.interrupt(FocusItem("urgent", 1.0))
        assert [i.name for i in am.current_focus()] == ["urgent"]
        am.resume()
        assert [i.name for i in am.current_focus()] == ["original"]

    def test_resume_without_interrupt_is_noop(self):
        am = AttentionManager()
        am.focus_on(FocusItem("a", 0.5))
        result = am.resume()
        assert [i.name for i in result] == ["a"]

    def test_publishes_attention_shifted(self):
        bus = EventBus()
        am = AttentionManager(event_bus=bus)
        am.focus_on(FocusItem("a", 0.5))
        names = [e.name for e in bus.history()]
        assert Events.ATTENTION_SHIFTED in names

    def test_clear(self):
        am = AttentionManager()
        am.focus_on(FocusItem("a", 0.5))
        am.interrupt(FocusItem("b", 1.0))
        am.clear()
        assert am.current_focus() == []
        assert am.resume() == []


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_assemble_caps_items_per_source(self):
        cm = ContextManager(max_items_per_source=2)
        bundle = cm.assemble(conversation=["a", "b", "c", "d"])
        assert bundle.conversation == ["a", "b"]

    def test_assemble_handles_none_sources(self):
        cm = ContextManager()
        bundle = cm.assemble()
        assert bundle.conversation == []
        assert bundle.render() == ""

    def test_render_includes_section_headers(self):
        cm = ContextManager()
        bundle = cm.assemble(identity=["MARK is an AI."], goals=["Ship Milestone 6."])
        rendered = bundle.render()
        assert "[Identity]" in rendered
        assert "[Goals]" in rendered
        assert "MARK is an AI." in rendered

    def test_render_truncates_to_max_chars(self):
        cm = ContextManager(max_items_per_source=100)
        bundle = cm.assemble(knowledge=["x" * 100 for _ in range(100)])
        rendered = bundle.render(max_chars=500)
        assert len(rendered) <= 520  # 500 + truncation marker slack
        assert "truncated" in rendered


# ---------------------------------------------------------------------------
# ConfidenceEngine
# ---------------------------------------------------------------------------

class TestConfidenceEngine:
    def test_no_evidence_yields_low_confidence_and_recommendation(self):
        engine = ConfidenceEngine()
        assessment = engine.score(reason="guessing")
        assert assessment.confidence <= 0.5
        assert any("guess" in r.lower() for r in assessment.recommendations)

    def test_evidence_increases_confidence(self):
        engine = ConfidenceEngine()
        low = engine.score(reason="r", evidence=[])
        high = engine.score(reason="r", evidence=["e1", "e2", "e3"])
        assert high.confidence > low.confidence

    def test_conflicts_and_missing_and_unknowns_penalize(self):
        engine = ConfidenceEngine()
        clean = engine.score(reason="r", evidence=["e1", "e2"])
        messy = engine.score(
            reason="r",
            evidence=["e1", "e2"],
            conflicts=["c1"],
            missing_information=["m1"],
            unknowns=["u1"],
        )
        assert messy.confidence < clean.confidence
        assert messy.confidence >= 0.0

    def test_confidence_never_exceeds_bounds(self):
        engine = ConfidenceEngine()
        assessment = engine.score(reason="r", evidence=[f"e{i}" for i in range(50)])
        assert 0.0 <= assessment.confidence <= 1.0

    def test_history_and_latest(self):
        engine = ConfidenceEngine()
        assert engine.latest() is None
        engine.score(reason="first")
        engine.score(reason="second")
        assert len(engine.history()) == 2
        assert engine.latest().reason == "second"

    def test_history_bounded(self):
        engine = ConfidenceEngine()
        for i in range(60):
            engine.score(reason=f"r{i}")
        assert len(engine.history()) <= 50

    def test_publishes_confidence_changed(self):
        bus = EventBus()
        engine = ConfidenceEngine(event_bus=bus)
        engine.score(reason="r")
        names = [e.name for e in bus.history()]
        assert Events.CONFIDENCE_CHANGED in names


# ---------------------------------------------------------------------------
# StateMachine
# ---------------------------------------------------------------------------

class TestStateMachine:
    def test_starts_idle(self):
        sm = StateMachine()
        assert sm.state == InternalState.IDLE

    def test_transition_updates_state_and_history(self):
        sm = StateMachine()
        sm.transition(InternalState.THINKING, reason="processing")
        assert sm.state == InternalState.THINKING
        history = sm.history()
        assert len(history) == 1
        assert history[0].from_state == InternalState.IDLE
        assert history[0].to_state == InternalState.THINKING
        assert history[0].reason == "processing"

    def test_is_in(self):
        sm = StateMachine()
        assert sm.is_in(InternalState.IDLE, InternalState.SLEEPING)
        sm.transition(InternalState.ERROR)
        assert not sm.is_in(InternalState.IDLE)
        assert sm.is_in(InternalState.ERROR)

    def test_history_bounded(self):
        sm = StateMachine()
        for _ in range(250):
            sm.transition(InternalState.THINKING)
        assert len(sm.history()) <= 200

    def test_publishes_state_changed(self):
        bus = EventBus()
        sm = StateMachine(event_bus=bus)
        sm.transition(InternalState.PLANNING)
        names = [e.name for e in bus.history()]
        assert Events.STATE_CHANGED in names


# ---------------------------------------------------------------------------
# ReflectionEngine
# ---------------------------------------------------------------------------

class TestReflectionEngine:
    def test_reflect_success_not_flagged_memory_worthy_without_learning(self):
        engine = ReflectionEngine()
        reflection = engine.reflect(task_name="t1", succeeded=True, what_happened="It worked.")
        assert reflection.should_become_memory is False
        assert reflection.could_improve_future_performance is False

    def test_reflect_failure_is_memory_worthy(self):
        engine = ReflectionEngine()
        reflection = engine.reflect(
            task_name="t2", succeeded=False, what_happened="It broke.", what_failed="Timeout."
        )
        assert reflection.should_become_memory is True
        assert reflection.could_improve_future_performance is True

    def test_learned_flags_memory_worthy_even_on_success(self):
        engine = ReflectionEngine()
        reflection = engine.reflect(
            task_name="t3", succeeded=True, what_happened="Worked.", learned="Cache the result next time."
        )
        assert reflection.should_become_memory is True

    def test_list_reflections_filters_by_outcome(self):
        engine = ReflectionEngine()
        engine.reflect(task_name="a", succeeded=True, what_happened="ok")
        engine.reflect(task_name="b", succeeded=False, what_happened="bad")
        assert len(engine.list_reflections(succeeded=True)) == 1
        assert len(engine.list_reflections(succeeded=False)) == 1
        assert len(engine.list_reflections()) == 2

    def test_memory_worthy_filter(self):
        engine = ReflectionEngine()
        engine.reflect(task_name="a", succeeded=True, what_happened="ok")
        engine.reflect(task_name="b", succeeded=False, what_happened="bad")
        assert len(engine.memory_worthy()) == 1

    def test_publishes_reflection_finished(self):
        bus = EventBus()
        engine = ReflectionEngine(event_bus=bus)
        engine.reflect(task_name="a", succeeded=True, what_happened="ok")
        names = [e.name for e in bus.history()]
        assert Events.REFLECTION_FINISHED in names


# ---------------------------------------------------------------------------
# HealthMetrics / HomeostasisEngine
# ---------------------------------------------------------------------------

class TestHomeostasis:
    def test_healthy_defaults_score_high(self):
        metrics = HealthMetrics()
        assert metrics.score() > 0.9

    def test_overloaded_metrics_score_low(self):
        metrics = HealthMetrics(memory_usage=1.0, task_load=1.0, errors=10, queue_length=50)
        assert metrics.score() < 0.3

    def test_score_bounded(self):
        metrics = HealthMetrics(
            memory_usage=5.0, task_load=5.0, errors=1000, queue_length=1000, response_latency_ms=100000
        )
        assert metrics.score() == 0.0

    def test_engine_reports_healthy_before_any_check(self):
        engine = HomeostasisEngine()
        assert engine.is_healthy() is True
        assert engine.last_report() is None

    def test_check_returns_report(self):
        engine = HomeostasisEngine()
        report = engine.check(HealthMetrics())
        assert report.band == "healthy"
        assert engine.is_healthy() is True

    def test_health_changed_only_fires_on_band_transitions(self):
        bus = EventBus()
        engine = HomeostasisEngine(event_bus=bus)
        engine.check(HealthMetrics())  # healthy -> healthy: first check still transitions from None
        engine.check(HealthMetrics())  # healthy -> healthy again: no new event
        count_after_two_healthy = len([e for e in bus.history() if e.name == Events.HEALTH_CHANGED])
        engine.check(HealthMetrics(memory_usage=1.0, task_load=1.0, errors=10, queue_length=50))  # -> critical
        count_after_critical = len([e for e in bus.history() if e.name == Events.HEALTH_CHANGED])
        assert count_after_critical > count_after_two_healthy


class TestDigitalSensorySystem:
    def test_detect_records_and_returns_event(self):
        sensory = DigitalSensorySystem()
        event = sensory.detect(SensorySignal.LOW_CONFIDENCE, detail="score was 0.1")
        assert event.signal == SensorySignal.LOW_CONFIDENCE
        assert len(sensory.history()) == 1

    def test_history_filters_by_signal(self):
        sensory = DigitalSensorySystem()
        sensory.detect(SensorySignal.TOOL_FAILURE)
        sensory.detect(SensorySignal.NEW_GOAL)
        assert len(sensory.history(SensorySignal.TOOL_FAILURE)) == 1

    def test_publishes_sensory_signal_detected(self):
        bus = EventBus()
        sensory = DigitalSensorySystem(event_bus=bus)
        sensory.detect(SensorySignal.PERMISSION_DENIED)
        names = [e.name for e in bus.history()]
        assert Events.SENSORY_SIGNAL_DETECTED in names


class TestDigitalHomeostasisLoop:
    def test_tick_reports_healthy_and_not_overloaded_by_default(self):
        loop = DigitalHomeostasisLoop(HomeostasisEngine())
        result = loop.tick(HealthMetrics())
        assert result.is_healthy is True
        assert result.is_overloaded is False
        assert result.should_notify_owner is False

    def test_tick_flags_overloaded_and_notify(self):
        loop = DigitalHomeostasisLoop(HomeostasisEngine())
        result = loop.tick(HealthMetrics(memory_usage=1.0, task_load=1.0, errors=10, queue_length=50))
        assert result.is_overloaded is True
        assert result.should_notify_owner is True
        assert result.notes

    def test_tick_goals_match_mission_keyword_check(self):
        loop = DigitalHomeostasisLoop(HomeostasisEngine())
        matching = loop.tick(
            HealthMetrics(), goals=["Build the Mind milestone"], mission_keywords=["mind", "milestone"]
        )
        assert matching.goals_match_mission is True

        mismatching = loop.tick(HealthMetrics(), goals=["Bake a cake"], mission_keywords=["software", "engineer"])
        assert mismatching.goals_match_mission is False

    def test_tick_no_progress_is_noted(self):
        loop = DigitalHomeostasisLoop(HomeostasisEngine())
        result = loop.tick(HealthMetrics(), progress_made=False)
        assert result.is_making_progress is False
        assert any("progress" in note.lower() for note in result.notes)


# ---------------------------------------------------------------------------
# ExecutiveController
# ---------------------------------------------------------------------------

class TestExecutiveController:
    def test_constructs_with_defaults(self):
        controller = ExecutiveController()
        assert controller.identity.name == "MARK"
        snapshot = controller.self_model()
        assert snapshot.name == "MARK"

    def test_mind_providers_default_to_empty(self):
        providers = MindProviders()
        assert providers.active_goal() is None
        assert providers.goals() == []
        assert providers.skills() == []
        assert providers.tools() == []
        assert providers.active_model() is None
        assert providers.running_processes() == []

    def test_bound_providers_reflect_in_self_model(self):
        providers = MindProviders(
            goals=lambda: ["goal-1"],
            skills=lambda: ["skill-1"],
            tools=lambda: ["tool-1"],
            active_model=lambda: "mock",
        )
        controller = ExecutiveController(providers=providers)
        controller.sync_self_model()
        snapshot = controller.self_model()
        assert snapshot.goals == ["goal-1"]
        assert snapshot.skills == ["skill-1"]
        assert snapshot.tools == ["tool-1"]
        assert snapshot.active_model == "mock"

    def test_set_current_goal_publishes_goal_changed(self):
        bus = EventBus()
        controller = ExecutiveController(event_bus=bus)
        controller.set_current_goal("Ship Milestone 6")
        assert controller.current_goal == "Ship Milestone 6"
        names = [e.name for e in bus.history()]
        assert Events.GOAL_CHANGED in names

    def test_start_and_complete_task_lifecycle(self):
        bus = EventBus()
        controller = ExecutiveController(event_bus=bus)
        controller.start_task("write_tests", importance=0.8)
        assert controller.state_machine.state == InternalState.EXECUTING
        assert any(item.name == "write_tests" for item in controller.attention.current_focus())

        reflection = controller.complete_task("write_tests", succeeded=True, what_happened="Tests written.")
        assert reflection.succeeded is True
        assert controller.state_machine.state == InternalState.IDLE
        assert not any(item.name == "write_tests" for item in controller.attention.current_focus())

        names = [e.name for e in bus.history()]
        assert Events.TASK_STARTED in names
        assert Events.TASK_COMPLETED in names
        assert Events.REFLECTION_FINISHED in names

    def test_priority_queue_ranks_and_pops_highest_first(self):
        controller = ExecutiveController()
        controller.enqueue("low", importance=0.2)
        controller.enqueue("high", importance=0.9)
        assert controller.priority_queue()[0].name == "high"
        popped = controller.next_in_queue()
        assert popped.name == "high"
        assert controller.next_in_queue().name == "low"
        assert controller.next_in_queue() is None

    def test_interrupt_and_resume_delegate_to_attention(self):
        controller = ExecutiveController()
        controller.attention.focus_on(FocusItem("normal", 0.5))
        controller.interrupt("urgent", importance=1.0)
        assert [i.name for i in controller.attention.current_focus()] == ["urgent"]
        controller.resume()
        assert [i.name for i in controller.attention.current_focus()] == ["normal"]

    def test_decide_scores_confidence_and_updates_self_model(self):
        controller = ExecutiveController()
        assessment = controller.decide(reason="picking a tool", evidence=["docs say so"])
        assert 0.0 <= assessment.confidence <= 1.0
        assert controller.self_model().confidence == assessment.confidence

    def test_build_context_includes_identity_and_working_memory(self):
        controller = ExecutiveController()
        controller.working_memory.put("scratch", "some fact")
        bundle = controller.build_context(conversation=["hello"])
        assert bundle.identity
        assert "some fact" in bundle.working_memory
        assert bundle.conversation == ["hello"]

    def test_health_check_updates_self_model_health_score(self):
        controller = ExecutiveController()
        result = controller.health_check(HealthMetrics())
        assert result.is_healthy is True
        assert controller.self_model().health_score > 0.9

    def test_health_check_detects_sensory_signal_when_unhealthy(self):
        controller = ExecutiveController()
        controller.health_check(HealthMetrics(memory_usage=1.0, task_load=1.0, errors=10, queue_length=50))
        signals = [e.signal for e in controller.sensory.history()]
        assert SensorySignal.HIGH_CPU_LOAD in signals

    def test_running_processes_includes_current_task(self):
        controller = ExecutiveController()
        controller.start_task("some_task")
        names = [p.name for p in controller.running_processes()]
        assert "some_task" in names

    def test_notify_owner_returns_message(self):
        controller = ExecutiveController()
        message = controller.notify_owner("Something needs attention.")
        assert message == "Something needs attention."

    def test_describe_returns_human_readable_summary(self):
        controller = ExecutiveController()
        description = controller.describe()
        assert "MARK" in description


# ---------------------------------------------------------------------------
# Brain integration
# ---------------------------------------------------------------------------

class TestSmartAgentMindIntegration:
    def test_agent_has_mind(self, tmp_path):
        agent = _agent(tmp_path)
        assert isinstance(agent.mind, ExecutiveController)

    def test_mind_providers_reflect_live_agent_state(self, tmp_path):
        agent = _agent(tmp_path)
        agent.mind.sync_self_model()
        snapshot = agent.mind.self_model()
        assert snapshot.skills == agent.skill_engine.list_available()
        assert snapshot.tools == agent.tool_engine.list_available()

    def test_handle_message_return_value_unaffected_by_mind(self, tmp_path):
        """
        Zero-regression check: the Mind must observe, not decide. Compare
        against the exact same fallback message Milestone 2/3 produced.
        """
        agent = _agent(tmp_path)
        response = agent.handle_message("some arbitrary message the agent can't otherwise handle")
        assert response.startswith(f"[{agent.settings.agent_name} placeholder] You said:")

    def test_handle_message_leaves_mind_in_idle_state(self, tmp_path):
        agent = _agent(tmp_path)
        agent.handle_message("hello there")
        assert agent.mind.state_machine.state == InternalState.IDLE

    def test_handle_message_records_a_reflection(self, tmp_path):
        agent = _agent(tmp_path)
        before = len(agent.mind.reflection_engine.list_reflections())
        agent.handle_message("hello there")
        after = len(agent.mind.reflection_engine.list_reflections())
        assert after == before + 1

    def test_handle_message_never_raises_even_if_mind_breaks(self, tmp_path, monkeypatch):
        agent = _agent(tmp_path)

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated Mind failure")

        monkeypatch.setattr(agent.mind.reflection_engine, "reflect", _boom)
        # Must not raise — Mind failures are swallowed defensively.
        response = agent.handle_message("hello there")
        assert isinstance(response, str)

    def test_default_model_id_default_behavior_unchanged(self, tmp_path):
        """Milestone 5's contract must still hold: no auto-loaded model by default."""
        agent = _agent(tmp_path)
        assert agent.model_manager.active_model_id is None
