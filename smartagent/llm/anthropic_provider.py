"""
AnthropicProvider — Anthropic Claude LLM provider.

Activated when ACTIVE_PROVIDER=anthropic.
Requires: pip install anthropic
Set ANTHROPIC_API_KEY in environment.

Implements the full LLMProvider protocol:
    chat(), stream_chat(), embed(), embeddings(), list_models(), health(), switch_model()

Note: Anthropic does not provide a native embeddings API.
embed() raises NotImplementedError unless OPENAI_API_KEY is also set,
in which case text-embedding-3-small is used as a fallback.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterator

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MODEL = os.environ.get("ANTHROPIC_DEFAULT_MODEL", "claude-haiku-3-5")
_MAX_TOKENS    = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096"))

# Available Claude models — current mid-2026 lineup (for list_models()).
# Fields mirror the OllamaModel shape expected by the dashboard:
#   id, name, provider, family, params, context, size_gb, modified, supports_tools
_KNOWN_MODELS = [
    {
        "id":            "claude-opus-4-5",
        "name":          "Claude Opus 4.5",
        "provider":      "anthropic",
        "family":        "claude",
        "params":        "",
        "context":       200_000,
        "size_gb":       0,
        "modified":      "2025-08-01",
        "supports_tools": True,
    },
    {
        "id":            "claude-sonnet-4-5",
        "name":          "Claude Sonnet 4.5",
        "provider":      "anthropic",
        "family":        "claude",
        "params":        "",
        "context":       200_000,
        "size_gb":       0,
        "modified":      "2025-08-01",
        "supports_tools": True,
    },
    {
        "id":            "claude-haiku-3-5",
        "name":          "Claude Haiku 3.5",
        "provider":      "anthropic",
        "family":        "claude",
        "params":        "",
        "context":       200_000,
        "size_gb":       0,
        "modified":      "2024-11-05",
        "supports_tools": True,
    },
]


class AnthropicProvider:
    """
    Anthropic Claude LLM provider.

    For embeddings, falls back to OpenAI text-embedding-3-small (if OPENAI_API_KEY
    is set) since Anthropic has no native embedding API.
    """

    _exclude_from_discovery = True

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        api_key:    str | None = None,
    ) -> None:
        self._model   = model_name
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client  = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def load(self) -> None:
        try:
            import anthropic  # type: ignore
            self._client = anthropic.Anthropic(api_key=self._api_key)
        except ImportError:
            raise RuntimeError("AnthropicProvider requires: pip install anthropic")

    def _client_or_raise(self):
        if self._client is None:
            self.load()
        return self._client

    # ── LLMProvider protocol ───────────────────────────────────────────────

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        # Anthropic expects system messages separately
        system = ""
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                chat_msgs.append({"role": m["role"], "content": m["content"]})

        create_kwargs: dict[str, Any] = {
            "model":      self._model,
            "max_tokens": kwargs.get("max_tokens", _MAX_TOKENS),
            "messages":   chat_msgs,
        }
        if system:
            create_kwargs["system"] = system

        response = self._client_or_raise().messages.create(**create_kwargs)
        content  = response.content[0].text if response.content else ""
        usage    = response.usage
        return {
            "content":       content,
            "tool_calls":    [],
            "usage":         {
                "prompt_tokens":     usage.input_tokens  if usage else 0,
                "completion_tokens": usage.output_tokens if usage else 0,
                "total_tokens":      (usage.input_tokens + usage.output_tokens) if usage else 0,
            },
            "finish_reason": response.stop_reason or "stop",
            "model":         self._model,
        }

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        system = ""
        chat_msgs = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                chat_msgs.append({"role": m["role"], "content": m["content"]})

        create_kwargs: dict[str, Any] = {
            "model":      self._model,
            "max_tokens": kwargs.get("max_tokens", _MAX_TOKENS),
            "messages":   chat_msgs,
        }
        if system:
            create_kwargs["system"] = system

        with self._client_or_raise().messages.stream(**create_kwargs) as stream:
            for text in stream.text_stream:
                yield text

    def embed(self, text: str, **_kwargs: Any) -> list[float]:
        """
        Anthropic has no native embedding API.
        Falls back to OpenAI text-embedding-3-small if OPENAI_API_KEY is set.
        """
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            try:
                from openai import OpenAI  # type: ignore
                client = OpenAI(api_key=openai_key)
                resp = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text,
                )
                return resp.data[0].embedding
            except Exception as exc:
                raise RuntimeError(f"AnthropicProvider embed (OpenAI fallback) failed: {exc}") from exc
        raise NotImplementedError(
            "AnthropicProvider does not support embeddings natively. "
            "Set OPENAI_API_KEY to use text-embedding-3-small as a fallback."
        )

    def embeddings(self, text: str, **kwargs: Any) -> list[float]:
        return self.embed(text, **kwargs)

    def list_models(self) -> list[dict[str, Any]]:
        return list(_KNOWN_MODELS)

    def health(self) -> dict[str, Any]:
        if not self._api_key:
            return {"healthy": False, "message": "ANTHROPIC_API_KEY not set"}
        t0 = time.monotonic()
        try:
            self.chat([{"role": "user", "content": "hi"}], max_tokens=1)
            ms = round((time.monotonic() - t0) * 1000)
            return {"healthy": True, "message": f"Anthropic reachable ({ms}ms)", "model": self._model}
        except Exception as exc:
            return {"healthy": False, "message": str(exc)}

    def switch_model(self, model_name: str) -> None:
        self._model = model_name
        logger.info("AnthropicProvider: switched to %s", model_name)

    # ── Aliases ────────────────────────────────────────────────────────────

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return self.chat([{"role": "user", "content": prompt}], **kwargs)
