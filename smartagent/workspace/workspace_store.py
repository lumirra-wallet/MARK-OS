"""
WorkspaceStore — disk persistence for Workspace metadata.

Each workspace lives under ``<base_path>/<name>/`` and has a single
``workspace.json`` file holding its mutable state.  All directory creation
is handled here; callers never touch the filesystem directly.
"""

from __future__ import annotations

import json
import os
import shutil

from smartagent.logs.logger import get_logger
from smartagent.workspace.workspace import Workspace, _now_iso

logger = get_logger(__name__)


class WorkspaceStore:
    """
    Read/write workspace metadata to and from disk.

    Args:
        base_path: Root directory that contains all workspace subdirectories.
                   Created automatically if it does not exist.
    """

    def __init__(self, base_path: str = "workspaces") -> None:
        self._base_path = os.path.abspath(base_path)
        os.makedirs(self._base_path, exist_ok=True)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def base_path(self) -> str:
        """Absolute path to the workspace root directory."""
        return self._base_path

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def workspace_dir(self, name: str) -> str:
        """Return the absolute path to the directory for workspace *name*."""
        return os.path.join(self._base_path, name)

    def _meta_file(self, name: str) -> str:
        return os.path.join(self.workspace_dir(name), "workspace.json")

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def exists(self, name: str) -> bool:
        """Return True if a workspace named *name* has a metadata file on disk."""
        return os.path.isfile(self._meta_file(name))

    def save(self, workspace: Workspace) -> None:
        """
        Persist *workspace* metadata to ``<path>/workspace.json``.

        Uses an atomic write (write to ``.tmp`` then ``os.replace``) so a
        crash during save never leaves a corrupt metadata file.

        Raises:
            OSError: On filesystem errors.
        """
        workspace.ensure_dirs()
        workspace.modified_at = _now_iso()
        data = workspace.to_dict()
        path = workspace.metadata_file
        tmp  = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, path)
            logger.debug("WorkspaceStore.save: %r → %s", workspace.name, path)
        except OSError as exc:
            logger.error("WorkspaceStore.save: failed for %r: %s", workspace.name, exc)
            raise

    def load(self, name: str) -> Workspace:
        """
        Load and return the workspace named *name*.

        Raises:
            FileNotFoundError: if the workspace does not exist on disk.
            ValueError:        if ``workspace.json`` is not valid JSON.
        """
        meta = self._meta_file(name)
        if not os.path.isfile(meta):
            raise FileNotFoundError(f"Workspace {name!r} not found in {self._base_path!r}.")
        with open(meta, "r", encoding="utf-8") as f:
            data = json.load(f)
        ws = Workspace.from_dict(data, path=self.workspace_dir(name))
        logger.debug("WorkspaceStore.load: %r from %s", name, self.workspace_dir(name))
        return ws

    def list_names(self) -> list[str]:
        """
        Return a sorted list of all workspace names stored under *base_path*.

        Only directories that contain a ``workspace.json`` file are included.
        """
        names: list[str] = []
        if not os.path.isdir(self._base_path):
            return names
        for entry in sorted(os.scandir(self._base_path), key=lambda e: e.name):
            if entry.is_dir() and os.path.isfile(
                os.path.join(entry.path, "workspace.json")
            ):
                names.append(entry.name)
        return names

    def delete(self, name: str) -> None:
        """
        Delete the workspace directory ``<base_path>/<name>/`` and all its contents.

        Raises:
            FileNotFoundError: if the workspace directory does not exist.
        """
        ws_dir = self.workspace_dir(name)
        if not os.path.isdir(ws_dir):
            raise FileNotFoundError(f"Workspace {name!r} not found.")
        shutil.rmtree(ws_dir)
        logger.info("WorkspaceStore.delete: removed %r", name)
