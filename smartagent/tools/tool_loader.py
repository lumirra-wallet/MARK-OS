"""
Tool Loader — Milestone 4, Part 4.

Automatically discovers ``BaseTool`` subclasses under
``smartagent/tools/builtin/`` without any file needing to hardcode
``from smartagent.tools.builtin.x import XTool``.  Adding a new built-in
tool is just "drop a ``.py`` file defining a ``BaseTool`` subclass in the
correct category sub-package" — nothing else needs to change.

Key difference from ``SkillLoader``: tools are organised into sub-packages
(``filesystem/``, ``system/``, ``text/``, ``utilities/``) so we use
``pkgutil.walk_packages`` (recursive) rather than ``pkgutil.iter_modules``
(single-level).  This also means future third-party plugins in their own
sub-packages will be discovered automatically once they register themselves
as part of the ``smartagent.tools.builtin`` namespace.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from smartagent.logs.logger import get_logger
from smartagent.tools.base_tool import BaseTool

logger = get_logger(__name__)

#: Default package tools are auto-discovered from. A plain string (not an
#: import) so this module never imports any specific tool.
DEFAULT_TOOLS_PACKAGE = "smartagent.tools.builtin"


def discover_tool_classes(package: str = DEFAULT_TOOLS_PACKAGE) -> list[type[BaseTool]]:
    """
    Recursively import every module in ``package`` and return every concrete
    ``BaseTool`` subclass found there.

    Uses ``pkgutil.walk_packages`` (recursive) so sub-packages
    (``filesystem/``, ``system/``, etc.) are traversed automatically.

    Returns:
        A list of concrete (non-abstract) ``BaseTool`` subclasses, one per
        discovered class.  Classes that are merely *imported* into a module
        (re-exports from another file) are not double-counted — only classes
        whose ``__module__`` matches the module being inspected are included.
    """
    try:
        root = importlib.import_module(package)
    except ModuleNotFoundError:
        logger.warning("Tool package %r not found; nothing to discover.", package)
        return []

    discovered: list[type[BaseTool]] = []
    module_paths = getattr(root, "__path__", None)
    if module_paths is None:
        return discovered

    for module_info in pkgutil.walk_packages(module_paths, prefix=f"{package}."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not import tool module %s: %s", module_info.name, exc)
            continue

        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(candidate, BaseTool)
                and candidate is not BaseTool
                and not inspect.isabstract(candidate)
                and candidate.__module__ == module.__name__
            ):
                discovered.append(candidate)
                logger.info(
                    "Discovered tool class %s in %s", candidate.__name__, module_info.name
                )

    return discovered
