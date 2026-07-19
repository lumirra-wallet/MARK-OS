"""
response_planner.py — turns classify_intent()'s routing decision into a
plan MARK can explain, with agent.mind genuinely involved in making it.

Two gaps this closes, both found in the Brain Ownership Architecture audit:

1. Decision-making belonged to no one. classify_intent() dispatches with
   zero deliberation from agent.mind — not consulted, not overruled, not
   even aware a decision happened. plan_response() is the seam: every
   response now gets a real ConfidenceAssessment from
   agent.mind.decide(), not just a route label.
2. agent.mind.decide() had zero callers anywhere in the repository —
   real, working code, sitting unused. This is its first live caller.

This is additive, not a replacement: classify_intent() keeps deciding
*what kind of thing* the message is exactly as before (that logic is
correct and tested); plan_response() adds *why*, and gives the Brain a
genuine say via a real confidence score instead of a hardcoded one.
Dispatch in smartagent/server/api.py still keys off intent.route directly —
this doesn't change behavior, only makes the reasoning visible and
real.

Deliberately not named DecisionEngine: that name is already
smartagent/brain/decision_engine.py's, a real, different component
(module-priority ordering). Lives under smartagent/mind/ — MARK's actual
persistent self — rather than smartagent/engineer/ or smartagent/server/,
because deciding what to do with a message is something MARK does, not
something the transport layer or the worker pipeline does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from smartagent.engineer.dev_pipeline import IntentDecision, classify_intent

ResponseAction = Literal[
    "ask_clarification",
    "answer_directly",
    "reason",
    "create_mission",
]


@dataclass(frozen=True)
class ResponsePlan:
    action: ResponseAction
    reasoning: str
    intent: IntentDecision
    confidence: float
    confidence_assessment: Any  # smartagent.mind.confidence.confidence_engine.ConfidenceAssessment


def _evidence_for(intent: IntentDecision) -> list[str]:
    """Only what's actually true about the decision — never fabricated to
    push the score up. classify_intent() doesn't expose which internal
    branch matched, so this stays to what the IntentDecision itself says."""
    evidence = [f"category={intent.category.value}"]
    if intent.complexity is not None:
        evidence.append(f"complexity={intent.complexity.value}")
    return evidence


def _missing_information_for(intent: IntentDecision) -> list[str]:
    if intent.route == "needs_clarification":
        return ["the goal doesn't specify what to change"]
    return []


def _action_and_reasoning(goal: str, intent: IntentDecision) -> tuple[ResponseAction, str]:
    if intent.route == "needs_clarification":
        return (
            "ask_clarification",
            "The goal is real intent, not small talk, but it's too broad to "
            "act on without picking a direction first — asking beats "
            "guessing and burning a mission on the wrong thing.",
        )

    if intent.route == "conversational":
        from smartagent.identity.profile import is_identity_question

        if is_identity_question(goal):
            return (
                "answer_directly",
                "This is a fixed fact about MARK's own identity — retrieved "
                "from his profile, not reasoned about.",
            )
        return (
            "reason",
            "Nothing in the workspace needs to change to answer this — it "
            "can be reasoned about directly, no worker dispatch.",
        )

    scale = "the full worker team" if intent.route == "complex_pipeline" else "a single focused worker"
    return (
        "create_mission",
        f"This needs real changes to the workspace, not just an answer — "
        f"that's mission work, handed to {scale}, never done by MARK directly.",
    )


def plan_response(agent: Any, goal: str, intent: IntentDecision | None = None) -> ResponsePlan:
    """
    Decide what MARK should do about *goal* — and make agent.mind actually
    part of that decision, not just a label attached after the fact.

    agent must expose .mind (a smartagent.mind.executive.executive_controller
    .ExecutiveController) — the persistent agent from
    smartagent.server.api._get_mark_agent() satisfies this. Pass *intent* if
    the caller already has one from classify_intent(goal) — avoids
    reclassifying the same goal twice.
    """
    if intent is None:
        intent = classify_intent(goal)
    action, reasoning = _action_and_reasoning(goal, intent)
    assessment = agent.mind.decide(
        reason=f"route the message: {reasoning}",
        evidence=_evidence_for(intent),
        missing_information=_missing_information_for(intent),
    )
    return ResponsePlan(
        action=action,
        reasoning=reasoning,
        intent=intent,
        confidence=assessment.confidence,
        confidence_assessment=assessment,
    )
