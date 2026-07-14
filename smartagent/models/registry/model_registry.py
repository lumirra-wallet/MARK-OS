"""
ModelRegistry — Milestone 5, Part 2.

Holds every model provider currently known to SmartAgent, enabled or not.
Design and method surface deliberately mirror `ToolRegistry`/
`SkillRegistry`: register, unregister, find, list, reload, enable, disable,
health_check, statistics — plus `discover()`, which wraps
`model_loader.discover_provider_classes()` so `ModelManager` never imports
a concrete provider class itself (Part 11: only `ModelManager` talks to
providers, and even it only does so through instances this registry hands
back, not through provider imports scattered across the codebase).
"""

from __future__ import annotations

from typing import Any, Callable

from smartagent.logs.logger import get_logger
from smartagent.models.base.base_model import BaseModel, ModelStatus
from smartagent.models.registry.model_loader import DEFAULT_PROVIDERS_PACKAGE, discover_provider_classes

logger = get_logger(__name__)

ModelFactory = Callable[[], BaseModel]


class ModelRegistry:
    """Container for every registered `BaseModel` instance."""

    def __init__(self) -> None:
        self._models: dict[str, BaseModel] = {}
        self._factories: dict[str, ModelFactory] = {}
        self._enabled: dict[str, bool] = {}
        self._generation_count: dict[str, int] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, model: BaseModel, factory: ModelFactory | None = None) -> None:
        """
        Add `model` to the registry, enabled by default, and call its `initialize()` hook.

        Args:
            model: A `BaseModel` instance.
            factory: Zero-arg callable used by `reload()`. Defaults to `type(model)`.
        """
        self._models[model.id] = model
        self._factories[model.id] = factory or type(model)
        self._enabled[model.id] = True
        self._generation_count[model.id] = 0
        model.initialize()
        logger.info("Model registered: %s (%s, provider=%s v%s)", model.id, model.name, model.provider, model.version)

    def unregister(self, model_id: str) -> None:
        """Remove a model entirely and call its `shutdown()` hook. No-op if not registered."""
        model = self._models.pop(model_id, None)
        self._factories.pop(model_id, None)
        self._enabled.pop(model_id, None)
        self._generation_count.pop(model_id, None)
        if model is not None:
            model.shutdown()
            logger.info("Model unregistered: %s", model_id)

    def find(self, model_id: str) -> BaseModel | None:
        """Look up a single registered model by exact id, or `None` if not found."""
        return self._models.get(model_id)

    def list(self, enabled_only: bool = True) -> list[BaseModel]:
        """List registered models, optionally filtered to enabled-only (default: `True`)."""
        models = list(self._models.values())
        if enabled_only:
            models = [m for m in models if self._enabled.get(m.id, True)]
        return models

    def list_available(self) -> list[str]:
        """Ids of every registered model, enabled or not."""
        return list(self._models.keys())

    def reload(self, model_id: str) -> BaseModel | None:
        """
        Re-instantiate a model from its stored factory, replacing the old instance.

        Calls `shutdown()` on the old instance and `initialize()` on the new
        one. Preserves the model's current enabled/disabled status. Returns
        `None` if `model_id` is not registered.
        """
        factory = self._factories.get(model_id)
        if factory is None:
            return None
        old = self._models.get(model_id)
        if old is not None:
            old.shutdown()
        previous_enabled = self._enabled.get(model_id, True)
        fresh = factory()
        self._models[model_id] = fresh
        self._enabled[model_id] = previous_enabled
        fresh.initialize()
        logger.info("Model reloaded: %s", model_id)
        return fresh

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, package: str = DEFAULT_PROVIDERS_PACKAGE) -> list[str]:
        """
        Discover and register every built-in provider class found in `package`.

        Uses `model_loader.discover_provider_classes()` — no hardcoded
        imports. Returns the ids of every model registered this call.
        Providers already registered under the same id are left as-is
        (re-running `discover()` is idempotent, not destructive).
        """
        registered: list[str] = []
        for model_class in discover_provider_classes(package):
            model = model_class()
            if model.id in self._models:
                continue
            self.register(model)
            registered.append(model.id)
        return registered

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    def enable(self, model_id: str) -> bool:
        """Mark a registered model as enabled. Returns `False` if not registered."""
        if model_id not in self._models:
            return False
        self._enabled[model_id] = True
        logger.info("Model enabled: %s", model_id)
        return True

    def disable(self, model_id: str) -> bool:
        """Mark a registered model as disabled (excluded from `list(enabled_only=True)`)."""
        if model_id not in self._models:
            return False
        self._enabled[model_id] = False
        logger.info("Model disabled: %s", model_id)
        return True

    def is_enabled(self, model_id: str) -> bool:
        """Whether `model_id` is registered and currently enabled."""
        return self._enabled.get(model_id, False)

    # ------------------------------------------------------------------
    # Health and statistics
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """
        Collect a health snapshot for every registered model.

        Returns a dict mapping each model id to its `health()` output, plus
        a top-level `"healthy"` key that is `True` only if every enabled
        model reports healthy.
        """
        per_model: dict[str, Any] = {}
        all_healthy = True
        for model_id, model in self._models.items():
            health = model.health()
            per_model[model_id] = {
                "healthy": health.healthy,
                "status": health.status.value,
                "message": health.message,
                "checked_at": health.checked_at,
                "enabled": self._enabled.get(model_id, True),
            }
            if self._enabled.get(model_id, True) and not health.healthy:
                all_healthy = False
        return {"healthy": all_healthy, "models": per_model}

    def statistics(self) -> dict[str, Any]:
        """Return registry-level statistics: totals, per-model generation counts."""
        total = len(self._models)
        enabled = sum(1 for v in self._enabled.values() if v)
        loaded = sum(1 for m in self._models.values() if m.status() == ModelStatus.LOADED)
        return {
            "total": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "loaded": loaded,
            "generation_counts": dict(self._generation_count),
        }

    def record_generation(self, model_id: str) -> None:
        """Increment the generation counter for `model_id`. Called by `ModelManager`."""
        if model_id in self._generation_count:
            self._generation_count[model_id] += 1
