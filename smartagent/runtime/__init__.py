"""
runtime/ — Elena's Runtime Core.

The Runtime is Elena.  Everything else is a service she uses.

Ownership map
─────────────
Runtime OWNS:
  Session          — conversation lifecycle and turn tracking
  Memory           — working + long-term + owner profile
  Identity         — who Elena is (never changes)
  EventBus         — async publish/subscribe nervous system
  Config           — typed env-var configuration
  ProviderRegistry — catalogue of interchangeable service providers

Runtime NEVER OWNS:
  Reasoning        → registered as a Provider
  Speech (STT/TTS) → registered as a Provider
  Model inference  → registered as a Provider

Import surface
──────────────
  from smartagent.runtime import Runtime
  from smartagent.runtime import EventBus, Event
  from smartagent.runtime import Session, SessionState
  from smartagent.runtime import Identity
  from smartagent.runtime import Config
  from smartagent.runtime import ProviderRegistry, ProviderKind
"""

from .config import Config
from .event_bus import Event, EventBus
from .identity import Identity
from .provider_registry import ProviderKind, ProviderRegistry
from .runtime import Runtime
from .session import Session, SessionState, Turn, UtteranceKind

__all__ = [
    "Config",
    "Event",
    "EventBus",
    "Identity",
    "ProviderKind",
    "ProviderRegistry",
    "Runtime",
    "Session",
    "SessionState",
    "Turn",
    "UtteranceKind",
]
