"""Tests for smartagent.identity.profile — Phase 2 (structured identity)."""

from __future__ import annotations

import pytest

from smartagent.identity.profile import (
    IDENTITY_PROFILE,
    IdentityProfile,
    identity_chat_reply,
    identity_summary_text,
    is_identity_question,
    load_identity_profile,
)


class TestIdentityProfileLoading:
    def test_default_profile_has_sane_fields(self):
        p = IdentityProfile()
        assert p.name == "MARK"
        assert p.is_human is False
        assert len(p.capabilities) > 0
        assert len(p.limitations) > 0

    def test_module_level_profile_loaded_without_raising(self):
        # Import-time load already happened — just assert it produced something usable.
        assert IDENTITY_PROFILE.name
        assert isinstance(IDENTITY_PROFILE.capabilities, tuple)

    def test_missing_canonical_file_falls_back_to_defaults(self, monkeypatch, tmp_path):
        import smartagent.identity.profile as mod
        monkeypatch.setattr(mod, "_PERSONALITY_FILE", tmp_path / "does_not_exist.json")
        profile = load_identity_profile()
        assert profile.name == "MARK"
        assert profile.raw_personality == {}

    def test_as_dict_has_expected_keys(self):
        d = IdentityProfile().as_dict()
        for key in ("name", "type", "purpose", "capabilities", "limitations", "operating_principles"):
            assert key in d


class TestIdentityQuestionDetection:
    @pytest.mark.parametrize("goal", [
        "who are you?",
        "who are you",
        "What are you?",
        "what's your name?",
        "what is your name",
        "are you human?",
        "are you a robot?",
        "are you an ai?",
        "introduce yourself",
        "tell me about yourself",
        "who made you?",
        "who created you",
    ])
    def test_matches_identity_questions(self, goal):
        assert is_identity_question(goal) is True, f"Expected identity match: {goal!r}"

    @pytest.mark.parametrize("goal", [
        "build a Python script",
        "can you generate images?",
        "who are you going to hire",  # contains "who are you" but not the question
        "what are you building today",
        "generate a REST API",
        "",
    ])
    def test_does_not_match_non_identity_goals(self, goal):
        assert is_identity_question(goal) is False, f"Expected no match: {goal!r}"


class TestIdentityReplies:
    def test_chat_reply_mentions_mark_and_is_operating_system(self):
        reply = identity_chat_reply()
        assert "MARK" in reply
        assert "Operating System" in reply or "operating system" in reply.lower()

    def test_chat_reply_is_honest_about_limitations(self):
        reply = identity_chat_reply()
        assert "image" in reply.lower() or "video" in reply.lower()
        assert "human" in reply.lower()

    def test_summary_text_includes_capabilities_and_limitations(self):
        text = identity_summary_text()
        assert "can do" in text.lower()
        assert "can't do" in text.lower()
