"""
FileEditor — Milestone 19: File Editing Engine.

Provides a tracked, scoped API for workers to create, edit, patch, and delete
files within a base directory (typically a workspace's ``output/`` directory).

All operations are recorded in ``list_edits()`` so the console can report
exactly which files were created or modified during a run.

Usage::

    editor = FileEditor(base_dir="/workspaces/weather-api/output")

    editor.create("auth.py", "def login(): ...")
    editor.create("routes/api.py", "from fastapi import ...")
    editor.patch("auth.py", "def login():", "def login(username: str, password: str):")

    print(editor.summary())
    # → 2 file(s) written: auth.py, routes/api.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

OperationType = Literal["create", "edit", "patch", "delete", "read"]


@dataclass
class EditResult:
    """
    Result of one :class:`FileEditor` operation.

    Attributes:
        success:       Whether the operation completed without error.
        path:          The relative path within the editor's base directory.
        operation:     One of ``"create"``, ``"edit"``, ``"patch"``, ``"delete"``, ``"read"``.
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


class FileEditor:
    """
    Scoped, tracked file editor.

    All paths passed to :meth:`create`, :meth:`edit`, :meth:`patch`, and
    :meth:`delete` are resolved relative to *base_dir*.  Attempts to escape
    the base directory (via ``../``) raise :exc:`ValueError`.

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
        Overwrite the entire content of an existing file at *path*.

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

        Raises (captured in result):
            FileNotFoundError: If the file does not exist.
            ValueError:        If *old_text* is not found in the file.
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
