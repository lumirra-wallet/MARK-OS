"""
FileEditor — Milestone 19 + v2.0 upgrade.

Provides a tracked, scoped API for workers to create, edit, patch, delete,
move, and rename files within a base directory.  v2.0 adds:

  - ``preview()`` / ``diff()``    — show a unified diff without writing.
  - ``snapshot()``                — capture current state for rollback.
  - ``restore(snapshot)``         — revert to a captured snapshot.
  - ``move()`` / ``rename()``     — move/rename files within the base dir.
  - ``export_audit_log()``        — dump the edit history as JSON.

All operations are recorded in ``list_edits()`` so the console can report
exactly which files were created or modified during a run.

Usage::

    editor = FileEditor(base_dir="/workspaces/weather-api/output")

    editor.create("auth.py", "def login(): ...")
    editor.create("routes/api.py", "from fastapi import ...")
    editor.patch("auth.py", "def login():", "def login(username: str, password: str):")

    # Preview before committing a change
    print(editor.preview("auth.py", new_full_content))

    # Rollback support
    snap = editor.snapshot()
    editor.edit("auth.py", dangerous_change)
    editor.restore(snap)  # undone

    print(editor.summary())
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Literal

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

OperationType = Literal["create", "edit", "patch", "delete", "read", "move"]


@dataclass
class EditResult:
    """
    Result of one :class:`FileEditor` operation.

    Attributes:
        success:       Whether the operation completed without error.
        path:          The relative path within the editor's base directory.
        operation:     One of ``"create"``, ``"edit"``, ``"patch"``,
                       ``"delete"``, ``"read"``, ``"move"``.
        message:       Human-readable outcome or error description.
        bytes_written: Bytes written (0 for reads and deletes).
    """

    success: bool
    path: str
    operation: OperationType
    message: str
    bytes_written: int = 0

    def __str__(self) -> str:
        icon = "✓" if self.success else "✗"
        return f"{icon} [{self.operation}] {self.path} — {self.message}"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "path": self.path,
            "operation": self.operation,
            "message": self.message,
            "bytes_written": self.bytes_written,
        }


# ---------------------------------------------------------------------------
# Snapshot type alias
# ---------------------------------------------------------------------------

Snapshot = dict[str, str]  # relative_path → file_content


class FileEditor:
    """
    Scoped, tracked file editor with rollback and diff support.

    All paths passed to :meth:`create`, :meth:`edit`, :meth:`patch`,
    :meth:`delete`, :meth:`move`, and :meth:`rename` are resolved relative
    to *base_dir*.  Attempts to escape the base directory (via ``../``)
    raise :exc:`ValueError`.

    Args:
        base_dir: Root directory for all file operations.  Created if it
                  does not already exist.
    """

    def __init__(self, base_dir: str) -> None:
        self._base_dir = os.path.abspath(base_dir)
        os.makedirs(self._base_dir, exist_ok=True)
        self._edits: list[EditResult] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def base_dir(self) -> str:
        """Absolute path to the editor's root directory."""
        return self._base_dir

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def _resolve(self, path: str) -> str:
        """
        Resolve *path* relative to :attr:`base_dir`.

        Raises:
            ValueError: If *path* would escape the base directory.
        """
        full = os.path.normpath(os.path.join(self._base_dir, path))
        if not (full == self._base_dir or full.startswith(self._base_dir + os.sep)):
            raise ValueError(
                f"Path {path!r} would escape the editor's base directory "
                f"({self._base_dir!r})."
            )
        return full

    def _record(self, result: EditResult) -> EditResult:
        """Append *result* to the edit log and return it."""
        self._edits.append(result)
        return result

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create(self, path: str, content: str) -> EditResult:
        """
        Create a new file at *path* with *content*.

        If the file already exists it is overwritten.  Parent directories
        are created automatically.

        Returns:
            :class:`EditResult` with ``operation="create"``.
        """
        try:
            full = self._resolve(path)
            parent = os.path.dirname(full)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            bytes_written = len(content.encode("utf-8"))
            logger.info("FileEditor.create: %s (%d bytes)", full, bytes_written)
            return self._record(EditResult(
                success=True,
                path=path,
                operation="create",
                message=f"{bytes_written} bytes written",
                bytes_written=bytes_written,
            ))
        except (ValueError, OSError) as exc:
            logger.warning("FileEditor.create failed: %s — %s", path, exc)
            return self._record(EditResult(
                success=False,
                path=path,
                operation="create",
                message=str(exc),
            ))

    def edit(self, path: str, content: str) -> EditResult:
        """
        Overwrite the entire content of a file at *path*.

        Parent directories are created if they do not exist.

        Returns:
            :class:`EditResult` with ``operation="edit"``.
        """
        try:
            full = self._resolve(path)
            parent = os.path.dirname(full)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
            bytes_written = len(content.encode("utf-8"))
            logger.info("FileEditor.edit: %s (%d bytes)", full, bytes_written)
            return self._record(EditResult(
                success=True,
                path=path,
                operation="edit",
                message=f"{bytes_written} bytes written",
                bytes_written=bytes_written,
            ))
        except (ValueError, OSError) as exc:
            logger.warning("FileEditor.edit failed: %s — %s", path, exc)
            return self._record(EditResult(
                success=False,
                path=path,
                operation="edit",
                message=str(exc),
            ))

    def patch(self, path: str, old_text: str, new_text: str) -> EditResult:
        """
        Replace the first occurrence of *old_text* with *new_text* in *path*.

        Args:
            path:     Relative path of the file to patch.
            old_text: Exact text to find and replace.
            new_text: Replacement text.

        Returns:
            :class:`EditResult` with ``operation="patch"``.
        """
        try:
            full = self._resolve(path)
            with open(full, "r", encoding="utf-8") as f:
                original = f.read()
            if old_text not in original:
                raise ValueError(
                    f"old_text not found in {path!r}.  "
                    f"First 50 chars: {old_text[:50]!r}"
                )
            patched = original.replace(old_text, new_text, 1)
            with open(full, "w", encoding="utf-8") as f:
                f.write(patched)
            diff = len(new_text) - len(old_text)
            sign = "+" if diff >= 0 else ""
            logger.info("FileEditor.patch: %s (diff=%s%d bytes)", full, sign, diff)
            return self._record(EditResult(
                success=True,
                path=path,
                operation="patch",
                message=f"patched ({sign}{diff} bytes)",
                bytes_written=len(patched.encode("utf-8")),
            ))
        except (ValueError, OSError) as exc:
            logger.warning("FileEditor.patch failed: %s — %s", path, exc)
            return self._record(EditResult(
                success=False,
                path=path,
                operation="patch",
                message=str(exc),
            ))

    def delete(self, path: str) -> EditResult:
        """
        Delete the file at *path*.

        Returns:
            :class:`EditResult` with ``operation="delete"``.
        """
        try:
            full = self._resolve(path)
            if not os.path.exists(full):
                raise FileNotFoundError(f"No such file: {path!r}")
            os.remove(full)
            logger.info("FileEditor.delete: %s", full)
            return self._record(EditResult(
                success=True,
                path=path,
                operation="delete",
                message="deleted",
            ))
        except (ValueError, OSError) as exc:
            logger.warning("FileEditor.delete failed: %s — %s", path, exc)
            return self._record(EditResult(
                success=False,
                path=path,
                operation="delete",
                message=str(exc),
            ))

    def move(self, src: str, dst: str) -> EditResult:
        """
        Move (or rename) *src* to *dst* within :attr:`base_dir`.

        Both paths are resolved relative to the base directory.  Parent
        directories of *dst* are created automatically.

        Returns:
            :class:`EditResult` with ``operation="move"``.
        """
        try:
            full_src = self._resolve(src)
            full_dst = self._resolve(dst)
            if not os.path.exists(full_src):
                raise FileNotFoundError(f"Source not found: {src!r}")
            parent_dst = os.path.dirname(full_dst)
            if parent_dst:
                os.makedirs(parent_dst, exist_ok=True)
            shutil.move(full_src, full_dst)
            logger.info("FileEditor.move: %s → %s", full_src, full_dst)
            return self._record(EditResult(
                success=True,
                path=dst,
                operation="move",
                message=f"moved from {src!r} to {dst!r}",
            ))
        except (ValueError, OSError) as exc:
            logger.warning("FileEditor.move failed: %s → %s — %s", src, dst, exc)
            return self._record(EditResult(
                success=False,
                path=src,
                operation="move",
                message=str(exc),
            ))

    def rename(self, src: str, dst: str) -> EditResult:
        """
        Rename *src* to *dst* — alias for :meth:`move`.

        Returns:
            :class:`EditResult` with ``operation="move"``.
        """
        return self.move(src, dst)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def read(self, path: str) -> str:
        """
        Read and return the content of *path*.

        Raises:
            FileNotFoundError: If the file does not exist.
            OSError:           On other filesystem errors.
        """
        full = self._resolve(path)
        with open(full, "r", encoding="utf-8") as f:
            return f.read()

    def exists(self, path: str) -> bool:
        """Return True if *path* exists within the base directory."""
        try:
            full = self._resolve(path)
            return os.path.isfile(full)
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Preview and diff (non-destructive)
    # ------------------------------------------------------------------

    def preview(self, path: str, new_content: str) -> str:
        """
        Return a unified-diff string showing what :meth:`edit` would change
        *without* modifying the file.

        If *path* does not exist yet the diff shows the full new content as
        additions (``+`` lines).

        Args:
            path:        Relative path to the file.
            new_content: Proposed new content.

        Returns:
            Unified diff as a single string (empty if no changes).
        """
        try:
            current = self.read(path)
        except (FileNotFoundError, OSError):
            current = ""
        return _unified_diff(path, current, new_content)

    def diff(self, path: str, new_content: str) -> str:
        """Alias for :meth:`preview` — returns a unified diff."""
        return self.preview(path, new_content)

    # ------------------------------------------------------------------
    # Snapshot / rollback
    # ------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        """
        Capture the current state of all files in :attr:`base_dir`.

        Returns:
            A ``{relative_path: content}`` dict.  Paths use forward slashes.
        """
        snap: Snapshot = {}
        for rel in self.list_files():
            try:
                snap[rel] = self.read(rel)
            except OSError:
                pass
        logger.info("FileEditor.snapshot: captured %d file(s)", len(snap))
        return snap

    def restore(self, snapshot: Snapshot) -> list[EditResult]:
        """
        Restore the editor's base directory to the state captured by
        :meth:`snapshot`.

        Files that existed in the snapshot are re-written with their captured
        content.  Files that exist now but were absent from the snapshot are
        deleted.  Failures are recorded but do not abort the restore.

        Args:
            snapshot: A dict returned by :meth:`snapshot`.

        Returns:
            List of :class:`EditResult` objects for every write/delete.
        """
        results: list[EditResult] = []

        # Re-write files from the snapshot
        for rel, content in snapshot.items():
            r = self.edit(rel, content)
            results.append(r)

        # Delete files that weren't in the snapshot
        for current_file in self.list_files():
            if current_file not in snapshot:
                r = self.delete(current_file)
                results.append(r)

        logger.info(
            "FileEditor.restore: %d write(s), %d delete(s)",
            len(snapshot),
            len(results) - len(snapshot),
        )
        return results

    # ------------------------------------------------------------------
    # Audit log export
    # ------------------------------------------------------------------

    def export_audit_log(self) -> str:
        """
        Return the full edit history as a JSON string.

        Each entry is a dict with keys:
        ``success``, ``path``, ``operation``, ``message``, ``bytes_written``.
        """
        return json.dumps([e.to_dict() for e in self._edits], indent=2)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def list_files(self) -> list[str]:
        """
        Return all files in :attr:`base_dir` recursively, relative to it.

        Paths use forward slashes regardless of OS.
        """
        result: list[str] = []
        if not os.path.isdir(self._base_dir):
            return result
        for root, _dirs, files in os.walk(self._base_dir):
            for fname in files:
                full = os.path.join(root, fname)
                rel  = os.path.relpath(full, self._base_dir)
                result.append(rel.replace("\\", "/"))
        return sorted(result)

    def list_edits(self) -> list[EditResult]:
        """Return all edit operations recorded in this session."""
        return list(self._edits)

    def written_files(self) -> list[str]:
        """
        Return the paths of files successfully written (created or edited)
        in this session, in the order they were first written.
        """
        seen: set[str] = set()
        result: list[str] = []
        for edit in self._edits:
            if edit.success and edit.operation in ("create", "edit", "patch"):
                if edit.path not in seen:
                    seen.add(edit.path)
                    result.append(edit.path)
        return result

    def total_bytes_written(self) -> int:
        """Return the total bytes written across all successful write operations."""
        return sum(
            e.bytes_written for e in self._edits
            if e.success and e.operation in ("create", "edit")
        )

    def summary(self) -> str:
        """Return a one-line summary of all write operations."""
        written = self.written_files()
        if not written:
            return "No files written."
        names = ", ".join(written[:5])
        suffix = f" (and {len(written) - 5} more)" if len(written) > 5 else ""
        return f"{len(written)} file(s) written: {names}{suffix}"

    def __repr__(self) -> str:
        return (
            f"FileEditor(base_dir={self._base_dir!r}, "
            f"edits={len(self._edits)}, files={len(self.list_files())})"
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _unified_diff(path: str, original: str, new: str) -> str:
    """Return a unified diff string between *original* and *new*."""
    a_lines = original.splitlines(keepends=True)
    b_lines = new.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(
        a_lines, b_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    ))
    return "\n".join(diff_lines)
