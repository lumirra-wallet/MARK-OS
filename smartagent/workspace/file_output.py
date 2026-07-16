"""
file_output — utilities for writing artefacts into a workspace's output/ dir.

Workers can call ``write_output_file(workspace, filename, content)`` to
persist generated code, configs, documentation, and other files under the
workspace's ``output/`` directory.  Parent directories are created on demand.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.workspace.workspace import Workspace

logger = get_logger(__name__)


def write_output_file(
    workspace: "Workspace",
    filename: str,
    content: str,
) -> str:
    """
    Write *content* to ``<workspace.output_path>/<filename>``.

    Creates any intermediate directories automatically.

    Args:
        workspace: The active ``Workspace`` (provides ``output_path``).
        filename:  Relative path within ``output/``.
                   May contain subdirectories, e.g. ``"src/main.py"``.
        content:   Text content to write (UTF-8).

    Returns:
        The absolute path of the written file.

    Raises:
        OSError: On filesystem errors (permissions, no space, etc.).
    """
    dest = os.path.join(workspace.output_path, filename)
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("file_output.write: %s (%d bytes)", dest, len(content))
    return dest


def list_output_files(workspace: "Workspace") -> list[str]:
    """
    Return a sorted list of all files in ``<workspace.output_path>``.

    Paths are relative to ``workspace.output_path``.  Returns an empty list
    if the output directory does not yet exist.
    """
    result: list[str] = []
    if not os.path.isdir(workspace.output_path):
        return result
    for root, _dirs, files in os.walk(workspace.output_path):
        for fname in files:
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, workspace.output_path)
            result.append(rel)
    return sorted(result)


def output_file_count(workspace: "Workspace") -> int:
    """Return the total number of files in the workspace's output directory."""
    return len(list_output_files(workspace))
