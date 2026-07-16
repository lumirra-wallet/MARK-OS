"""
Workspace — a named, persistent project context.

A Workspace is the isolation unit for Milestone 15.  When a workspace is
active every subsystem (memory, knowledge, execution history, output files,
and lessons) operates inside it, fully isolated from every other workspace
and from the global agent state.

Disk layout::

    workspaces/
      <name>/
        workspace.json   ← serialised Workspace metadata
        goals.md         ← append-only goal log
        memory/          ← scoped MemoryManager vault
        knowledge/       ← scoped KnowledgeManager store
        output/          ← files written by workers
        history/         ← one JSON per execution run
        LESSONS.md       ← distilled lessons from reflection cycles
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Valid workspace name: 3-63 chars, lowercase letters/digits/hyphens,
# no leading or trailing hyphens.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


def validate_workspace_name(name: str) -> None:
    """
    Raise ``ValueError`` if *name* is not a valid workspace slug.

    Rules:
        - Lowercase letters, digits, and hyphens only.
        - Between 3 and 63 characters.
        - Cannot start or end with a hyphen.

    Example valid names: ``"weather-api"``, ``"calculator"``, ``"my-project-v2"``.
    """
    if not name:
        raise ValueError("Workspace name cannot be empty.")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid workspace name {name!r}.  "
            "Must be 3–63 characters, lowercase letters/digits/hyphens, "
            "no leading or trailing hyphens.  Example: 'weather-api'"
        )


# ---------------------------------------------------------------------------
# WorkspaceStatus constants
# ---------------------------------------------------------------------------

class WorkspaceStatus:
    """String constants for workspace status (avoids enum import overhead)."""
    ACTIVE   = "active"
    IDLE     = "idle"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Workspace dataclass
# ---------------------------------------------------------------------------

@dataclass
class Workspace:
    """
    Represents one named project workspace.

    Args:
        name:         Slug identifier, e.g. ``"weather-api"``.
        path:         Absolute path to the workspace root directory.
        status:       ``WorkspaceStatus`` string — ``active | idle | archived``.
        created_at:   ISO-8601 timestamp when the workspace was created.
        modified_at:  ISO-8601 timestamp of the last state change.
        active_goal:  The most recently set goal (shown in status dashboards).
        goals:        All goals set on this workspace (append-only list).
        run_count:    Number of executions recorded.
        last_run_at:  ISO-8601 timestamp of the most recent execution.
        lesson_count: Number of lessons appended to LESSONS.md.
    """

    name:         str
    path:         str
    status:       str = WorkspaceStatus.IDLE
    created_at:   str = field(default_factory=_now_iso)
    modified_at:  str = field(default_factory=_now_iso)
    active_goal:  str = ""
    goals:        list[str] = field(default_factory=list)
    run_count:    int = 0
    last_run_at:  str = ""
    lesson_count: int = 0

    # ------------------------------------------------------------------
    # Computed path helpers — never serialised, always derived from self.path
    # ------------------------------------------------------------------

    @property
    def memory_path(self) -> str:
        """Scoped vault directory for this workspace's memories."""
        return os.path.join(self.path, "memory")

    @property
    def knowledge_path(self) -> str:
        """Scoped knowledge directory for this workspace's graph."""
        return os.path.join(self.path, "knowledge")

    @property
    def output_path(self) -> str:
        """Directory where workers write generated files."""
        return os.path.join(self.path, "output")

    @property
    def history_path(self) -> str:
        """Directory for per-execution JSON records."""
        return os.path.join(self.path, "history")

    @property
    def lessons_file(self) -> str:
        """LESSONS.md — distilled lessons from all reflection cycles."""
        return os.path.join(self.path, "LESSONS.md")

    @property
    def goals_file(self) -> str:
        """goals.md — append-only log of all goals set on this workspace."""
        return os.path.join(self.path, "goals.md")

    @property
    def metadata_file(self) -> str:
        """workspace.json — persisted metadata (read/written by WorkspaceStore)."""
        return os.path.join(self.path, "workspace.json")

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """Create all workspace subdirectories if they do not already exist."""
        for d in (
            self.path,
            self.memory_path,
            self.knowledge_path,
            self.output_path,
            self.history_path,
        ):
            os.makedirs(d, exist_ok=True)

    def file_count(self) -> int:
        """Return the total number of files in the ``output/`` directory."""
        if not os.path.isdir(self.output_path):
            return 0
        count = 0
        for _root, _dirs, files in os.walk(self.output_path):
            count += len(files)
        return count

    def history_count(self) -> int:
        """Return the number of execution history records."""
        if not os.path.isdir(self.history_path):
            return 0
        return len([f for f in os.listdir(self.history_path) if f.endswith(".json")])

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of persistent fields."""
        return {
            "name":         self.name,
            "status":       self.status,
            "created_at":   self.created_at,
            "modified_at":  self.modified_at,
            "active_goal":  self.active_goal,
            "goals":        self.goals,
            "run_count":    self.run_count,
            "last_run_at":  self.last_run_at,
            "lesson_count": self.lesson_count,
        }

    @classmethod
    def from_dict(cls, d: dict, path: str) -> "Workspace":
        """Reconstruct a ``Workspace`` from a stored dict and its directory *path*."""
        return cls(
            name=d.get("name", os.path.basename(path)),
            path=path,
            status=d.get("status", WorkspaceStatus.IDLE),
            created_at=d.get("created_at", _now_iso()),
            modified_at=d.get("modified_at", _now_iso()),
            active_goal=d.get("active_goal", ""),
            goals=d.get("goals", []),
            run_count=d.get("run_count", 0),
            last_run_at=d.get("last_run_at", ""),
            lesson_count=d.get("lesson_count", 0),
        )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def one_line_summary(self) -> str:
        """Single-line description for workspace list output."""
        goal_str = (
            f"\n    Goal : {self.active_goal[:60]}" if self.active_goal else ""
        )
        return (
            f"  {self.name:32s}  [{self.status:8s}]  "
            f"runs={self.run_count}  lessons={self.lesson_count}"
            f"{goal_str}"
        )

    def __repr__(self) -> str:
        return (
            f"Workspace(name={self.name!r}, status={self.status!r}, "
            f"run_count={self.run_count})"
        )
