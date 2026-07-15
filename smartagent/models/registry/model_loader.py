"""
Model Loader — Milestone 5, Part 4 (Provider discovery).

Automatically discovers `BaseModel` subclasses under
`smartagent/models/providers/` without any file hardcoding
`from smartagent.models.providers.x import XModel`. Adding a new built-in
provider is just "drop a `.py` file defining a concrete `BaseModel`
subclass in that package" — nothing else needs to change.

Mirrors `smartagent.skills.skill_loader.discover_skill_classes()`: a flat
package (no sub-packages, unlike `tools/builtin/`), so `pkgutil.iter_modules`
(single-level) is enough. `future_providers.py`'s classes are deliberately
left abstract (see that module's docstring) so `inspect.isabstract()`
excludes them here automatically — no separate "future" package needed.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from smartagent.logs.logger import get_logger
from smartagent.models.base.base_model import BaseModel

logger = get_logger(__name__)

#: Default package providers are auto-discovered from. A plain string (not
#: an import) so this module never has to import any specific provider.
DEFAULT_PROVIDERS_PACKAGE = "smartagent.models.providers"


def discover_provider_classes(package: str = DEFAULT_PROVIDERS_PACKAGE) -> list[type[BaseModel]]:
    """
    Import every module in `package` and return every concrete `BaseModel` subclass found.

    Returns classes, not instances — `ModelManager`/`ModelRegistry` decide
    how to instantiate them. Abstract subclasses (the design-only future
    provider stubs) are skipped automatically since they cannot be
    instantiated anyway.
    """
    try:
        root = importlib.import_module(package)
    except ModuleNotFoundError:
        logger.warning("Model provider package %r not found; nothing to discover.", package)
        return []

    discovered: list[type[BaseModel]] = []
    module_paths = getattr(root, "__path__", None)
    if module_paths is None:
        return discovered

    for module_info in pkgutil.iter_modules(module_paths, prefix=f"{package}."):
        module = importlib.import_module(module_info.name)
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(candidate, BaseModel)
                and candidate is not BaseModel
                and not inspect.isabstract(candidate)
                and candidate.__module__ == module.__name__
                # Respect the opt-out marker — providers that manage their own
                # registration (e.g. OllamaProvider, which needs per-model-name
                # instances) set ``_exclude_from_discovery = True`` on the class.
                and not getattr(candidate, "_exclude_from_discovery", False)
            ):
                discovered.append(candidate)
                logger.info("Discovered model provider class %s in %s", candidate.__name__, module_info.name)
    return discovered
