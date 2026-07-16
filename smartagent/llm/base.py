"""
LLMProvider — unified interface every provider must satisfy.

This module defines the canonical LLMProvider protocol that
feature code (chat, RAG, agents, memory, planning, voice) calls.
Concrete implementations live in github_provider.py and the existing
OllamaProvider in smartagent/models/providers/ollama_provider.py.

The LLMProvider interface is a superset of the BaseModel abstract class:
it adds list_models() and makes embeddings a documented first-class method.
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable

from smartagent.models.base.base_model import BaseModel, ModelHealth, ModelMetadata, ModelStatus


@runtime_checkable
class LLMProvider(Protocol):
    """
    Structural protocol that every provider must satisfy.

    Any class that implements these methods is a valid provider — no
    explicit subclassing required.  BaseModel subclasses that also add
    list_models() automatically satisfy this protocol.

    Methods:
        chat(messages, **kwargs)    — non-streaming chat completion
        stream_chat(messages, **kwargs) — streaming token iterator
        embeddings(text, **kwargs)  — embedding vector for *text*
        list_models()               — catalogue of models this provider offers

    All other BaseModel lifecycle methods (initialize, load, generate,
    stream, embed, shutdown, health, metadata) are part of the concrete
    implementation — feature code only calls the four methods above.
    """

    def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Non-streaming chat completion. Returns ``{"content": str, ...}``."""
        ...

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """Streaming chat. Yields text tokens as they arrive."""
        ...

    def embeddings(self, text: str, **kwargs: Any) -> list[float]:
        """Return an embedding vector for *text*."""
        ...

    def list_models(self) -> list[dict[str, Any]]:
        """Return metadata dicts for every model this provider offers."""
        ...


# Re-export base types so callers can import from smartagent.llm.base
__all__ = [
    "LLMProvider",
    "BaseModel",
    "ModelHealth",
    "ModelMetadata",
    "ModelStatus",
]
