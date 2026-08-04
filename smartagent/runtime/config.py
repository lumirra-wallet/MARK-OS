"""
config.py — Typed, validated configuration for Elena's Runtime.

All configuration is read from environment variables (or a .env file via
python-dotenv).  No raw ``os.environ`` calls are scattered elsewhere in the
runtime; every consumer reads from ``Config`` instead.

Usage
─────
    cfg = Config.load()              # reads env once, caches the instance
    cfg = Config.load(reload=True)   # force re-read (useful in tests)

    cfg.server_port                  # int
    cfg.active_provider              # str  e.g. "ollama"
    cfg.ollama_host                  # str
    cfg.google_live_api_key          # str (empty = disabled)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# Load .env if present — non-fatal if the file does not exist.
try:
    from dotenv import load_dotenv  # type: ignore[import]
    load_dotenv(override=False)     # env vars already set take priority
except ImportError:
    pass                            # python-dotenv is optional

_instance: Optional["Config"] = None


@dataclass(frozen=True)
class Config:
    """
    Immutable snapshot of Elena's runtime configuration.

    All values come from environment variables.  Defaults are set here so
    the runtime works out-of-the-box without a .env file.
    """

    # ── Server ────────────────────────────────────────────────────────────────
    server_port:    int  = 18949
    server_host:    str  = "0.0.0.0"
    session_secret: str  = "change-me"

    # ── Active reasoning provider ─────────────────────────────────────────────
    # Options: ollama | github | nvidia | openai | anthropic | gemini
    active_provider: str = "ollama"

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_host:  str = "http://localhost:11434"
    mark_model:   str = "llama3.2:3b"

    # ── NVIDIA NIM ────────────────────────────────────────────────────────────
    nvidia_api_key: str = ""

    # ── GitHub Models ─────────────────────────────────────────────────────────
    github_token: str = ""

    # ── Google Gemini Live ────────────────────────────────────────────────────
    google_live_api_key:  str = ""
    google_live_model:    str = "gemini-2.0-flash-live-001"
    google_project_id:    str = ""
    google_live_location: str = "us-central1"
    voice_name:           str = "Aoede"

    # ── LiveKit ───────────────────────────────────────────────────────────────
    livekit_url:        str = "ws://localhost:7880"
    livekit_api_key:    str = "devkey"
    livekit_api_secret: str = "secret"

    # ── Database ──────────────────────────────────────────────────────────────
    database_provider: str = "sqlite"
    mongodb_uri:       str = ""

    # ── Voice provider (runtime-switchable, not an env var) ──────────────────
    # This is the *default* — individual sessions may override it.
    default_voice_provider: str = "local"   # "local" | "gemini" | "livekit"

    # ── Feature flags ─────────────────────────────────────────────────────────
    streaming_enabled: bool = True
    voice_always_active: bool = True

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def gemini_live_available(self) -> bool:
        """True when GOOGLE_LIVE_API_KEY is set."""
        return bool(self.google_live_api_key.strip())

    @property
    def nvidia_available(self) -> bool:
        return bool(self.nvidia_api_key.strip())

    @property
    def github_available(self) -> bool:
        return bool(self.github_token.strip())

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, *, reload: bool = False) -> "Config":
        """
        Return the singleton Config instance.

        On first call (or when ``reload=True``) all environment variables are
        read and the instance is frozen.  Subsequent calls return the cached
        instance with no I/O.
        """
        global _instance
        if _instance is None or reload:
            _instance = cls._from_env()
        return _instance

    @classmethod
    def _from_env(cls) -> "Config":
        def _str(key: str, default: str = "") -> str:
            return os.environ.get(key, default).strip()

        def _int(key: str, default: int) -> int:
            raw = os.environ.get(key, "").strip()
            try:
                return int(raw)
            except (ValueError, TypeError):
                return default

        def _bool(key: str, default: bool) -> bool:
            raw = os.environ.get(key, "").strip().lower()
            if raw in ("1", "true", "yes", "on"):
                return True
            if raw in ("0", "false", "no", "off"):
                return False
            return default

        return cls(
            server_port=_int("SERVER_PORT", 18949),
            server_host=_str("SERVER_HOST", "0.0.0.0"),
            session_secret=_str("SESSION_SECRET", "change-me"),
            active_provider=_str("ACTIVE_PROVIDER", "ollama"),
            ollama_host=_str("OLLAMA_HOST", "http://localhost:11434"),
            mark_model=_str("MARK_MODEL", "llama3.2:3b"),
            nvidia_api_key=_str("NVIDIA_API_KEY"),
            github_token=_str("GITHUB_TOKEN"),
            google_live_api_key=_str("GOOGLE_LIVE_API_KEY"),
            google_live_model=_str("GOOGLE_LIVE_MODEL", "gemini-2.0-flash-live-001"),
            google_project_id=_str("GOOGLE_PROJECT_ID"),
            google_live_location=_str("GOOGLE_LIVE_LOCATION", "us-central1"),
            voice_name=_str("VOICE_NAME", "Aoede"),
            livekit_url=_str("LIVEKIT_URL", "ws://localhost:7880"),
            livekit_api_key=_str("LIVEKIT_API_KEY", "devkey"),
            livekit_api_secret=_str("LIVEKIT_API_SECRET", "secret"),
            database_provider=_str("DATABASE_PROVIDER", "sqlite"),
            mongodb_uri=_str("MONGODB_URI"),
            default_voice_provider=_str("DEFAULT_VOICE_PROVIDER", "local"),
            streaming_enabled=_bool("STREAMING_ENABLED", True),
            voice_always_active=_bool("VOICE_ALWAYS_ACTIVE", True),
        )
