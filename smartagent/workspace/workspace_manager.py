"""
WorkspaceManager — CRUD and active-workspace lifecycle for Milestone 15.

This is the single facade for all workspace operations.  Console commands,
the Orchestrator, and the ReflectionEngine talk to this class rather than
directly to WorkspaceStore or the filesystem.

Responsibilities:
    - Create, open, close, delete, list, and export workspaces.
    - Track the single *active* workspace that receives goals, plans, and
      execution history.
    - Cache per-workspace scoped service instances (MemoryManager,
      KnowledgeManager) so they are created once per session and re-used
      across multiple runs in the same workspace.
    - Record execution history and append lessons to LESSONS.md after each
      reflection cycle.
"""

from __future__ import annotations

import json
import os
from typing import Any

from smartagent.logs.logger import get_logger
from smartagent.workspace.workspace import (
    Workspace,
    WorkspaceStatus,
    _now_iso,
    validate_workspace_name,
)
from smartagent.workspace.workspace_store import WorkspaceStore

logger = get_logger(__name__)


class WorkspaceError(Exception):
    """Raised by WorkspaceManager for user-facing workspace errors."""


class WorkspaceManager:
    """
    CRUD and active-workspace lifecycle manager.

    Args:
        base_path: Root directory that holds all workspace subdirectories.
                   Defaults to ``"workspaces"`` (relative to cwd).
    """

    def __init__(self, base_path: str = "workspaces") -> None:
        self._store = WorkspaceStore(base_path)
        self._active: Workspace | None = None
        # Scoped service caches keyed by workspace name.
        # Lazily populated on first access so WorkspaceManager itself stays
        # free of MemoryManager / KnowledgeManager at import time.
        self._scoped_memory:    dict[str, Any] = {}
        self._scoped_knowledge: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def base_path(self) -> str:
        """Absolute path to the workspace root directory."""
        return self._store.base_path

    @property
    def active(self) -> Workspace | None:
        """The currently active workspace, or ``None`` if none is open."""
        return self._active

    # ------------------------------------------------------------------
    # Scoped service access (used by Orchestrator._inject_services)
    # ------------------------------------------------------------------

    def active_memory(self) -> Any | None:
        """
        Return a ``MemoryManager`` scoped to the active workspace.

        Created on first call and cached for the lifetime of the session.
        Returns ``None`` if no workspace is active.
        """
        if self._active is None:
            return None
        name = self._active.name
        if name not in self._scoped_memory:
            from smartagent.memory.memory_manager import MemoryManager
            self._scoped_memory[name] = MemoryManager(
                vault_path=self._active.memory_path
            )
            logger.debug(
                "WorkspaceManager: created scoped MemoryManager for %r at %s",
                name, self._active.memory_path,
            )
        return self._scoped_memory[name]

    def active_knowledge(self) -> Any | None:
        """
        Return a ``KnowledgeManager`` scoped to the active workspace.

        Created on first call and cached for the lifetime of the session.
        Returns ``None`` if no workspace is active.
        """
        if self._active is None:
            return None
        name = self._active.name
        if name not in self._scoped_knowledge:
            from smartagent.knowledge.knowledge_manager import KnowledgeManager
            self._scoped_knowledge[name] = KnowledgeManager(
                knowledge_path=self._active.knowledge_path
            )
            logger.debug(
                "WorkspaceManager: created scoped KnowledgeManager for %r at %s",
                name, self._active.knowledge_path,
            )
        return self._scoped_knowledge[name]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, name: str) -> Workspace:
        """
        Create a new workspace named *name* on disk and return it.

        Does NOT activate it — call ``activate(name)`` separately.

        Raises:
            ValueError:     If *name* fails validation.
            WorkspaceError: If a workspace with that name already exists.
        """
        validate_workspace_name(name)
        if self._store.exists(name):
            raise WorkspaceError(
                f"Workspace {name!r} already exists.  "
                f"Use 'workspace open {name}' to switch to it."
            )
        ws_dir = self._store.workspace_dir(name)
        ws = Workspace(name=name, path=ws_dir, status=WorkspaceStatus.IDLE)
        ws.ensure_dirs()
        self._store.save(ws)
        logger.info("WorkspaceManager.create: %r at %s", name, ws_dir)
        return ws

    def activate(self, name: str) -> Workspace:
        """
        Load workspace *name* from disk and make it the active workspace.

        If another workspace is currently active it is first set to IDLE and
        saved, but its scoped service cache is preserved in memory.

        Raises:
            WorkspaceError: If the workspace does not exist on disk.
        """
        if not self._store.exists(name):
            raise WorkspaceError(
                f"Workspace {name!r} does not exist.  "
                f"Use 'workspace create {name}' to create it."
            )
        # Idle out the previous workspace without clearing its service cache
        if self._active is not None and self._active.name != name:
            self._active.status = WorkspaceStatus.IDLE
            self._store.save(self._active)

        ws = self._store.load(name)
        ws.status = WorkspaceStatus.ACTIVE
        self._store.save(ws)
        self._active = ws
        logger.info("WorkspaceManager.activate: %r", name)
        return ws

    def deactivate(self) -> None:
        """
        Deactivate the current workspace, returning to the global context.

        A no-op if no workspace is currently active.
        """
        if self._active is None:
            return
        name = self._active.name
        self._active.status = WorkspaceStatus.IDLE
        self._store.save(self._active)
        self._active = None
        logger.info("WorkspaceManager.deactivate: %r closed", name)

    def get(self, name: str) -> Workspace | None:
        """Return workspace *name* loaded from disk, or ``None`` if it doesn't exist."""
        if not self._store.exists(name):
            return None
        try:
            return self._store.load(name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("WorkspaceManager.get: could not load %r: %s", name, exc)
            return None

    def exists(self, name: str) -> bool:
        """Return True if workspace *name* exists on disk."""
        return self._store.exists(name)

    def list_workspaces(self) -> list[Workspace]:
        """
        Return all workspaces loaded from disk, sorted alphabetically.

        The in-memory ``active`` status is reflected even if the on-disk
        record still shows ``idle``.
        """
        result: list[Workspace] = []
        for name in self._store.list_names():
            try:
                ws = self._store.load(name)
                if self._active and ws.name == self._active.name:
                    ws.status = WorkspaceStatus.ACTIVE
                result.append(ws)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "WorkspaceManager.list_workspaces: skipping %r: %s", name, exc
                )
        return result

    def delete(self, name: str, force: bool = False) -> None:
        """
        Delete workspace *name* and all its contents from disk.

        Args:
            name:  Workspace to delete.
            force: If ``True``, deactivate and delete even if *name* is the
                   currently active workspace.

        Raises:
            WorkspaceError: If the workspace is active and ``force=False``.
            WorkspaceError: If the workspace does not exist.
        """
        if not self._store.exists(name):
            raise WorkspaceError(f"Workspace {name!r} does not exist.")
        if self._active and self._active.name == name:
            if not force:
                raise WorkspaceError(
                    f"Workspace {name!r} is currently active.  "
                    "Use 'workspace close' first, or pass force=True."
                )
            self._active = None
        self._store.delete(name)
        self._scoped_memory.pop(name, None)
        self._scoped_knowledge.pop(name, None)
        logger.info("WorkspaceManager.delete: %r removed", name)

    # ------------------------------------------------------------------
    # Goal management
    # ------------------------------------------------------------------

    def set_goal(self, goal: str) -> None:
        """
        Set the active goal on the current workspace and persist it.

        Also appends the goal to ``goals.md`` with a timestamp.

        Raises:
            WorkspaceError: If no workspace is active.
        """
        if self._active is None:
            raise WorkspaceError(
                "No workspace is active.  "
                "Use 'workspace create <name>' or 'workspace open <name>' first."
            )
        self._active.active_goal = goal
        if goal not in self._active.goals:
            self._active.goals.append(goal)
        self._store.save(self._active)
        # Append to goals.md
        try:
            with open(self._active.goals_file, "a", encoding="utf-8") as f:
                f.write(f"\n## {_now_iso()}\n\n{goal}\n")
        except OSError as exc:
            logger.warning(
                "WorkspaceManager.set_goal: could not append to goals.md: %s", exc
            )

    # ------------------------------------------------------------------
    # Execution recording
    # ------------------------------------------------------------------

    def record_execution(
        self,
        context: Any,
        reflection_result: Any = None,
    ) -> None:
        """
        Save an execution context as a history record in the active workspace.

        Increments ``run_count``, updates ``last_run_at``, and writes a JSON
        file to ``history/<plan_id>.json``.  If *reflection_result* has a
        non-empty ``plan.memory_entries`` list, those entries are also
        appended to ``LESSONS.md``.

        A no-op if no workspace is currently active.
        """
        if self._active is None:
            return
        ws = self._active

        # Build the JSON record
        state_val = ""
        raw_state = getattr(context, "state", None)
        if raw_state is not None:
            state_val = raw_state.value if hasattr(raw_state, "value") else str(raw_state)

        record: dict[str, Any] = {
            "plan_id":    getattr(context, "plan_id",        ""),
            "goal":       getattr(context, "goal",           ""),
            "state":      state_val,
            "created_at": getattr(context, "created_at",     ""),
            "ended_at":   getattr(context, "ended_at",       ""),
            "task_count": getattr(context, "task_count",      0),
            "completed":  getattr(context, "completed_count", 0),
            "failed":     getattr(context, "failed_count",    0),
        }
        if reflection_result is not None:
            critic = getattr(reflection_result, "critic", None)
            record["reflection"] = {
                "score":          getattr(critic, "overall_score",     0.0) if critic else 0.0,
                "memory_entries": getattr(reflection_result, "memory_entries_added",  0),
                "prompt_versions": getattr(reflection_result, "prompt_versions_added", 0),
            }

        # Write to history/<plan_id>.json
        plan_id = record["plan_id"] or _now_iso().replace(":", "-")
        hist_file = os.path.join(ws.history_path, f"{plan_id}.json")
        try:
            os.makedirs(ws.history_path, exist_ok=True)
            with open(hist_file, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except OSError as exc:
            logger.warning(
                "WorkspaceManager.record_execution: could not write history: %s", exc
            )

        # Update workspace metadata counters
        ws.run_count  += 1
        ws.last_run_at = _now_iso()
        self._store.save(ws)

        # Persist lessons if the improvement plan has entries
        if reflection_result is not None:
            plan    = getattr(reflection_result, "plan", None)
            entries = getattr(plan, "memory_entries", []) if plan else []
            if entries:
                self.append_lessons(entries)

        logger.info(
            "WorkspaceManager.record_execution: recorded run #%d for %r",
            ws.run_count, ws.name,
        )

    def append_lessons(self, entries: list) -> None:
        """
        Append *entries* (``ImprovementPlanner`` memory entries) to ``LESSONS.md``.

        Each entry's ``.content`` attribute (or ``str(entry)``) is written as
        a bullet point under a timestamped heading.  A no-op if no workspace
        is active or *entries* is empty.
        """
        if self._active is None or not entries:
            return
        ws = self._active
        try:
            with open(ws.lessons_file, "a", encoding="utf-8") as f:
                f.write(f"\n## {_now_iso()}\n\n")
                for entry in entries:
                    content = getattr(entry, "content", str(entry))
                    f.write(f"- {content}\n")
            ws.lesson_count += len(entries)
            self._store.save(ws)
            logger.info(
                "WorkspaceManager.append_lessons: +%d lessons → %s",
                len(entries), ws.lessons_file,
            )
        except OSError as exc:
            logger.warning(
                "WorkspaceManager.append_lessons: could not write LESSONS.md: %s", exc
            )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_zip(self, name: str) -> str:
        """
        Archive workspace *name* to a ``.zip`` file in *base_path*.

        Returns:
            Absolute path to the created archive.

        Raises:
            WorkspaceError: If the workspace does not exist.
        """
        import shutil
        if not self._store.exists(name):
            raise WorkspaceError(f"Workspace {name!r} does not exist.")
        ws_dir     = self._store.workspace_dir(name)
        out_prefix = os.path.join(self._store.base_path, f"{name}-export")
        archive    = shutil.make_archive(out_prefix, "zip", ws_dir)
        logger.info("WorkspaceManager.export_zip: %r → %s", name, archive)
        return archive
