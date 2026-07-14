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
        self.memory = MemoryManager(backend=settings.memory_backend)
        self.tools = ToolRegistry(enabled_tools=settings.enabled_tools)
        self.skills = SkillRegistry()
        self.model = ModelClient(model_name=settings.default_language_model)

    def handle_message(self, message: str) -> str:
        """
        Process a single user message and return a response.

        Placeholder implementation: echoes the message back. Will later
        route through memory retrieval, skill/tool selection, and a
        language model call via `self.model`.
        """
        # TODO: retrieve relevant context via self.memory
        # TODO: decide if a skill (self.skills) or tool (self.tools) call is needed
        # TODO: call self.model to generate a reply
        # TODO: store the exchange back into memory
        return f"[{self.settings.agent_name} placeholder] You said: {message}"

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
