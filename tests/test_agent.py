"""
Tests for the core `SmartAgent` orchestrator.

These currently assert against the placeholder behavior (echoing input)
so they will need updating once real reasoning/tool/memory logic replaces
the placeholder in `smartagent.brain.agent`.
"""

from smartagent.brain.agent import SmartAgent
from smartagent.config.settings import Settings


def test_agent_initializes_with_default_settings():
    agent = SmartAgent(settings=Settings.load())
    assert agent.settings.agent_name == "SmartAgent"
    assert agent.memory is not None
    assert agent.tools is not None


def test_handle_message_echoes_placeholder_response():
    agent = SmartAgent(settings=Settings.load())
    response = agent.handle_message("hello")
    assert "hello" in response
