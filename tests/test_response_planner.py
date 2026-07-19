"""Tests for smartagent.mind.response_planner — the seam between
classify_intent() (what kind of message is this) and agent.mind (does the
Brain actually get a say). See response_planner.py's module docstring for
the two gaps this closes: no deliberation after classify_intent(), and
agent.mind.decide() having zero callers anywhere in the repo."""

from __future__ import annotations

from types import SimpleNamespace

from smartagent.mind.executive.executive_controller import ExecutiveController
from smartagent.mind.response_planner import plan_response


def _agent() -> SimpleNamespace:
    return SimpleNamespace(mind=ExecutiveController())


class TestActionMapping:
    def test_vague_self_improvement_asks_for_clarification(self):
        plan = plan_response(_agent(), "improve yourself")
        assert plan.action == "ask_clarification"
        assert plan.reasoning

    def test_identity_questions_answer_directly(self):
        plan = plan_response(_agent(), "who are you?")
        assert plan.action == "answer_directly"

    def test_ordinary_chat_reasons(self):
        plan = plan_response(_agent(), "what do you think about this approach?")
        assert plan.action == "reason"

    def test_work_requests_create_a_mission(self):
        plan = plan_response(_agent(), "Create hello.py")
        assert plan.action == "create_mission"

    def test_large_work_requests_also_create_a_mission(self):
        plan = plan_response(_agent(), "build a full-stack todo app with tests")
        assert plan.action == "create_mission"


class TestMindInvolvement:
    def test_agent_mind_decide_actually_gets_called(self):
        """The whole point: agent.mind.decide() must be a real call, not
        bypassed — confirmed by checking its confidence history grew."""
        agent = _agent()
        before = len(agent.mind.confidence_engine.history())
        plan_response(agent, "Create hello.py")
        after = len(agent.mind.confidence_engine.history())
        assert after == before + 1

    def test_confidence_is_a_real_score_not_hardcoded(self):
        agent = _agent()
        plan = plan_response(agent, "Create hello.py")
        assert 0.0 <= plan.confidence <= 1.0
        assert plan.confidence_assessment is agent.mind.confidence_engine.latest()

    def test_needs_clarification_scores_lower_confidence_than_a_clear_request(self):
        """Missing information is a real penalty in ConfidenceEngine — a
        vague goal should score lower than a concrete one, not the same."""
        agent = _agent()
        vague = plan_response(agent, "improve yourself")
        clear = plan_response(agent, "Create hello.py")
        assert vague.confidence < clear.confidence

    def test_self_model_confidence_updates_after_deciding(self):
        agent = _agent()
        plan_response(agent, "Create hello.py")
        assert agent.mind.self_model().confidence == agent.mind.confidence_engine.latest().confidence


class TestHonestEvidence:
    def test_evidence_never_invents_specifics_classify_intent_does_not_expose(self):
        agent = _agent()
        plan = plan_response(agent, "Create hello.py")
        for item in plan.confidence_assessment.evidence:
            assert item.startswith("category=") or item.startswith("complexity=")

    def test_missing_information_only_set_for_clarification(self):
        agent = _agent()
        clear_plan = plan_response(agent, "Create hello.py")
        assert clear_plan.confidence_assessment.missing_information == []

        vague_plan = plan_response(_agent(), "improve yourself")
        assert vague_plan.confidence_assessment.missing_information != []


class TestPlanCarriesIntent:
    def test_plan_intent_matches_classify_intent_directly(self):
        from smartagent.engineer.dev_pipeline import classify_intent
        goal = "Create hello.py"
        plan = plan_response(_agent(), goal)
        assert plan.intent == classify_intent(goal)

    def test_precomputed_intent_is_reused_not_reclassified(self):
        """Callers that already ran classify_intent() (like api.py) can pass
        it straight through — avoids classifying the same goal twice."""
        from smartagent.engineer.dev_pipeline import classify_intent
        goal = "Create hello.py"
        intent = classify_intent(goal)
        plan = plan_response(_agent(), goal, intent)
        assert plan.intent is intent
