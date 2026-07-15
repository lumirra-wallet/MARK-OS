"""
Skill Loader — Milestone 3, Part 7.

Automatically discovers skill classes under `smartagent/skills/builtin/`
without any file having to hardcode `from smartagent.skills.builtin.x
import XSkill`. Adding a new built-in skill is then just "drop a new
`*.py` file defining a `BaseSkill` subclass in that folder" — nothing
else needs to change.

Uses `pkgutil.iter_modules` + `importlib` (standard library only, no new
dependency) to walk the package, then `inspect.getmembers` to find
`BaseSkill` subclasses defined *in* each discovered module (not merely
imported into it, which would otherwise double-count re-exports).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from smartagent.logs.logger import get_logger
from smartagent.skills.base_skill import BaseSkill

logger = get_logger(__name__)

#: Default package skills are auto-discovered from. A plain string (not
#: an import) so this module never has to import any specific skill.
DEFAULT_SKILLS_PACKAGE = "smartagent.skills.builtin"


def discover_skill_classes(package: str = DEFAULT_SKILLS_PACKAGE) -> list[type[BaseSkill]]:
    """
    Import every module in `package` and return every concrete `BaseSkill` subclass found.

    Returns classes, not instances — callers (typically `SkillEngine`)
    decide how to instantiate them (built-ins all take no constructor
    arguments, but this loader makes no assumption about that).
    """
    try:
        root = importlib.import_module(package)
    except ModuleNotFoundError:
        logger.warning("Skill package %r not found; nothing to discover.", package)
        return []

    discovered: list[type[BaseSkill]] = []
    module_paths = getattr(root, "__path__", None)
    if module_paths is None:
        return discovered

    for module_info in pkgutil.iter_modules(module_paths, prefix=f"{package}."):
        module = importlib.import_module(module_info.name)
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(candidate, BaseSkill)
                and candidate is not BaseSkill
                and not inspect.isabstract(candidate)
                and candidate.__module__ == module.__name__
            ):
                discovered.append(candidate)
                logger.info("Discovered skill class %s in %s", candidate.__name__, module_info.name)
    return discovered
