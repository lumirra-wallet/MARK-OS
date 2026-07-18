"""
reflection.py — B4 Reflection Engine.

Real per-run evaluation via one short, quiet LLM completion, replacing the
previous hardcoded 3-string canned reflection at api.py's post-run hook
(api.py:615-632). Never touches the chat stream or event_bus directly —
this is MARK's private evaluation of its own run, not something spoken to
the user (that's what ask_user_message is for, surfaced separately by the
caller as a normal chat line). Wrapped so any failure (LLM unavailable,
malformed JSON) falls back to the same canned strings the old code used —
the same optional-phase pattern as DevPipeline's Security/Docs checks in
dev_pipeline.py.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from smartagent.identity.mark_identity import MARK_IDENTITY_CORE
from smartagent.llm.factory import is_llm_error_text

logger = logging.getLogger(__name__)

_REFLECTION_ADDENDUM = """\
You just supervised a piece of engineering work and are reflecting \
privately on how it went — this is your own internal evaluation, not a \
message to the user. Given the goal and outcome below, reply with ONLY a \
JSON object with exactly these keys, no prose outside the JSON:
{"lesson": "<one sentence on what went well or should change next time>",
 "should_ask_user": <true or false>,
 "ask_user_message": "<a short question for the user, or empty string>"}
Set should_ask_user to true only when the outcome is genuinely ambiguous \
and a human decision is needed — not for routine successes or failures \
with an obvious fix.
"""


@dataclass
class ReflectionResult:
    lesson: str
    should_ask_user: bool = False
    ask_user_message: str = ""


def _canned_result(succeeded: bool, cancelled: bool) -> ReflectionResult:
    if succeeded:
        lesson = "Run completed successfully."
    elif cancelled:
        lesson = "Run was cancelled."
    else:
        lesson = "Run finished with failures — check summary or error."
    return ReflectionResult(lesson=lesson)


def reflect_on_run(
    goal: str,
    outcome_summary: str,
    succeeded: bool,
    cancelled: bool,
    model_manager: Any | None,
) -> ReflectionResult:
    """
    One short, quiet LLM completion evaluating a just-finished run.

    Must be called from a worker thread (``asyncio.to_thread``) — same
    constraint as ``_stream_llm_response``, since ``chat_stream`` is a
    blocking iterator. Never raises: falls back to the same canned lesson
    text the post-run hook used before this existed. *model_manager* may be
    ``None`` (e.g. agent init itself failed before a run ever started) —
    that goes straight to the fallback with no LLM attempt.
    """
    fallback = _canned_result(succeeded, cancelled)
    if model_manager is None:
        return fallback
    try:
        messages = [
            {"role": "system", "content": f"{MARK_IDENTITY_CORE}\n{_REFLECTION_ADDENDUM}"},
            {
                "role": "user",
                "content": (
                    f"Goal: {goal[:300]}\n"
                    f"Succeeded: {succeeded}\n"
                    f"Outcome: {outcome_summary[:500] or '(no summary)'}"
                ),
            },
        ]
        chunks: list[str] = []
        for chunk in model_manager.chat_stream(messages, max_tokens=200):
            if chunk and is_llm_error_text(chunk):
                raise RuntimeError(chunk)
            if chunk:
                chunks.append(chunk)
        text = "".join(chunks).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text[:4].lower() == "json":
                text = text[4:].strip()
        data = json.loads(text)
        lesson = str(data.get("lesson") or "").strip() or fallback.lesson
        return ReflectionResult(
            lesson=lesson,
            should_ask_user=bool(data.get("should_ask_user", False)),
            ask_user_message=str(data.get("ask_user_message") or "").strip(),
        )
    except Exception as exc:
        logger.debug("reflect_on_run: LLM reflection unavailable (%s) — using fallback", exc)
        return fallback
