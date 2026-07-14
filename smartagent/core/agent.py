"""
The SmartAgent core class.

This is the orchestrator that ties configuration, memory, and tools
together to handle a user's request and produce a response. Real
reasoning/LLM-calling logic is not implemented yet — this module currently
defines the shape of the API (constructor + `run`/`handle_message`) so the
rest of the codebase (CLI entry point, voice interface, automation jobs)
has a stable contract to build against.
"""

from __future__ import annotations

from smartagent.config.settings import Settings
from smartagent.memory.memory_manager import MemoryManager
from smartagent.tools.tool_registry import ToolRegistry


class SmartAgent:
    """
    Central orchestrator for the assistant.

    Responsibilities (to be implemented incrementally):
        - Receive a message/command from a user (text or transcribed voice).
        - Consult `MemoryManager` for relevant context/history.
        - Decide whether a `Tool` should be invoked to fulfill the request.
        - Call out to a language model to reason and produce a response.
        - Persist any new information back into memory.
        - Return the response to the caller (CLI, voice output, etc.).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.memory = MemoryManager(backend=settings.memory_backend)
        self.tools = ToolRegistry(enabled_tools=settings.enabled_tools)

    def handle_message(self, message: str) -> str:
        """
        Process a single user message and return a response.

        Placeholder implementation: echoes the message back. Will later
        route through memory retrieval, tool selection, and a language
        model call.
        """
        # TODO: retrieve relevant context via self.memory
        # TODO: decide if a tool call (self.tools) is needed
        # TODO: call the configured language model to generate a reply
        # TODO: store the exchange back into memory
        return f"[{self.settings.agent_name} placeholder] You said: {message}"

    def run(self) -> None:
        """
        Start the assistant's main interaction loop.

        Placeholder implementation: prints a startup message. This will
        eventually branch into a text REPL, a voice loop (see
        `smartagent.voice`), or be driven externally (e.g. by an
        automation trigger or a future web/API front-end).
        """
        print(f"{self.settings.agent_name} is starting up (placeholder run loop).")
        print("Real conversational behavior has not been implemented yet.")
