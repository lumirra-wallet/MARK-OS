"""
OpenAIProvider — OpenAI API LLM provider.

Activated when ACTIVE_PROVIDER=openai.
Requires: pip install openai
Set OPENAI_API_KEY in environment.

Implements the full LLMProvider protocol:
    chat(), stream_chat(), embed(), embeddings(), list_models(), health(), switch_model()
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterator

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_EXCLUDE_FROM_DISCOVERY = True

_DEFAULT_MODEL      = os.environ.get("OPENAI_DEFAULT_MODEL", "gpt-4o-mini")
_DEFAULT_EMBED      = os.environ.get("OPENAI_EMBED_MODEL",   "text-embedding-3-small")
_BASE_URL           = os.environ.get("OPENAI_BASE_URL", "")  # override for Azure/proxies

# Curated mid-2026 OpenAI model catalogue.
# Returned by list_models() enriched with dashboard metadata fields.
_KNOWN_MODELS: list[dict] = [
    {
        "id": "gpt-4.1",         "name": "GPT-4.1",         "provider": "openai",
        "family": "gpt",         "params": "",               "context": 1_047_576,
        "size_gb": 0,            "modified": "2025-04-14",   "supports_tools": True,
    },
    {
        "id": "gpt-4.1-mini",    "name": "GPT-4.1 Mini",    "provider": "openai",
        "family": "gpt",         "params": "",               "context": 1_047_576,
        "size_gb": 0,            "modified": "2025-04-14",   "supports_tools": True,
    },
    {
        "id": "gpt-4o",          "name": "GPT-4o",           "provider": "openai",
        "family": "gpt",         "params": "",               "context": 128_000,
        "size_gb": 0,            "modified": "2024-11-20",   "supports_tools": True,
    },
    {
        "id": "gpt-4o-mini",     "name": "GPT-4o Mini",     "provider": "openai",
        "family": "gpt",         "params": "",               "context": 128_000,
        "size_gb": 0,            "modified": "2024-07-18",   "supports_tools": True,
    },
    {
        "id": "o3",              "name": "o3",               "provider": "openai",
        "family": "o3",          "params": "",               "context": 200_000,
        "size_gb": 0,            "modified": "2025-04-16",   "supports_tools": True,
    },
    {
        "id": "o3-mini",         "name": "o3-mini",          "provider": "openai",
        "family": "o3",          "params": "",               "context": 200_000,
        "size_gb": 0,            "modified": "2025-01-31",   "supports_tools": False,
    },
    {
        "id": "o4-mini",         "name": "o4-mini",          "provider": "openai",
        "family": "o3",          "params": "",               "context": 200_000,
        "size_gb": 0,            "modified": "2025-04-16",   "supports_tools": True,
    },
    {
        "id": "text-embedding-3-small", "name": "text-embedding-3-small", "provider": "openai",
        "family": "embedding",   "params": "",               "context": 8_191,
        "size_gb": 0,            "modified": "2024-01-25",   "supports_tools": False,
    },
    {
        "id": "text-embedding-3-large", "name": "text-embedding-3-large", "provider": "openai",
        "family": "embedding",   "params": "",               "context": 8_191,
        "size_gb": 0,            "modified": "2024-01-25",   "supports_tools": False,
    },
]


class OpenAIProvider:
    """
    OpenAI (or compatible) LLM provider.

    Compatible with any OpenAI-API-compatible endpoint — pass OPENAI_BASE_URL
    to point at Azure OpenAI, Together AI, Groq, etc.
    """

    _exclude_from_discovery = True

    def __init__(
        self,
        model_name:  str = _DEFAULT_MODEL,
        embed_model: str = _DEFAULT_EMBED,
        api_key:     str | None = None,
        base_url:    str = _BASE_URL,
    ) -> None:
        self._model      = model_name
        self._embed_mod  = embed_model
        self._api_key    = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url   = base_url
        self._client     = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def load(self) -> None:
        try:
            from openai import OpenAI  # type: ignore
            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        except ImportError:
            raise RuntimeError("OpenAIProvider requires: pip install openai")

    def _client_or_raise(self):
        if self._client is None:
            self.load()
        return self._client

    # ── LLMProvider protocol ───────────────────────────────────────────────

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        response = self._client_or_raise().chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096),
            stream=False,
        )
        choice = response.choices[0]
        usage  = response.usage
        return {
            "content":       choice.message.content or "",
            "tool_calls":    [],
            "usage":         {
                "prompt_tokens":     usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens":      usage.total_tokens if usage else 0,
            },
            "finish_reason": choice.finish_reason,
            "model":         self._model,
        }

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        stream = self._client_or_raise().chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096),
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    def embed(self, text: str, **_kwargs: Any) -> list[float]:
        response = self._client_or_raise().embeddings.create(
            model=self._embed_mod,
            input=text,
        )
        return response.data[0].embedding

    def embeddings(self, text: str, **kwargs: Any) -> list[float]:
        return self.embed(text, **kwargs)

    def list_models(self) -> list[dict[str, Any]]:
        """
        Return enriched model metadata for the current OpenAI lineup.

        Always returns the curated catalogue — the live /v1/models endpoint
        returns hundreds of fine-tuned snapshots with no useful metadata, so
        we overlay the curated list on top of what the API confirms is available.
        """
        try:
            live_ids: set[str] = {
                m.id for m in self._client_or_raise().models.list().data
            }
            # Keep curated models that the API confirms exist; fall back to
            # showing all curated models if the API is unavailable.
            return [
                m for m in _KNOWN_MODELS
                if m["id"] in live_ids
            ] or list(_KNOWN_MODELS)
        except Exception as exc:
            logger.warning("OpenAIProvider.list_models: %s — using curated catalogue", exc)
            return list(_KNOWN_MODELS)

    def health(self) -> dict[str, Any]:
        if not self._api_key:
            return {"healthy": False, "message": "OPENAI_API_KEY not set"}
        t0 = time.monotonic()
        try:
            self.chat([{"role": "user", "content": "hi"}], max_tokens=1)
            ms = round((time.monotonic() - t0) * 1000)
            return {"healthy": True, "message": f"OpenAI reachable ({ms}ms)", "model": self._model}
        except Exception as exc:
            return {"healthy": False, "message": str(exc)}

    def switch_model(self, model_name: str) -> None:
        self._model = model_name
        logger.info("OpenAIProvider: switched to %s", model_name)

    # ── Aliases ────────────────────────────────────────────────────────────

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return self.chat([{"role": "user", "content": prompt}], **kwargs)
