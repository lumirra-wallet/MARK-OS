"""Tests for `ActionResult`, the common return type every Brain module uses."""

from smartagent.brain.action_result import ActionResult


def test_action_result_defaults():
    result = ActionResult(success=True, message="ok")
    assert result.data is None
    assert result.source == ""
    assert result.execution_time == 0.0
    assert result.confidence == 0.0


def test_action_result_holds_all_fields():
    result = ActionResult(
        success=True,
        message="Here's what I remember: blue",
        data=["entry"],
        source="memory",
        execution_time=0.01,
        confidence=0.8,
    )
    assert result.success is True
    assert result.message == "Here's what I remember: blue"
    assert result.data == ["entry"]
    assert result.source == "memory"
    assert result.execution_time == 0.01
    assert result.confidence == 0.8
