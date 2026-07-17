"""
Tests for smartagent.engineer.agent_loop — the core tool-calling loop.

Focused on ``allow_direct_reply``: when ``run_agent_loop`` is dispatched as a
delegated specialist worker (see ``worker_roles.py`` / ``DevPipeline``), its
own final reply must never stream straight to chat — only MARK's own
executive-composed text should reach the user. All tests mock the model
manager; no network calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from smartagent.engineer.agent_loop import run_agent_loop


def _done_response(content: str):
    msg = MagicMock()
    msg.tool_calls = []
    msg.content    = content
    return msg


def _streamed_texts(event_bus: MagicMock) -> list[str]:
    return [
        c.kwargs.get("text", "") for c in event_bus.publish.call_args_list
        if c.args and c.args[0] == "StreamingToken"
    ]


class TestAllowDirectReply:
    def test_defaults_to_streaming_direct_reply(self, tmp_path):
        """Default behaviour (MARK acting directly) is unchanged."""
        eb = MagicMock()
        mm = MagicMock()
        mm.chat_with_tools.return_value = _done_response("Final answer.")

        result = run_agent_loop("goal", mm, eb, str(tmp_path))

        assert "".join(_streamed_texts(eb)) == "Final answer."
        assert result.final_summary == "Final answer."
        assert result.success is True

    def test_suppresses_direct_reply_when_false(self, tmp_path):
        """A delegated worker's final reply must not reach chat directly."""
        eb = MagicMock()
        mm = MagicMock()
        mm.chat_with_tools.return_value = _done_response("Final answer.")

        result = run_agent_loop(
            "goal", mm, eb, str(tmp_path), allow_direct_reply=False,
        )

        assert _streamed_texts(eb) == []
        # Still captured for MARK's own synthesis to use.
        assert result.final_summary == "Final answer."
        assert result.success is True

    def test_llm_error_message_suppressed_when_false(self, tmp_path):
        eb = MagicMock()
        mm = MagicMock()
        mm.chat_with_tools.side_effect = RuntimeError("model unavailable")

        result = run_agent_loop(
            "goal", mm, eb, str(tmp_path), allow_direct_reply=False,
        )

        assert _streamed_texts(eb) == []
        assert "llm_error" in result.stop_reason

    def test_llm_error_message_streams_when_true(self, tmp_path):
        eb = MagicMock()
        mm = MagicMock()
        mm.chat_with_tools.side_effect = RuntimeError("model unavailable")

        run_agent_loop("goal", mm, eb, str(tmp_path), allow_direct_reply=True)

        assert any("LLM call failed" in t for t in _streamed_texts(eb))
