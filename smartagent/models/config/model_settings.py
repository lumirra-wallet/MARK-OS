"""
ModelSettings — Milestone 5, Part 8.

Configuration for the Model Framework, following the same philosophy as
`smartagent.config.settings.Settings`: a plain dataclass of defaults, no
I/O, no hardcoded secrets. Kept in `smartagent.models.config` (not merged
into the top-level `Settings`) so `smartagent.config` does not need to
depend on `smartagent.models` — the same reasoning `Settings`'s docstring
already gives for duplicating `memory_categories` instead of importing
them from `smartagent.memory`.

`SmartAgent.__init__` builds one `ModelSettings` from the top-level
`Settings.default_language_model` (so there's still exactly one place a
deployment configures "which model to use") and passes it to
`ModelManager`.

No API keys live here as literal values. `api_keys` is a placeholder dict
for future providers (Part 10) — deployments would populate it from
environment variables/Replit secrets (see `environment-secrets` skill),
never from a hardcoded default.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelSettings:
    """
    Configuration for `ModelManager` and the providers it loads.

    Attributes:
        default_model_id: Id of the provider to load as the active default
            (e.g. `"mock"`). Empty string means "no default" — `ModelManager`
            will not auto-load anything, matching the pre-Milestone-5
            placeholder behavior of never actually generating text until a
            model is loaded explicitly.
        temperature: Sampling temperature passed to providers that support it.
        top_p: Nucleus sampling parameter passed to providers that support it.
        top_k: Top-k sampling parameter passed to providers that support it.
        max_tokens: Maximum tokens to generate in a single `generate()`/`stream()` call.
        streaming_enabled: Whether `ModelManager.generate()` may use `stream()`
            under the hood when a caller asks for incremental output.
        timeout_seconds: How long to wait for a provider call before treating
            it as failed. Not enforced by `MockModelProvider` (it never blocks),
            but real providers should respect it.
        api_keys: Placeholder mapping of provider id -> API key, for future
            cloud providers (Part 10). Always populate from environment
            variables/secrets at runtime — never hardcode a value here.
        local_model_paths: Placeholder mapping of provider id -> filesystem
            path, for future local-weight providers (llama.cpp, LM Studio).
    """

    default_model_id: str = ""
    temperature: float = 0.7
    top_p: float = 1.0
    top_k: int = 40
    max_tokens: int = 1024
    streaming_enabled: bool = True
    timeout_seconds: float = 30.0
    api_keys: dict[str, str] = field(default_factory=dict)
    local_model_paths: dict[str, str] = field(default_factory=dict)

    # Ollama integration (Milestone 9)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_default_model: str = "llama3.1:8b"
    ollama_coding_model: str = "qwen2.5-coder:7b"

    # GitHub Models integration
    github_default_model: str = "gpt-4.1-mini"
    github_coding_model: str = "gpt-4.1"
    github_fallback_model: str = "gpt-4o-mini"

    # Milestone 10 — Streaming, Performance & Optimisation
    warmup_enabled: bool = True
    """Perform a tiny warmup generation when a model loads to keep it resident."""
    cache_prompts: bool = True
    """Cache assembled static prompt context (system prompt, identity, goals)."""
    show_generation_stats: bool = False
    """Print timing / token-count metrics after each streamed response."""
    lazy_model_loading: bool = False
    """Unload the previous model when switching to a new one."""

    def generation_kwargs(self) -> dict[str, float | int | bool]:
        """
        Common generation parameters to forward to a provider's `generate()`/`stream()`.

        Centralizing this avoids every call site re-listing the same four
        keys, and gives `ModelManager` one place to override a subset per-call.
        """
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
        }
