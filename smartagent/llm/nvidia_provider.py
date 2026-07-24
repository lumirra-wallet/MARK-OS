"""
NvidiaProvider — NVIDIA NIM / build.nvidia.com inference provider.

Uses the OpenAI Python SDK pointed at NVIDIA's OpenAI-compatible endpoint::

    https://integrate.api.nvidia.com/v1

Authentication via NVIDIA_API_KEY environment variable.

Architecture:

    Brain / Workers / RAG / Memory
          ↓
    ModelManager (via chat_stream / chat / generate)
          ↓
    NvidiaProvider  ← THIS FILE
          ↓
    NVIDIA API (OpenAI-compatible)

Nothing above ModelManager should import this module directly.

Fallback:
    If the NVIDIA API is unreachable or the key is invalid, chat() returns a
    dict with ``"content": "<error message>"`` rather than raising — callers
    must check for the ``NVIDIA_ERROR_PREFIX`` sentinel before treating
    chat()/chat_stream() output as real content (see
    ``smartagent.llm.factory.is_llm_error_text``).

Reasoning:
    Nemotron models support an extended "thinking" mode (extra_body
    chat_template_kwargs.enable_thinking + reasoning_budget). Reasoning
    tokens arrive on a separate ``delta.reasoning_content`` field, distinct
    from the final answer's ``delta.content`` — only ``content`` is
    surfaced through chat()/chat_stream(), matching every other provider's
    contract (callers only ever see the final answer, never raw
    intermediate reasoning).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Iterator

from smartagent.logs.logger import get_logger
from smartagent.models.base.base_model import BaseModel, ModelHealth, ModelStatus

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Sentinel — skip auto-discovery; registered explicitly by the ProviderFactory
# ---------------------------------------------------------------------------
_EXCLUDE_FROM_DISCOVERY = True

NVIDIA_INFERENCE_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_REASONING_BUDGET = 16384

# ---------------------------------------------------------------------------
# Process-wide telemetry — diagnostics needs real cumulative request/error
# counts, but api_diagnostics.py's health check constructs a fresh, throwaway
# NvidiaProvider instance per poll (so a per-instance counter would always
# read back 0). Track at module level instead, updated by every instance.
# ---------------------------------------------------------------------------
_total_requests: int = 0
_last_error: str | None = None
_last_error_at: str | None = None


def get_telemetry() -> dict[str, Any]:
    """Process-wide request count + last error, for the diagnostics endpoint."""
    return {
        "base_url":       NVIDIA_INFERENCE_BASE_URL,
        "total_requests": _total_requests,
        "last_error":     _last_error,
        "last_error_at":  _last_error_at,
    }


def _record_request() -> None:
    global _total_requests
    _total_requests += 1


def _record_error(exc: BaseException) -> None:
    global _last_error, _last_error_at
    _last_error    = str(exc)
    _last_error_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

# Curated catalogue of NVIDIA-hosted models this codebase knows about.
# Fields mirror _GITHUB_MODEL_CATALOGUE's shape for consistency.
_NVIDIA_MODEL_CATALOGUE: list[dict[str, Any]] = [
    {
        "id": "nvidia/nemotron-3-ultra-550b-a55b", "family": "nemotron", "context": 128_000,
        "supports_tools": True,                    "params": "550B-A55B", "size_gb": 0,
        "modified": "2026-01-01",
    },
    {
        # Fast conversational model on the same NVIDIA API — used by the
        # voice loop (brain_runtime), where time-to-first-token dominates the
        # felt latency. Measured on this account: ~2 s round-trip vs ~10 s
        # for the 550B ultra. The ultra stays the default for deep work.
        "id": "meta/llama-3.1-8b-instruct", "family": "llama", "context": 128_000,
        "supports_tools": True,             "params": "8B",    "size_gb": 0,
        "modified": "2026-01-01",
    },
]


def _get_client(api_key: str | None = None, timeout: float = 120.0):
    """Build an OpenAI client pointed at NVIDIA's inference endpoint."""
    from openai import OpenAI  # lazily imported to avoid hard startup dep
    resolved_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
    if not resolved_key:
        raise ValueError(
            "NVIDIA_API_KEY environment variable is not set. "
            "Set it to a build.nvidia.com API key."
        )
    return OpenAI(
        base_url=NVIDIA_INFERENCE_BASE_URL,
        api_key=resolved_key,
        timeout=timeout,
    )


