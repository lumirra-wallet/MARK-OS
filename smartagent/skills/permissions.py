"""
Permission model — Milestone 3, Part 6.

Every skill declares the permissions it needs to run (see
`smartagent.skills.base_skill.BaseSkill.permissions`). `PermissionManager`
is the single authority that decides whether a given permission is
currently granted. The core rule, straight from the spec: **nothing is
granted automatically** — a skill that declares `NETWORK_ACCESS` stays
unusable until something explicitly grants it, even if the skill itself
is otherwise perfectly correct.

Design decision: granted permissions are a deliberately small, static set
configured via `Settings.granted_permissions` (see `smartagent.config`)
rather than an interactive "approve this request" flow — there is no UI
layer yet to ask the owner in the moment, and Milestone 3 explicitly rules
out adding new, unrelated features. `SmartAgent`'s default
`Settings.granted_permissions` only grants `READ_MEMORY`/`WRITE_MEMORY` —
the minimum first-party built-in skills need — so every other permission
(network access, system commands, automation, file access, running
tools) starts denied until an owner deliberately opts in.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


class Permission(str, Enum):
    """
    The fixed set of permissions a skill or tool can request.

    Milestone 3 (Part 6) defined the original seven. Milestone 4 adds five
    tool-specific permissions that map to the concrete filesystem and system
    operations built-in tools perform. All are subject to the same
    "nothing granted automatically" rule — only `read_memory` and
    `write_memory` are in the default grant list.
    """

    # ---- Memory (Milestone 3) ----------------------------------------
    READ_MEMORY = "read_memory"
    WRITE_MEMORY = "write_memory"

    # ---- Tool execution control (Milestone 3) ------------------------
    RUN_TOOLS = "run_tools"
    ACCESS_FILES = "access_files"         # coarse "can touch the filesystem" gate

    # ---- Network / automation / system (Milestone 3) -----------------
    NETWORK_ACCESS = "network_access"
    AUTOMATION = "automation"
    SYSTEM_COMMANDS = "system_commands"

    # ---- Fine-grained filesystem permissions (Milestone 4) -----------
    READ_FILES = "read_files"             # open & read file contents
    WRITE_FILES = "write_files"           # create or overwrite files
    DELETE_FILES = "delete_files"         # permanently remove files
    CREATE_DIRECTORIES = "create_directories"   # mkdir (incl. parents)

    # ---- System introspection (Milestone 4) --------------------------
    READ_SYSTEM_INFO = "read_system_info"  # OS info, env vars, platform details


class PermissionManager:
    """
    Tracks which `Permission`s are currently granted, system-wide.

    Deliberately simple (a set of granted permissions, checked on every
    skill execution) — no per-skill grants yet, since no concrete skill
    needs different treatment from another with the same declared
    permission. That refinement is a natural extension point once a
    skill needs a permission other built-in skills shouldn't have.
    """

    def __init__(self, granted: Iterable[Permission] | None = None) -> None:
        self._granted: set[Permission] = set(granted or [])

    def grant(self, permission: Permission) -> None:
        """Explicitly grant `permission`. Never happens implicitly/automatically."""
        self._granted.add(permission)
        logger.info("Permission granted: %s", permission.value)

    def revoke(self, permission: Permission) -> None:
        """Revoke a previously granted permission."""
        self._granted.discard(permission)
        logger.info("Permission revoked: %s", permission.value)

    def is_granted(self, permission: Permission) -> bool:
        """Whether `permission` is currently granted."""
        return permission in self._granted

    def missing(self, required: Iterable[Permission]) -> list[Permission]:
        """Return the subset of `required` that is NOT currently granted."""
        return [permission for permission in required if permission not in self._granted]

    def granted_permissions(self) -> list[Permission]:
        """Return every permission currently granted."""
        return list(self._granted)
