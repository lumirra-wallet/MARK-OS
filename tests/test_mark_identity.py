"""
Tests for smartagent.identity.mark_identity — the consolidated identity
module all chat-facing prompts import from.

The core regression this guards: MARK's identity must never re-drift back
to "an autonomous AI software engineer" / "an AI software engineering
assistant" / "a coding agent" — the exact framing docs/mark-operating-
system.md and SMARTAGENT.md both explicitly reject in favor of "MARK is an
AI Operating System."
"""

from __future__ import annotations

from smartagent.identity import mark_identity
from smartagent.identity.mark_identity import (
    build_system_prompt,
    CHAT_FALLBACK_TEXT,
    CHAT_SURFACE_NOTES,
    EXECUTIVE_SURFACE_NOTES,
    IDLE_SURFACE_NOTES,
    MARK_IDENTITY_CORE,
    OPENING_SURFACE_NOTES,
    PLAN_SURFACE_NOTES,
    WORKER_REPORTING_CONTRACT,
)

_BANNED_PHRASES = (
    "autonomous ai software engineer",
    "ai software engineering assistant",
)

# Every constant that ends up in an outbound prompt or fallback string —
# extend this list when a new chat-facing surface is added.
_ALL_PROMPT_CONSTANTS = {
    "MARK_IDENTITY_CORE": MARK_IDENTITY_CORE,
    "WORKER_REPORTING_CONTRACT": WORKER_REPORTING_CONTRACT,
    "CHAT_SURFACE_NOTES": CHAT_SURFACE_NOTES,
    "OPENING_SURFACE_NOTES": OPENING_SURFACE_NOTES,
    "IDLE_SURFACE_NOTES": IDLE_SURFACE_NOTES,
    "PLAN_SURFACE_NOTES": PLAN_SURFACE_NOTES,
    "EXECUTIVE_SURFACE_NOTES": EXECUTIVE_SURFACE_NOTES,
    "CHAT_FALLBACK_TEXT": CHAT_FALLBACK_TEXT,
}


class TestBannedPhrases:
    def test_no_prompt_constant_contains_a_banned_phrase(self):
        for name, text in _ALL_PROMPT_CONSTANTS.items():
            lower = text.lower()
            for banned in _BANNED_PHRASES:
                assert banned not in lower, (
                    f"{name} regressed to banned framing: {banned!r}"
                )

    def test_composed_system_prompts_have_no_banned_phrase(self):
        for surface_notes in (
            CHAT_SURFACE_NOTES, OPENING_SURFACE_NOTES,
            IDLE_SURFACE_NOTES, PLAN_SURFACE_NOTES, EXECUTIVE_SURFACE_NOTES,
        ):
            composed = build_system_prompt(surface_notes).lower()
            for banned in _BANNED_PHRASES:
                assert banned not in composed


class TestIdentityCore:
    def test_declares_operating_system_not_coding_agent(self):
        assert "AI Operating System" in MARK_IDENTITY_CORE
        assert "not a coding agent" in MARK_IDENTITY_CORE.lower()

    def test_never_reveals_underlying_model_or_provider(self):
        lower = MARK_IDENTITY_CORE.lower()
        assert "if pressed" in lower

    def test_build_system_prompt_prepends_identity_core(self):
        composed = build_system_prompt(CHAT_SURFACE_NOTES)
        assert composed.startswith(MARK_IDENTITY_CORE)
        assert CHAT_SURFACE_NOTES in composed


class TestWorkerReportingContract:
    def test_states_mark_is_the_only_voice(self):
        assert "MARK is the only one" in WORKER_REPORTING_CONTRACT

    def test_used_by_every_worker_role(self):
        from smartagent.engineer.worker_roles import ALL_ROLES
        for role in ALL_ROLES:
            assert WORKER_REPORTING_CONTRACT in role.prompt, (
                f"{role.name}'s prompt is missing the reporting contract"
            )
