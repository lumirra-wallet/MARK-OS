"""
Elina Brain Integration Bridge.

This module provides the unified interface between the Gemini Live streaming
voice layer and the underlying Elina / SmartAgent operating system.

Gemini Live calls these methods whenever memory, reasoning, or tool execution
is needed. Gemini Live NEVER executes tools directly — it requests execution
through Elina.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

logger = logging.getLogger("smartagent.brain.elina_bridge")


class ElinaMemoryBridge:
    """Memory interface exposed to voice providers."""

    def __init__(self, agent: SmartAgent) -> None:
        self._agent = agent

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search Elina's memory vault for relevant context."""
        logger.info(f"🔍 [Elina.memory.search] Query: '{query}'")
        try:
            results = self._agent.memory.search(query, limit=top_k)
            return [
                {
                    "content": getattr(r, "content", str(r)),
                    "category": getattr(r, "category", "General"),
                    "score": getattr(r, "score", 1.0),
                }
                for r in results
            ]
        except Exception as exc:
            logger.error(f"Error searching memory: {exc}", exc_info=True)
            return [{"error": str(exc)}]

    def store(self, content: str, category: str = "Journal") -> str:
        """Store a new entry in Elina's memory vault."""
        logger.info(f"💾 [Elina.memory.store] Category: '{category}', Content: '{content[:50]}...'")
        try:
            self._agent.memory.remember(content, category=category)
            return f"Memory stored in {category}."
        except Exception as exc:
            logger.error(f"Error storing memory: {exc}", exc_info=True)
            return f"Failed to store memory: {exc}"


class ElinaBridge:
    """
    Core Elina Operating System interface.
    Exposes high-level OS methods to Gemini Live.
    """

    def __init__(self, agent: Optional["SmartAgent"] = None) -> None:
        if agent is None:
            # Lazy import to avoid the agent.py ↔ voice package import cycle.
            from smartagent.brain.agent import SmartAgent
            from smartagent.config.settings import Settings
            agent = SmartAgent(settings=Settings.load())
        self.agent = agent
        self.memory = ElinaMemoryBridge(self.agent)

    def process(self, text: str) -> str:
        """Process a text command or query through Elina's full brain router."""
        logger.info(f"🧠 [Elina.process] Input: '{text}'")
        response = self.agent.handle_message(text)
        logger.info(f"🧠 [Elina.process] Response: '{response[:80]}...'")
        return response

    def reason(self, prompt: str) -> str:
        """Delegate a complex reasoning step to Elina's model manager."""
        logger.info(f"💡 [Elina.reason] Prompt: '{prompt[:50]}...'")
        try:
            if hasattr(self.agent.model_manager, "generate"):
                res = self.agent.model_manager.generate(prompt)
                return str(res)
            return self.process(prompt)
        except Exception as exc:
            logger.warning(f"Reasoning fallback to process(): {exc}")
            return self.process(prompt)

    def execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """
        Execute an Elina tool securely.
        Gemini Live streams tool requests here; Elina executes and returns the result.
        """
        logger.info(f"⚙️ [Elina.execute_tool] Executing '{tool_name}' with args: {tool_args}")
        try:
            # Handle special memory tools directly if passed as tool name
            if tool_name == "search_memory":
                return self.memory.search(tool_args.get("query", ""), top_k=tool_args.get("top_k", 5))
            elif tool_name == "store_memory":
                return self.memory.store(tool_args.get("content", ""), category=tool_args.get("category", "Journal"))
            elif tool_name == "process_command":
                return self.process(tool_args.get("command", ""))

            # Any other tool: per the owner's architecture, Gemini does not
            # pick MARK's specific tools — it hands intent to MARK's brain,
            # which plans and executes. Route through the message handler.
            return self.process(f"{tool_name}: {tool_args}")
        except Exception as exc:
            logger.error(f"Error executing tool '{tool_name}': {exc}", exc_info=True)
            return {"error": f"Tool execution failed: {str(exc)}"}

    def get_tool_declarations(self) -> List[Dict[str, Any]]:
        """Return tool declarations for Gemini Live function calling."""
        return [
            {
                "name": "search_memory",
                "description": "Search Elina's persistent memory vault for past facts, preferences, knowledge, or user details.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "The search query string."},
                        "top_k": {"type": "INTEGER", "description": "Number of results to retrieve (default 5)."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "store_memory",
                "description": "Save an important fact, note, task, or user preference into Elina's memory vault.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "content": {"type": "STRING", "description": "The information to remember."},
                        "category": {
                            "type": "STRING",
                            "description": "Memory category (e.g. Personal, Business, Projects, Knowledge, Journal).",
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "process_command",
                "description": "Delegate a complex system command, automation, research task, or code request to Elina's full OS brain.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "command": {"type": "STRING", "description": "The instruction or command to execute."},
                    },
                    "required": ["command"],
                },
            },
        ]


# Convenient alias for Elina OS
Elina = ElinaBridge
