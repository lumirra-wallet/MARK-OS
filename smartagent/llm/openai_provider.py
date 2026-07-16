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
        try:
            models = self._client_or_raise().models.list()
            return [
                {"id": m.id, "name": m.id, "provider": "openai"}
                for m in models.data
                if "gpt" in m.id or "text-embedding" in m.id
            ]
        except Exception as exc:
            logger.warning("OpenAIProvider.list_models: %s", exc)
            return []

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
