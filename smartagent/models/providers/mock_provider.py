"""
MockModelProvider — Milestone 5, Part 9.

The one concrete, working `BaseModel` implementation Milestone 5 ships.
Deterministic and offline: it never calls out to a real AI backend, so it
is safe to load in tests and CI without network access, API keys, or
non-deterministic output. It exists purely so `ModelManager`,
`PromptBuilder`, `ResponseParser`, and `ConversationContext` have a real
provider to exercise end-to-end.

Design decisions:
- `generate()` returns a small provider-shaped `dict` (`content`,
  `tool_calls`, `usage`, `finish_reason`) rather than a `ParsedResponse`
  directly — normalizing that shape into a `ParsedResponse` is
  `ResponseParser`'s job (Part 7), and using a plain dict here keeps this
  provider a plausible stand-in for what a real HTTP-API-backed provider
  would return.
- The response text is derived deterministically from the prompt (a
  digest-based token plus a truncated echo) so the same prompt always
  produces the same output — useful for asserting behavior in tests
  without hardcoding a magic string in two places.
- `embed()` always raises `NotImplementedError` — Milestone 5's rules
  explicitly forbid implementing embeddings for any provider yet.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterator

from smartagent.logs.logger import get_logger
from smartagent.models.base.base_model import BaseModel, ModelStatus

logger = get_logger(__name__)


def _estimate_tokens(text: str) -> int:
    """Rough, provider-agnostic token estimate: ~4 characters per token."""
    return max(1, len(text) // 4)


class MockModelProvider(BaseModel):
    """A deterministic, offline stand-in for a real language model backend."""

    def __init__(self) -> None:
        self._status = ModelStatus.UNLOADED
        self._call_count = 0

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        return "mock"

    @property
    def name(self) -> str:
        return "Mock Model"

    @property
    def provider(self) -> str:
        return "mock"

    @property
    def version(self) -> str:
        return "0.1.0"

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    @property
    def context_window(self) -> int:
        return 4096

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_tools(self) -> bool:
        return False

    @property
    def supports_images(self) -> bool:
        return False

    @property
    def supports_embeddings(self) -> bool:
        return False

    @property
    def supports_functions(self) -> bool:
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        logger.info("MockModelProvider initialized (no real backend to configure).")

    def load(self) -> None:
        self._status = ModelStatus.LOADED
        logger.info("Model loaded: %s (%s)", self.id, self.name)

    def shutdown(self) -> None:
        self._status = ModelStatus.UNLOADED
        logger.info("Model unloaded: %s", self.id)

    @property
    def call_count(self) -> int:
        """Number of `generate()` calls served since `load()` — used by statistics/tests."""
        return self._call_count

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def generate(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        if self._status != ModelStatus.LOADED:
            raise RuntimeError(f"Model {self.id!r} must be load()ed before generate() is called.")
        self._call_count += 1
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
        excerpt = prompt.strip().replace("\n", " ")[:160]
        content = f"[mock-{digest}] deterministic reply to: {excerpt}"
        prompt_tokens = _estimate_tokens(prompt)
        completion_tokens = _estimate_tokens(content)
        return {
            "content": content,
            "tool_calls": [],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "finish_reason": "stop",
            "model": self.id,
        }

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        raw = self.generate(prompt, **kwargs)
        for word in raw["content"].split(" "):
            yield word + " "

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Embeddings are out of scope for Milestone 5 (Model Framework v1) — "
            "no provider, including MockModelProvider, implements embed() yet."
        )
