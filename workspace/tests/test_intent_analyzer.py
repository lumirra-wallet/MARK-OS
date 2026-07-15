"""Tests for the rule-based `IntentAnalyzer`."""

from smartagent.brain.intent_analyzer import Intent, IntentAnalyzer


def test_classifies_memory_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("Remember that I like tea.") == Intent.MEMORY


def test_classifies_research_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("Please research the history of Rome.") == Intent.RESEARCH


def test_classifies_planning_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("What's my goal for this quarter?") == Intent.PLANNING


def test_classifies_voice_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("Please transcribe this voice message.") == Intent.VOICE


def test_classifies_vision_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("What do you see in this image?") == Intent.VISION


def test_classifies_automation_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("Please automate my morning report.") == Intent.AUTOMATION


def test_classifies_tool_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("Can you calculate this for me?") == Intent.TOOL


def test_classifies_skill_intent():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("skill: summarize-notes") == Intent.SKILL


def test_unmatched_message_is_unknown():
    analyzer = IntentAnalyzer()
    assert analyzer.analyze("Good morning!") == Intent.UNKNOWN
