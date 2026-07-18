"""
MARK system prompt — Milestone 9.

A permanent, identity-defining system prompt injected into every Ollama
conversation.  Centralised here so it is easy to find, version, and update
without hunting through command files.

Import it wherever a full MARK context is assembled:

    from smartagent.models.prompts.mark_system_prompt import MARK_SYSTEM_PROMPT

This is now a thin re-export of the single consolidated identity in
smartagent/identity/mark_identity.py — this file used to define its own,
independent (and contradictory) identity/personality text.
"""

from smartagent.identity.mark_identity import MARK_IDENTITY_CORE

MARK_SYSTEM_PROMPT = MARK_IDENTITY_CORE
