"""
The SmartAgent core class.

This is the orchestrator that ties configuration, memory, models, skills,
and tools together to handle a user's request and produce a response.
Real reasoning/LLM-calling logic is not implemented yet — this module
currently defines the shape of the API (constructor + `run`/
`handle_message`) so the rest of the codebase (entry point, ui, voice,
automation) has a stable contract to build against.
"""

from __future__ import annotations

from smartagent.config.settings import Settings
from smartagent.memory.memory_manager import MemoryManager
from smartagent.models.model_client import ModelClient
from smartagent.skills.skill_registry import SkillRegistry
from smartagent.tools.tool_registry import ToolRegistry


class SmartAgent:
    """
    Central orchestrator for the assistant.

    Responsibilities (to be implemented incrementally):
        - Receive a message/command from a user (text or transcribed voice).
        - Consult `MemoryManager` for relevant context/history.
        - Decide whether a skill or tool should be invoked to fulfill the
          request.
        - Call out to a language model (via `ModelClient`) to reason and
          produce a response.
        - Persist any new information back into memory.
        - Return the response to the caller (ui, voice output, etc.).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = MemoryManager(
            backend=settings.memory_backend,
            vault_path=settings.vault_path,
            categories=settings.memory_categories,
        )
        self.tools = ToolRegistry(enabled_tools=settings.enabled_tools)
        self.skills = SkillRegistry()
        self.model = ModelClient(model_name=settings.default_language_model)

    def handle_message(self, message: str) -> str:
        """
        Process a single user message and return a response.

        Design decision: the brain always checks memory *before*
        considering a model call. If MARK already knows something relevant
        (a prior fact, note, or exchange stored in the vault), there is no
        reason to ask a language model to reproduce it — this keeps
        responses grounded in the owner's own persisted knowledge and
        avoids unnecessary model calls once a real backend exists.

        No model backend is wired up yet, so the "ask the model" branch
        below still falls back to a placeholder echo via `NotImplementedError`.
        """
        # TODO: once skills/tools exist, decide here whether one should
        # handle the message instead of falling through to memory/model.
        memory_hits = self.memory.search(message, limit=3)

        if memory_hits:
            recalled = "; ".join(hit.content for hit in memory_hits)
            response = f"[{self.settings.agent_name}] Here's what I remember: {recalled}"
        else:
            try:
                response = self.model.generate(message)
            except NotImplementedError:
                response = f"[{self.settings.agent_name} placeholder] You said: {message}"

        # Persist this exchange so future messages can find it via
        # `self.memory.search()` — this is what lets memory checks above
        # actually accumulate useful context over time.
        self.memory.remember(message, category="Journal")
        return response

    def run(self) -> None:
        """
        Start the assistant's main interaction loop.

        Placeholder implementation: prints a startup message. This will
        eventually branch into a text REPL (see `smartagent.ui`), a voice
        loop (see `smartagent.voice`), or be driven externally (e.g. by an
        automation trigger).
        """
        print(f"{self.settings.agent_name} is starting up (placeholder run loop).")
        print("Real conversational behavior has not been implemented yet.")
