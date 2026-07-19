"""Tests for classify_intent() — the Conversation Manager's single decision
point in dev_pipeline.py (replaces the retired _is_conversational_goal in
api.py and is_complex_goal in dev_pipeline.py — see B2 plan note)."""

import pytest
from smartagent.engineer.dev_pipeline import classify_intent


# ── True chat (pure greetings/acknowledgements) ────────────────────────────────

@pytest.mark.parametrize("goal", [
    "hi",
    "hi!",
    "hello",
    "hey",
    "good morning",
    "good evening",
    "how are you",
    "how are you?",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "who are you",
    "what are you",
    "what can you do",
    "yo",
])
def test_is_chat_for_greetings(goal):
    assert classify_intent(goal).route == "conversational", f"Expected chat for: {goal!r}"


# ── False (should route to agent execution) ────────────────────────────────────

@pytest.mark.parametrize("goal", [
    # Audit examples verbatim
    "Can you write to my workspace folder?",
    "BUILD A PYTHON CALCULATOR AND SAVE IT AS TEST.PY",
    "Create hello.py",
    "Read package.json",
    "Rename hello.py to app.py",
    "Run tests",
    "Create Flask API",
    "Commit milestone",
    # Additional real-world requests
    "Can you help me build a React app?",
    "write a function to sort a list",
    "fix the bug in auth.py",
    "build a todo app",
    "create a REST API with Flask",
    "what is in my workspace?",
    "can you write to my workspace",
    "please write main.py",
    "show me the directory structure",
    "run pytest",
    "git status",
    "commit all my changes",
    "add an endpoint to the API",
    "refactor the auth module",
    "debug the test failures",
    "install requests",
    "make a calculator in python",
    "save it as test.py",
    "create hello.py with hello world",
    "write a hello world script",
    "add error handling to main.py",
    "update requirements.txt",
])
def test_is_agent_for_code_tasks(goal):
    assert classify_intent(goal).route != "conversational", f"Expected agent for: {goal!r}"


# ── Regression: ambiguous, non-action phrasing must stay conversational ───────
#
# The bug B2 fixes: the old _is_conversational_goal defaulted anything that
# fell through its greeting/keyword/short-message checks to the AGENT path —
# so an open question with no action keyword and more than 3 words (like
# "what do you think?") silently triggered a tool-calling agent run instead
# of a plain conversational reply.

@pytest.mark.parametrize("goal", [
    "what do you think?",
    "what do you think about this approach?",
    "should we take a break?",
    "do you have any thoughts on this?",
    "is this a good idea?",
    "how does this look to you?",
])
def test_ambiguous_questions_stay_conversational(goal):
    assert classify_intent(goal).route == "conversational", f"Expected chat for: {goal!r}"


# ── Capability questions about MARK itself stay conversational ────────────────
#
# "can you generate images?" contains "generate" — a generic action verb
# that would otherwise force the agent/engineering path regardless of
# phrasing. But this is a yes/no question about MARK's own ability, not a
# work request, and answering it should never involve tool calls (searching
# the workspace, reading files) — see the live incident this regression test
# is named for: MARK tried to read a hallucinated file path and searched the
# codebase for "image generation" instead of just answering from its own
# identity.

@pytest.mark.parametrize("goal", [
    "can you generate images?",
    "can you generate an image?",
    "are you able to browse the internet?",
    "do you support voice?",
    "does mark support voice input?",
    "will you be able to make phone calls?",
    "can you make videos?",
    "could you write music?",
])
def test_capability_questions_stay_conversational(goal):
    decision = classify_intent(goal)
    assert decision.route == "conversational", f"Expected chat for: {goal!r}"


# ── Same phrasing shape, but a real request — must still route to the agent ───
#
# The capability-question fix must not swallow genuine work requests that
# happen to be phrased as "can/could/are/do you ...?" — distinguished by a
# concrete deliverable (a file, or a code/project-domain noun) or a
# "for me" / "help" signal.

@pytest.mark.parametrize("goal", [
    "can you generate a REST API?",
    "can you fix app.py?",
    "could you help me build a login page?",
    "can you create a Flask app for me?",
    "are you able to write main.py?",
    "do you support building a React frontend?",
])
def test_capability_shaped_work_requests_still_route_to_agent(goal):
    decision = classify_intent(goal)
    assert decision.route != "conversational", f"Expected agent for: {goal!r}"


# ── Vague self-improvement goals ask for clarification, not a plan ────────────
#
# "Improve yourself" is real intent, not a chat question — but it's too
# broad to hand a worker without guessing what "improve" means. Must not
# land in "conversational" (a generic chat reply, no options offered) or
# silently fall through to "simple_agent"/"complex_pipeline" (auto-starts a
# pipeline against a guess) — it gets its own route.

@pytest.mark.parametrize("goal", [
    "improve yourself",
    "Improve MARK",
    "make yourself better",
    "upgrade yourself",
    "can you become smarter",
    "self-improve",
    "optimize yourself",
])
def test_vague_self_improvement_needs_clarification(goal):
    decision = classify_intent(goal)
    assert decision.route == "needs_clarification", f"Expected clarification for: {goal!r}"
    assert len(decision.clarification_options) > 0


@pytest.mark.parametrize("goal", [
    "improve the login page",
    "improve app.py",
    "improve error handling in the API",
    "make the website better",
])
def test_concrete_improvement_requests_do_not_need_clarification(goal):
    decision = classify_intent(goal)
    assert decision.route != "needs_clarification", f"Expected normal routing for: {goal!r}"
