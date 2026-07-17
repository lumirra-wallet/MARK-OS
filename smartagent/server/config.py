"""
smartagent.server.config — single source of truth for all server env vars.

Import from here instead of calling ``os.environ.get(...)`` in individual
server modules.  This keeps the full list visible in one place, documents
expected values, and makes it easy to validate the configuration at startup.

Usage::

    from smartagent.server.config import cfg

    url = cfg.ollama_base_url
    tok = cfg.github_token
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServerConfig:
    """Immutable snapshot of all server configuration values."""

    # ── LLM provider ──────────────────────────────────────────────────────────
    active_provider: str        # "github" | "ollama"
    github_token: str           # GitHub PAT with Models access
    github_default_model: str   # e.g. "gpt-4.1"
    github_coding_model: str    # e.g. "gpt-4.1"

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str        # e.g. "http://localhost:11434"
    ollama_default_model: str   # e.g. "llama3.1:8b"

    # ── Web server ────────────────────────────────────────────────────────────
    session_secret: str
    vite_api_url: str           # forwarded to frontend; empty = same origin

    # ── Feature flags ─────────────────────────────────────────────────────────
    debug: bool
    log_level: str

    @property
    def github_available(self) -> bool:
        return bool(self.github_token)

    @property
    def is_github_active(self) -> bool:
        return self.active_provider == "github"

    @property
    def is_ollama_active(self) -> bool:
        return self.active_provider == "ollama"


def _load() -> ServerConfig:
    return ServerConfig(
        active_provider      = (
            os.environ.get("ACTIVE_PROVIDER", "").strip().lower()
            or ("github" if os.environ.get("GITHUB_TOKEN") else "ollama")
        ),
        github_token         = os.environ.get("GITHUB_TOKEN", ""),
        github_default_model = os.environ.get("GITHUB_DEFAULT_MODEL", "gpt-4.1"),
        github_coding_model  = os.environ.get("GITHUB_CODING_MODEL", "gpt-4.1"),
        ollama_base_url      = os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        ollama_default_model = os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3.1:8b"),
        session_secret       = os.environ.get("SESSION_SECRET", "dev-secret-change-me"),
        vite_api_url         = os.environ.get("VITE_API_URL", ""),
        debug                = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
        log_level            = os.environ.get("LOG_LEVEL", "INFO").upper(),
    )


# Module-level singleton — imported as ``from smartagent.server.config import cfg``
cfg: ServerConfig = _load()
