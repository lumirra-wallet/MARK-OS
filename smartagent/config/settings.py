"""
Settings loader.

Provides a single `Settings` object that the rest of SmartAgent depends on
for configuration values. Real configuration sources (environment
variables, a `.env` file, a YAML/JSON config file, Replit secrets, etc.)
will be wired in later. For now this is a placeholder with sensible
defaults so other modules have something concrete to import against.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Settings:
    """
    Holds all runtime configuration for SmartAgent.

    Attributes:
        agent_name: Display name for the assistant.
        default_language_model: Identifier for the LLM/backend to use.
            Placeholder only — no model is wired up yet.
        memory_backend: Which memory implementation to use
            (e.g. "in_memory", "sqlite", "vector_store"). Placeholder only.
        enabled_tools: Names of tools the agent is allowed to invoke.
            Placeholder only — populated once real tools exist.
        voice_enabled: Whether voice input/output is active.
        automation_enabled: Whether scheduled/background automations run.
    """

    agent_name: str = "SmartAgent"
    default_language_model: str = "placeholder-model"
    memory_backend: str = "in_memory"
    enabled_tools: list[str] = field(default_factory=list)
    voice_enabled: bool = False
    automation_enabled: bool = False

    @classmethod
    def load(cls) -> "Settings":
        """
        Build a `Settings` instance.

        TODO: Read from environment variables / a config file / Replit
        secrets instead of returning hardcoded defaults. Kept simple for
        now so the rest of the project has a stable configuration contract
        to build against.
        """
        return cls()
