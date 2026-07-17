"""
GitHubProvider — GitHub Models inference provider.

Uses the OpenAI Python SDK pointed at the GitHub Models inference endpoint::

    https://models.github.ai/inference

Authentication via GITHUB_TOKEN environment variable (the PAT or fine-grained
token with Models access).

Architecture:

    Brain / Workers / RAG / Memory
          ↓
    ModelManager (via chat_stream / chat / generate)
          ↓
    GitHubProvider  ← THIS FILE
          ↓
    GitHub Models API (OpenAI-compatible)

Nothing above ModelManager should import this module directly.

Discovery:
    _exclude_from_discovery = True — ModelManager.load_github_models() or
    the ProviderFactory registers instances explicitly with the right token.

Fallback:
    If the GitHub API is unreachable or the token is invalid, chat() returns a
    dict with ``"content": "<error message>"`` rather than raising.
    health() reports healthy=False and the error reason.

Streaming:
    chat_stream() yields tokens using the OpenAI SDK's streaming iterator.

Embeddings:
    Uses ``text-embedding-3-small`` (available through GitHub Models).

Tool calling:
    Enabled for models that support it (gpt-4.1, gpt-4o, etc.).
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
# Sentinel — skip auto-discovery; registered explicitly by load_github_models()
# ---------------------------------------------------------------------------
_EXCLUDE_FROM_DISCOVERY = True

GITHUB_INFERENCE_BASE_URL = "https://models.github.ai/inference"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# Curated catalogue of GitHub Models available as of mid-2026.
# Used as a static fallback when the live /models endpoint is unavailable.
# Fields: id, family, context, supports_tools, params, size_gb, modified (ISO-8601 date)
_GITHUB_MODEL_CATALOGUE: list[dict[str, Any]] = [
    # ── OpenAI ────────────────────────────────────────────────────────────────
    {
        "id": "gpt-4.1",                "family": "gpt",       "context": 1_047_576,
        "supports_tools": True,         "params": "",          "size_gb": 0,
        "modified": "2025-04-14",
    },
    {
        "id": "gpt-4.1-mini",           "family": "gpt",       "context": 1_047_576,
        "supports_tools": True,         "params": "",          "size_gb": 0,
        "modified": "2025-04-14",
    },
    {
        "id": "gpt-4.1-nano",           "family": "gpt",       "context": 1_047_576,
        "supports_tools": True,         "params": "",          "size_gb": 0,
        "modified": "2025-04-14",
    },
    {
        "id": "gpt-4o",                 "family": "gpt",       "context": 128_000,
        "supports_tools": True,         "params": "",          "size_gb": 0,
        "modified": "2024-11-20",
    },
    {
        "id": "gpt-4o-mini",            "family": "gpt",       "context": 128_000,
        "supports_tools": True,         "params": "",          "size_gb": 0,
        "modified": "2024-07-18",
    },
    {
        "id": "o3",                     "family": "o3",        "context": 200_000,
        "supports_tools": True,         "params": "",          "size_gb": 0,
        "modified": "2025-04-16",
    },
    {
        "id": "o3-mini",                "family": "o3",        "context": 200_000,
        "supports_tools": False,        "params": "",          "size_gb": 0,
        "modified": "2025-01-31",
    },
    {
        "id": "o4-mini",                "family": "o3",        "context": 200_000,
        "supports_tools": True,         "params": "",          "size_gb": 0,
        "modified": "2025-04-16",
    },
    # ── Microsoft Phi ─────────────────────────────────────────────────────────
    {
        "id": "Phi-4",                  "family": "phi",       "context": 16_384,
        "supports_tools": False,        "params": "14B",       "size_gb": 0,
        "modified": "2024-12-12",
    },
    {
        "id": "Phi-4-mini-instruct",    "family": "phi",       "context": 128_000,
        "supports_tools": False,        "params": "3.8B",      "size_gb": 0,
        "modified": "2025-03-01",
    },
    {
        "id": "Phi-4-reasoning",        "family": "phi",       "context": 32_000,
        "supports_tools": False,        "params": "14B",       "size_gb": 0,
        "modified": "2025-04-30",
    },
    # ── Meta Llama ────────────────────────────────────────────────────────────
    {
        "id": "Llama-3.3-70B-Instruct", "family": "llama",    "context": 128_000,
        "supports_tools": True,         "params": "70B",       "size_gb": 0,
        "modified": "2024-12-06",
    },
    {
        "id": "Llama-4-Scout-17B-16E-Instruct", "family": "llama", "context": 128_000,
        "supports_tools": False,        "params": "17B",       "size_gb": 0,
        "modified": "2025-04-05",
    },
    # ── Mistral ───────────────────────────────────────────────────────────────
    {
        "id": "Mistral-Large-2411",     "family": "mistral",   "context": 128_000,
        "supports_tools": True,         "params": "123B",      "size_gb": 0,
        "modified": "2024-11-01",
    },
    {
        "id": "Codestral-2501",         "family": "codestral", "context": 256_000,
        "supports_tools": False,        "params": "22B",       "size_gb": 0,
        "modified": "2025-01-01",
    },
    # ── DeepSeek ──────────────────────────────────────────────────────────────
    {
        "id": "DeepSeek-V3",            "family": "deepseek",  "context": 64_000,
        "supports_tools": False,        "params": "671B",      "size_gb": 0,
        "modified": "2025-01-20",
    },
    # ── Embeddings ────────────────────────────────────────────────────────────
    {
        "id": "text-embedding-3-small", "family": "embedding", "context": 8_191,
        "supports_tools": False,        "params": "",          "size_gb": 0,
        "modified": "2024-01-25",
    },
    {
        "id": "text-embedding-3-large", "family": "embedding", "context": 8_191,
        "supports_tools": False,        "params": "",          "size_gb": 0,
        "modified": "2024-01-25",
    },
]


def _get_client(token: str | None = None, timeout: float = 60.0):
    """Build an OpenAI client pointed at GitHub Models inference."""
    from openai import OpenAI  # lazily imported to avoid hard startup dep
    resolved_token = token or os.environ.get("GITHUB_TOKEN", "")
    if not resolved_token:
        raise ValueError(
            "GITHUB_TOKEN environment variable is not set. "
            "Set it to a GitHub personal access token with Models access."
        )
    return OpenAI(
        base_url=GITHUB_INFERENCE_BASE_URL,
        api_key=resolved_token,
        timeout=timeout,
    )


class GitHubProvider(BaseModel):
    """
    Connects MARK to GitHub Models via the OpenAI-compatible inference API.

    One ``GitHubProvider`` instance per model name is registered with
    ``ModelManager``.  ``ModelManager.load_github_models()`` creates them.

    Args:
        model_name:       GitHub Models model id (e.g. ``"gpt-4.1-mini"``).
        token:            GitHub PAT. Defaults to ``GITHUB_TOKEN`` env var.
        timeout:          HTTP timeout in seconds.
        embedding_model:  Model to use for ``embed()``.
        max_retries:      Number of retries on transient errors (OpenAI SDK handles these).
    """

    _exclude_from_discovery: bool = True

    def __init__(
        self,
        model_name: str = "gpt-4.1-mini",
        token: str | None = None,
        timeout: float = 60.0,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        max_retries: int = 2,
    ) -> None:
        self._model_name = model_name
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._timeout = timeout
        self._embedding_model = embedding_model
        self._max_retries = max_retries
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
        return f"GitHub/{self._model_name}"

    @property
    def provider(self) -> str:
        return "github"

    @property
    def version(self) -> str:
        return "1.0.0"

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    @property
    def context_window(self) -> int:
        for m in _GITHUB_MODEL_CATALOGUE:
            if m["id"] == self._model_name:
                return m["context"]
        return 128_000  # conservative default

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        for m in _GITHUB_MODEL_CATALOGUE:
            if m["id"] == self._model_name:
                return bool(m.get("supports_tools", False))
        return False

    @property
    def supports_images(self) -> bool:
        return "vision" in self._model_name.lower() or "4o" in self._model_name.lower()

    @property
    def supports_embeddings(self) -> bool:
        return True  # via text-embedding-3-small

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
            "GitHubProvider initialized: model=%s base_url=%s",
            self._model_name, GITHUB_INFERENCE_BASE_URL,
        )

    def load(self) -> None:
        """
        Mark the provider as loaded and validate the token.

        Always sets _status = LOADED so model switching works regardless of
        connectivity. The real signal is health().
        """
        self._status = ModelStatus.LOADED
        if not self._token:
            logger.warning(
                "GitHubProvider: GITHUB_TOKEN is not set — "
                "API calls will fail. Set it in your environment."
            )
        else:
            logger.info(
                "GitHubProvider: %s ready (token present, %d chars)",
                self._model_name, len(self._token),
            )

    def unload(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        self._status = ModelStatus.UNLOADED
        self._client = None
        logger.info("GitHubProvider: %s unloaded", self._model_name)

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def _get_client(self):
        if self._client is None:
            self._client = _get_client(self._token, timeout=self._timeout)
        return self._client

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> ModelHealth:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self._token:
            return ModelHealth(
                healthy=False,
                status=self._status,
                message="GITHUB_TOKEN is not set.",
                checked_at=now,
            )
        t0 = time.monotonic()
        try:
            client = self._get_client()
            # Probe with a minimal 1-token generation (models.list is not
            # supported at the GitHub inference endpoint).
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
                    f"GitHub Models reachable; {self._model_name} available. "
                    f"Latency: {latency_ms}ms"
                ),
                checked_at=now,
            )
        except Exception as exc:
            return ModelHealth(
                healthy=False,
                status=ModelStatus.ERROR,
                message=f"GitHub Models unreachable: {exc}",
                checked_at=now,
            )

    # ------------------------------------------------------------------
    # Generation (non-streaming)
    # ------------------------------------------------------------------

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a response for *prompt* (non-streaming)."""
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"GitHubProvider {self._model_name!r} must be load()ed before generate()."
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

        Returns the same provider-shaped dict as OllamaProvider.chat() so
        ResponseParser can normalise both without special-casing.
        """
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(
                f"GitHubProvider {self._model_name!r} must be load()ed before chat()."
            )
        self._call_count += 1
        params = self._build_params(kwargs)
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self._model_name,
                messages=messages,  # type: ignore[arg-type]
                stream=False,
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
            logger.warning(
                "GitHubProvider.chat: error for model %s: %s",
                self._model_name, exc,
            )
            return {
                "content": f"GitHub Models error: {exc}",
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
                f"GitHubProvider {self._model_name!r} must be load()ed before generate_stream()."
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
                f"GitHubProvider {self._model_name!r} must be load()ed before chat_stream()."
            )
        self._call_count += 1
        yield from self._stream_messages(messages, **kwargs)

    def _stream_messages(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """Core streaming implementation."""
        params = self._build_params(kwargs)
        try:
            client = self._get_client()
            stream = client.chat.completions.create(
                model=self._model_name,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
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
            logger.warning(
                "GitHubProvider.stream: error for model %s: %s",
                self._model_name, exc,
            )
            yield f"GitHub Models error: {exc}"

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
                f"GitHubProvider {self._model_name!r} must be load()ed before chat_with_tools()."
            )
        self._call_count += 1
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self._model_name,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,        # type: ignore[arg-type]
                tool_choice="auto",
                max_tokens=max_tokens,
                stream=False,
            )
            return response.choices[0].message
        except Exception as exc:
            logger.warning(
                "GitHubProvider.chat_with_tools: error for model %s: %s",
                self._model_name, exc,
            )
            raise

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Return an embedding vector using text-embedding-3-small."""
        try:
            client = self._get_client()
            response = client.embeddings.create(
                model=self._embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("GitHubProvider.embed: error: %s", exc)
            raise RuntimeError(f"GitHub Models embeddings error: {exc}") from exc

    # Re-expose as embeddings() so LLMProvider protocol is satisfied
    def embeddings(self, text: str, **_kwargs: Any) -> list[float]:
        return self.embed(text)

    # ------------------------------------------------------------------
    # Model catalogue
    # ------------------------------------------------------------------

    def list_models(self) -> list[dict[str, Any]]:
        """
        Return metadata for all models available on GitHub Models.

        Tries the live /models endpoint first; falls back to the curated
        static catalogue if the API is unavailable.
        """
        try:
            client = self._get_client()
            response = client.models.list()
            live = [
                {
                    "id":             m.id,
                    "family":         _infer_family(m.id),
                    "context":        128_000,
                    "supports_tools": _infer_tools(m.id),
                }
                for m in response.data
                if m.id != "text-embedding-3-small"  # exclude embedding-only
            ]
            if live:
                return live
        except Exception as exc:
            logger.debug("GitHubProvider.list_models: live fetch failed (%s), using catalogue", exc)
        return [m for m in _GITHUB_MODEL_CATALOGUE if m["family"] != "embedding"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt_to_messages(prompt: str) -> list[dict[str, str]]:
        """Convert a flat prompt string to a chat messages list."""
        if prompt.startswith("System:"):
            messages: list[dict[str, str]] = []
            lines = prompt.splitlines()
            current_role = ""
            current_lines: list[str] = []
            for line in lines:
                for prefix, role in [("System:", "system"), ("User:", "user"), ("assistant:", "assistant")]:
                    if line.startswith(prefix):
                        if current_role and current_lines:
                            messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
                        current_role = role
                        current_lines = [line[len(prefix):].strip()]
                        break
                else:
                    current_lines.append(line)
            if current_role and current_lines:
                messages.append({"role": current_role, "content": "\n".join(current_lines).strip()})
            return messages or [{"role": "user", "content": prompt}]
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_family(model_id: str) -> str:
    lower = model_id.lower()
    for family in ("llama", "mistral", "phi", "deepseek", "gpt", "o1", "o3", "codestral", "embedding"):
        if family in lower:
            return family
    return "other"


def _infer_tools(model_id: str) -> bool:
    tool_capable = (
        "gpt-4", "gpt-4o", "gpt-4.1", "o3", "o4",
        "llama-3.3", "llama-4", "mistral-large",
    )
    return any(t in model_id.lower() for t in tool_capable)
