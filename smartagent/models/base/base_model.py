"""
BaseModel — Milestone 5, Model Framework v1, Part 1.

Defines the abstract contract every model provider implements, whether
it is `MockModelProvider` (Part 9, wired up today) or one of the
design-only future providers (Part 10 — Ollama, OpenAI, Anthropic, etc.,
none of which are implemented yet). Nothing above this class — `ModelManager`,
`PromptBuilder`, `ResponseParser`, the Brain — ever needs to know which
concrete provider it is talking to; they only depend on this interface.

Design deliberately mirrors `BaseTool`/`BaseSkill`:

- Required abstract identity properties (`id`, `name`, `provider`, `version`).
- Optional overridable capability properties, defaulted conservatively
  (`False`/`0`) so a minimal provider can be written without claiming
  capabilities it doesn't have.
- Required abstract lifecycle/action methods (Part 1's "every model must
  implement": `initialize`, `load`, `generate`, `stream`, `embed`, `shutdown`).
- `metadata()` and `status()` are concrete snapshot builders (like
  `BaseTool.metadata()`), not abstract — a provider satisfies the spec's
  "must implement metadata()/status()" simply by inheriting from this class,
  without every provider needing to hand-write the same snapshot logic.
- `health()` has a concrete default (derived from `status()`) but providers
  may override it to do a real connectivity probe once a real backend exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterator


class ModelStatus(str, Enum):
    """Runtime lifecycle status of a model provider instance."""

    UNLOADED = "unloaded"
    LOADED = "loaded"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ModelMetadata:
    """
    Frozen snapshot of a model provider's declared identity and capabilities.

    Built on demand via `BaseModel.metadata()` so callers (`ModelRegistry`,
    `ModelManager.statistics()`, future UIs) have one stable, hashable shape
    regardless of the concrete provider.
    """

    id: str
    name: str
    provider: str
    version: str
    context_window: int
    supports_streaming: bool
    supports_tools: bool
    supports_images: bool
    supports_embeddings: bool
    supports_functions: bool


@dataclass(frozen=True)
class ModelHealth:
    """Health snapshot returned by `BaseModel.health()` / `ModelManager.health_check()`."""

    healthy: bool
    status: ModelStatus
    message: str
    checked_at: str


class BaseModel(ABC):
    """
    Abstract base class every SmartAgent model provider implements (Part 1).

    **Required** abstract identity properties: `id`, `name`, `provider`, `version`.

    **Required** abstract lifecycle/action methods: `initialize()`, `load()`,
    `generate()`, `stream()`, `embed()`, `shutdown()`.

    **Optional** overridable capability properties (all default to the most
    conservative value — "no, I can't do that"): `context_window` (0),
    `supports_streaming`, `supports_tools`, `supports_images`,
    `supports_embeddings`, `supports_functions` (all `False`).

    Only `ModelManager` is allowed to hold and call a `BaseModel` instance
    directly — the Brain, Skills, and everything else talk to `ModelManager`
    instead (Part 11), so swapping a provider never ripples outward.
    """

    #: Runtime lifecycle status. Providers update this in `load()`/`shutdown()`;
    #: `ModelRegistry`/`ModelManager` read it via `status()`, never write it directly.
    _status: ModelStatus = ModelStatus.UNLOADED

    # ------------------------------------------------------------------
    # Required abstract identity properties
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique, machine-readable identifier (e.g. `"mock"`)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name (e.g. `"Mock Model"`)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def provider(self) -> str:
        """Name of the backend/vendor this model belongs to (e.g. `"mock"`, `"openai"`)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string for this provider integration, independent of the model's own version."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Optional overridable capability properties
    # ------------------------------------------------------------------

    @property
    def context_window(self) -> int:
        """Maximum number of tokens this model can accept as context. Defaults to unknown (0)."""
        return 0

    @property
    def supports_streaming(self) -> bool:
        """Whether `stream()` produces real incremental output instead of a single chunk."""
        return False

    @property
    def supports_tools(self) -> bool:
        """Whether this model can be handed tool/function-call schemas and request their use."""
        return False

    @property
    def supports_images(self) -> bool:
        """Whether this model accepts image input alongside text."""
        return False

    @property
    def supports_embeddings(self) -> bool:
        """Whether `embed()` is implemented for real, rather than raising `NotImplementedError`."""
        return False

    @property
    def supports_functions(self) -> bool:
        """Whether this model supports structured function-calling (distinct from generic tool use)."""
        return False

    # ------------------------------------------------------------------
    # Required abstract lifecycle / action methods
    # ------------------------------------------------------------------

    @abstractmethod
    def initialize(self) -> None:
        """
        Prepare this provider for use (validate config, warm caches, etc.).

        Called once by `ModelRegistry.register()`, before `load()`. Must not
        raise for a merely-not-yet-loaded model — only for genuinely invalid
        configuration.
        """
        raise NotImplementedError

    @abstractmethod
    def load(self) -> None:
        """
        Actually bring the model online (connect, open a session, load weights, etc.).

        Must set `self._status = ModelStatus.LOADED` on success. Only
        `ModelManager.load()` calls this directly.
        """
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> Any:
        """
        Generate a response for `prompt`.

        Returns the provider's own raw response shape (a dict, a client
        library's response object, etc.) — normalizing it into a
        provider-agnostic shape is `ResponseParser`'s job, not this method's.
        Implementations should raise if called before `load()`.
        """
        raise NotImplementedError

    @abstractmethod
    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """
        Generate a response for `prompt`, yielding text incrementally.

        Providers that don't support real streaming (`supports_streaming`
        is `False`) may implement this as a single-chunk generator — the
        contract only requires that iterating it yields the full text.
        """
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """
        Return an embedding vector for `text`.

        Milestone 5 explicitly does not implement embeddings for any
        provider — every concrete provider (including `MockModelProvider`)
        is expected to raise `NotImplementedError` here for now. The method
        exists so `ModelManager`/callers have a stable interface to call
        once a real implementation lands, gated by `supports_embeddings`.
        """
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        """
        Release any resources this provider is holding (connections, sessions, etc.).

        Must set `self._status = ModelStatus.UNLOADED`. Called by
        `ModelManager.unload()` / `ModelRegistry.unregister()`.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Concrete snapshot builders
    # ------------------------------------------------------------------

    def health(self) -> ModelHealth:
        """
        Return a health snapshot for this provider.

        Default implementation reports healthy iff currently loaded — good
        enough for a provider with no real backend to probe. Providers with
        a real backend (a future Ollama/OpenAI provider) should override
        this to perform an actual connectivity check.
        """
        status = self.status()
        return ModelHealth(
            healthy=status == ModelStatus.LOADED,
            status=status,
            message="OK" if status == ModelStatus.LOADED else f"Model is {status.value}.",
            checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def metadata(self) -> ModelMetadata:
        """Build a `ModelMetadata` snapshot of this provider's declared properties."""
        return ModelMetadata(
            id=self.id,
            name=self.name,
            provider=self.provider,
            version=self.version,
            context_window=self.context_window,
            supports_streaming=self.supports_streaming,
            supports_tools=self.supports_tools,
            supports_images=self.supports_images,
            supports_embeddings=self.supports_embeddings,
            supports_functions=self.supports_functions,
        )

    def status(self) -> ModelStatus:
        """Current lifecycle status. Managed by the provider's own `load()`/`shutdown()`."""
        return self._status
