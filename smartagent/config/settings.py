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
            Placeholder only — no model is wired up yet. Consumed by the
            legacy `ModelClient` (kept for backward compatibility).
        default_model_id: Id of the Model Framework v1 provider (see
            `smartagent.models.registry.model_registry.ModelRegistry`) to
            treat as the default in `ModelManager`. Empty string (the
            default) means no provider auto-loads — `ModelManager.generate()`
            raises `NoActiveModelError` until a model is explicitly loaded/
            switched to, matching the pre-Milestone-5 "model always reports
            not implemented" behavior. Set to `"mock"` to exercise the real
            (deterministic) `MockModelProvider` end-to-end.
        memory_backend: Which memory implementation to use. Memory v1 only
            implements "markdown_vault" (a persistent Markdown file vault,
            see `smartagent.memory`); other values are accepted but fall
            back to it with a warning.
        vault_path: Directory on disk where the memory vault lives. Kept
            configurable (rather than hardcoded) so tests and deployments
            can relocate it without code changes.
        memory_categories: Category subfolders to ensure exist in the
            vault. Mirrors `smartagent.memory.vault.DEFAULT_CATEGORIES` —
            duplicated here (rather than imported) to keep `config` free of
            a dependency on `memory`.
        enabled_tools: Names of tools the agent is allowed to invoke.
            Placeholder only — populated once real tools exist.
        voice_enabled: Whether voice input/output is active.
        automation_enabled: Whether scheduled/background automations run.
        granted_permissions: Permission values (see
            `smartagent.skills.permissions.Permission`) granted to skills
            system-wide. Per Milestone 3's permission model, nothing is
            granted automatically — this defaults to only
            `read_memory`/`write_memory`, the minimum the first-party
            built-in skills need. Every other permission (network access,
            system commands, automation, file access, running tools)
            starts denied until explicitly added here.
    """

    agent_name: str = "SmartAgent"
    default_language_model: str = "placeholder-model"
    default_model_id: str = ""
    memory_backend: str = "markdown_vault"
    vault_path: str = "vault"
    memory_categories: list[str] = field(
        default_factory=lambda: [
            "Personal",
            "Business",
            "Projects",
            "Knowledge",
            "Research",
            "Journal",
            "Archive",
        ]
    )
    enabled_tools: list[str] = field(default_factory=list)
    workspace_path: str = "."
    knowledge_path: str = "knowledge"
    workspaces_path: str = "workspaces"   # Milestone 15 — workspace root directory
    # Ollama integration (Milestone 9)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_default_model: str = "llama3.1:8b"
    ollama_coding_model: str = "qwen2.5-coder:7b"

    # LLM provider abstraction (GitHub Models / Ollama)
    active_provider: str = ""   # read from ACTIVE_PROVIDER env var at runtime
    github_default_model: str = "gpt-4.1-mini"
    github_coding_model: str = "gpt-4.1"
    github_fallback_model: str = "gpt-4o-mini"

    voice_enabled: bool = False
    automation_enabled: bool = False
    granted_permissions: list[str] = field(default_factory=lambda: ["read_memory", "write_memory"])
    # Milestone 13 — Parallel Executive Engine
    max_parallel_workers: int = 4

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
