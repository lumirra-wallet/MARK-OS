"""Tests for _is_conversational_goal() — the intent router in api.py."""

import pytest
from smartagent.server.api import _is_conversational_goal as is_chat


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
    assert is_chat(goal) is True, f"Expected chat for: {goal!r}"


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
    assert is_chat(goal) is False, f"Expected agent for: {goal!r}"
