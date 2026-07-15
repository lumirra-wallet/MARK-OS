"""
Tests for the core `SmartAgent` orchestrator.

Reasoning/tool logic is still a placeholder, but memory is now real
(Memory v1's Markdown vault), so every test here points the agent at an
isolated temporary vault (via `tmp_path`) rather than the project's real
`vault/` directory.
"""

from smartagent.brain.agent import SmartAgent
from smartagent.config.settings import Settings


def _agent(tmp_path):
    settings = Settings.load()
    settings.vault_path = str(tmp_path / "vault")
    return SmartAgent(settings=settings)


def test_agent_initializes_with_default_settings(tmp_path):
    agent = _agent(tmp_path)
    assert agent.settings.agent_name == "SmartAgent"
    assert agent.memory is not None
    assert agent.tools is not None


def test_handle_message_echoes_placeholder_response_when_nothing_remembered(tmp_path):
    agent = _agent(tmp_path)
    response = agent.handle_message("hello")
    assert "hello" in response


def test_handle_message_checks_memory_before_falling_back_to_the_model(tmp_path):
    agent = _agent(tmp_path)
    agent.memory.remember("The user's favorite color is blue.", category="Personal")

    response = agent.handle_message("favorite color")
    assert "blue" in response


def test_handle_message_persists_the_exchange_for_future_recall(tmp_path):
    agent = _agent(tmp_path)
    agent.handle_message("Remember that I like tea.")

    results = agent.memory.search("tea")
    assert len(results) == 1