class NvidiaProvider(BaseModel):
    """
    Connects MARK to NVIDIA's NIM inference API via the OpenAI-compatible SDK.

    Args:
        model_name:        NVIDIA model id (e.g. ``"nvidia/nemotron-3-ultra-550b-a55b"``).
        api_key:           NVIDIA API key. Defaults to ``NVIDIA_API_KEY`` env var.
        timeout:           HTTP timeout in seconds (large MoE models can be slow).
        enable_thinking:   Request the model's extended reasoning mode.
        reasoning_budget:  Max reasoning tokens when thinking mode is enabled.
    """

    _exclude_from_discovery: bool = True

    def __init__(
        self,
        model_name: str = "nvidia/nemotron-3-ultra-550b-a55b",
        api_key: str | None = None,
        timeout: float = 120.0,
        enable_thinking: bool = True,
        reasoning_budget: int = DEFAULT_REASONING_BUDGET,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        self._timeout = timeout
        # Thinking mode is only supported by Nemotron models — sending
        # chat_template_kwargs.enable_thinking to a Llama/non-Nemotron model
        # causes it to ignore the system prompt and respond as a generic LLM.
        # Auto-disable it for any model whose ID doesn't contain "nemotron".
        nemotron = "nemotron" in model_name.lower()
        self._enable_thinking = enable_thinking and nemotron
        self._reasoning_budget = reasoning_budget
        self._status = ModelStatus.UNLOADED
        self._call_count = 0
        self._client = None  # lazily created on first use

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self._model_name

    @property
    def name(self) -> str:
        return f"NVIDIA/{self._model_name}"

    @property
    def provider(self) -> str:
        return "nvidia"

    @property
    def version(self) -> str:
        return "1.0.0"

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    @property
    def context_window(self) -> int:
        for m in _NVIDIA_MODEL_CATALOGUE:
            if m["id"] == self._model_name:
                return m["context"]
        return 128_000  # conservative default

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        for m in _NVIDIA_MODEL_CATALOGUE:
            if m["id"] == self._model_name:
                return bool(m.get("supports_tools", False))
        return False

    @property
    def supports_images(self) -> bool:
        return False

    @property
    def supports_embeddings(self) -> bool:
        return False

    @property
    def supports_functions(self) -> bool:
        return self.supports_tools

    @property
    def call_count(self) -> int:
        return self._call_count

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        logger.info(
            "NvidiaProvider initialized: model=%s base_url=%s",
            self._model_name, NVIDIA_INFERENCE_BASE_URL,
        )

    def load(self) -> None:
        """
        Mark the provider as loaded and validate the key.

        Always sets _status = LOADED so model switching works regardless of
        connectivity. The real signal is health().
        """
        self._status = ModelStatus.LOADED
        if not self._api_key:
            logger.warning(
                "NvidiaProvider: NVIDIA_API_KEY is not set — "
                "API calls will fail. Set it in your environment."
            )
        else:
            logger.info(
                "NvidiaProvider: %s ready (key present, %d chars)",
                self._model_name, len(self._api_key),
            )

    def unload(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        self._status = ModelStatus.UNLOADED
        self._client = None
        logger.info("NvidiaProvider: %s unloaded", self._model_name)

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            self._client = _get_client(self._api_key, timeout=self._timeout)
        return self._client

    def _reasoning_extra_body(self) -> dict[str, Any]:
        if not self._enable_thinking:
            return {}
        return {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": self._reasoning_budget,
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> ModelHealth:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self._api_key:
            return ModelHealth(
                healthy=False,
                status=self._status,
                message="NVIDIA_API_KEY is not set.",
                checked_at=now,
            )
        t0 = time.monotonic()
        _record_request()
        try:
            client = self._get_client()
            client.chat.completions.create(
                model=self._model_name,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                stream=False,
            )
            latency_ms = round((time.monotonic() - t0) * 1000)
            return ModelHealth(
                healthy=True,
                status=self._status,
                message=(
                    f"NVIDIA API reachable; {self._model_name} available. "
                    f"Latency: {latency_ms}ms"
                ),
                checked_at=now,
            )
        except Exception as exc:
            _record_error(exc)
            return ModelHealth(
                healthy=False,
                status=ModelStatus.ERROR,
                message=f"NVIDIA API unreachable: {exc}",
                checked_at=now,
            )

    # ------------------------------------------------------------------
    # Generation (non-streaming)
    # ------------------------------------------------------------------

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a response for *prompt* (non-streaming)."""
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"NvidiaProvider {self._model_name!r} must be load()ed before generate()."
            )
        messages = self._prompt_to_messages(prompt)
        return self.chat(messages, **kwargs)

    def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Non-streaming chat completion.

        Returns the same provider-shaped dict as the other providers so
        ResponseParser can normalise them all without special-casing.
        """
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"NvidiaProvider {self._model_name!r} must be load()ed before chat()."
            )
        self._call_count += 1
        _record_request()
        params = self._build_params(kwargs)
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self._model_name,
                messages=messages,  # type: ignore[arg-type]
                stream=False,
                extra_body=self._reasoning_extra_body(),
                **params,
            )
            content = response.choices[0].message.content or ""
            usage = response.usage
            return {
                "content": content,
                "tool_calls": [],
                "usage": {
                    "prompt_tokens":     getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens":      getattr(usage, "total_tokens", 0),
                },
                "finish_reason": (response.choices[0].finish_reason or "stop"),
                "model": self._model_name,
            }
        except Exception as exc:
            _record_error(exc)
            logger.warning(
                "NvidiaProvider.chat: error for model %s: %s",
                self._model_name, exc,
            )
            return {
                "content": f"NVIDIA API error: {exc}",
                "tool_calls": [],
                "usage": {},
                "finish_reason": "error",
                "model": self._model_name,
            }

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Streaming generation for a flat prompt."""
        yield from self.generate_stream(prompt, **kwargs)

    def generate_stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Stream tokens for *prompt*."""
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"NvidiaProvider {self._model_name!r} must be load()ed before generate_stream()."
            )
        self._call_count += 1
        messages = self._prompt_to_messages(prompt)
        yield from self._stream_messages(messages, **kwargs)

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """Stream tokens for a chat messages list."""
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"NvidiaProvider {self._model_name!r} must be load()ed before chat_stream()."
            )
        self._call_count += 1
        yield from self._stream_messages(messages, **kwargs)

    def _stream_messages(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """
        Core streaming implementation. Only the final-answer ``content``
        delta is yielded — ``reasoning_content`` (the model's "thinking"
        tokens) is deliberately swallowed here, never surfaced to callers,
        matching every other provider's contract of "chat_stream() output
        is the final answer, nothing else."
        """
        _record_request()
        params = self._build_params(kwargs)
        try:
            client = self._get_client()
            stream = client.chat.completions.create(
                model=self._model_name,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
                extra_body=self._reasoning_extra_body(),
                **params,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    yield content
        except Exception as exc:
            _record_error(exc)
            logger.warning(
                "NvidiaProvider.stream: error for model %s: %s",
                self._model_name, exc,
            )
            yield f"NVIDIA API error: {exc}"

    # ------------------------------------------------------------------
    # Tool calling (agentic)
    # ------------------------------------------------------------------

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Any:
        """
        Non-streaming chat call with OpenAI function-calling tool definitions.

        Returns the raw ``choices[0].message`` object from the OpenAI SDK so
        callers can inspect ``.tool_calls`` and ``.content`` directly.

        Raises:
            RuntimeError: If the provider is not loaded.
        """
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"NvidiaProvider {self._model_name!r} must be load()ed before chat_with_tools()."
            )
        self._call_count += 1
        _record_request()
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self._model_name,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,        # type: ignore[arg-type]
                tool_choice="auto",
                max_tokens=max_tokens,
                stream=False,
                extra_body=self._reasoning_extra_body(),
            )
            return response.choices[0].message
        except Exception as exc:
            _record_error(exc)
            logger.warning(
                "NvidiaProvider.chat_with_tools: error for model %s: %s",
                self._model_name, exc,
            )
            raise

    # ------------------------------------------------------------------
    # Embeddings (not supported by this chat model)
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            f"NvidiaProvider {self._model_name!r} does not support embeddings "
            "— it's a chat/reasoning model, not an embedding model."
        )

    # ------------------------------------------------------------------
    # Model catalogue
    # ------------------------------------------------------------------

    def list_models(self) -> list[dict[str, Any]]:
        """
        Return metadata for all models this codebase knows about on NVIDIA's
        API. Tries the live /models endpoint first; falls back to the
        curated static catalogue if it's unavailable.
        """
        try:
            client = self._get_client()
            response = client.models.list()
            live = [
                {
                    "id":             m.id,
                    "family":         "nemotron" if "nemotron" in m.id.lower() else "other",
                    "context":        128_000,
                    "supports_tools": True,
                }
                for m in response.data
            ]
            if live:
                return live
        except Exception as exc:
            logger.debug("NvidiaProvider.list_models: live fetch failed (%s), using catalogue", exc)
        return list(_NVIDIA_MODEL_CATALOGUE)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt_to_messages(prompt: str) -> list[dict[str, str]]:
        """Convert a flat prompt string to a chat messages list."""
        return [{"role": "user", "content": prompt}]

    @staticmethod
    def _build_params(kwargs: dict[str, Any]) -> dict[str, Any]:
        """Map ModelSettings generation kwargs to OpenAI API params."""
        params: dict[str, Any] = {}
        if "temperature" in kwargs:
            params["temperature"] = float(kwargs["temperature"])
        if "max_tokens" in kwargs:
            params["max_tokens"] = int(kwargs["max_tokens"])
        if "top_p" in kwargs:
            params["top_p"] = float(kwargs["top_p"])
        return params
