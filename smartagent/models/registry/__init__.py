"""
Model registry — `ModelRegistry` and provider auto-discovery.

Mirrors `smartagent.tools.tool_registry`/`tool_loader`: `ModelRegistry`
holds every registered `BaseModel` instance (enabled or not), and
`model_loader.discover_provider_classes()` finds concrete provider classes
under `smartagent.models.providers` without any file hardcoding an import.
"""

from smartagent.models.registry.model_loader import DEFAULT_PROVIDERS_PACKAGE, discover_provider_classes
from smartagent.models.registry.model_registry import ModelRegistry

__all__ = ["DEFAULT_PROVIDERS_PACKAGE", "discover_provider_classes", "ModelRegistry"]
