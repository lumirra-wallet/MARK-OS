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
