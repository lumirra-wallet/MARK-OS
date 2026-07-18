"""
Tests for smartagent.server.reflection — B4 (Reflection Engine).

Covers: real JSON-parsed reflection on a successful chat_stream call,
fallback to the canned strings on LLM error text / malformed JSON /
missing model_manager, and should_ask_user/ask_user_message plumbing.

Not to be confused with tests/test_reflection.py, which covers the
unrelated, pre-existing smartagent.reflection package (Milestone 14's
ExecutionAnalyzer/Critic/LearningStore learning system).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from smartagent.server.reflection import ReflectionResult, reflect_on_run


def _mm_returning(*chunks: str) -> MagicMock:
    mm = MagicMock()
    mm.chat_stream.return_value = iter(chunks)
    return mm


class TestCannedFallback:
    def test_none_model_manager_succeeded(self):
        result = reflect_on_run("goal", "outcome", True, False, None)
        assert result == ReflectionResult(lesson="Run completed successfully.")

    def test_none_model_manager_cancelled(self):
        result = reflect_on_run("goal", "outcome", False, True, None)
        assert result.lesson == "Run was cancelled."
        assert result.should_ask_user is False

    def test_none_model_manager_failed(self):
        result = reflect_on_run("goal", "outcome", False, False, None)
        assert result.lesson == "Run finished with failures — check summary or error."

    def test_none_model_manager_never_calls_chat_stream(self):
        mm = _mm_returning('{"lesson": "should not be reached"}')
        reflect_on_run("goal", "outcome", True, False, None)
        mm.chat_stream.assert_not_called()


class TestLlmReflection:
    def test_valid_json_parsed(self):
        mm = _mm_returning(
            '{"lesson": "Kept the diff small.", '
            '"should_ask_user": false, "ask_user_message": ""}'
        )
        result = reflect_on_run("goal", "outcome", True, False, mm)
        assert result.lesson == "Kept the diff small."
        assert result.should_ask_user is False
        assert result.ask_user_message == ""

    def test_should_ask_user_true(self):
        mm = _mm_returning(
            '{"lesson": "Two viable fixes existed.", '
            '"should_ask_user": true, '
            '"ask_user_message": "Should I use approach A or B?"}'
        )
        result = reflect_on_run("goal", "outcome", False, False, mm)
        assert result.should_ask_user is True
        assert result.ask_user_message == "Should I use approach A or B?"

    def test_streamed_in_multiple_chunks(self):
        mm = _mm_returning('{"lesson": "chun', 'ked lesson"}')
        result = reflect_on_run("goal", "outcome", True, False, mm)
        assert result.lesson == "chunked lesson"

    def test_markdown_fenced_json_handled(self):
        mm = _mm_returning('```json\n{"lesson": "fenced"}\n```')
        result = reflect_on_run("goal", "outcome", True, False, mm)
        assert result.lesson == "fenced"

    def test_empty_lesson_falls_back_to_canned(self):
        mm = _mm_returning('{"lesson": ""}')
        result = reflect_on_run("goal", "outcome", True, False, mm)
        assert result.lesson == "Run completed successfully."


class TestFailureFallsBackToCanned:
    def test_llm_error_text_falls_back(self):
        mm = _mm_returning("NVIDIA API error: rate limited")
        result = reflect_on_run("goal", "outcome", False, False, mm)
        assert result.lesson == "Run finished with failures — check summary or error."
        assert result.should_ask_user is False

    def test_malformed_json_falls_back(self):
        mm = _mm_returning("not valid json at all")
        result = reflect_on_run("goal", "outcome", True, False, mm)
        assert result.lesson == "Run completed successfully."

    def test_chat_stream_raises_falls_back(self):
        mm = MagicMock()
        mm.chat_stream.side_effect = RuntimeError("boom")
        result = reflect_on_run("goal", "outcome", False, True, mm)
        assert result.lesson == "Run was cancelled."
