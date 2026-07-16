"""
smartagent.workspace — Milestone 15: Project Workspace Manager.

A workspace is a named, persistent project context that isolates
memory, knowledge, execution history, output files, and lessons per
project so MARK can manage multiple independent software projects.

Usage::

    from smartagent.workspace import WorkspaceManager

    wm = WorkspaceManager(base_path="workspaces")
    ws = wm.create("weather-api")
    wm.activate("weather-api")
    wm.set_goal("Build a FastAPI weather service")
    # ... run executions ...
    wm.deactivate()
"""

from smartagent.workspace.workspace import (
    Workspace,
    WorkspaceStatus,
    validate_workspace_name,
)
from smartagent.workspace.workspace_manager import WorkspaceError, WorkspaceManager
from smartagent.workspace.workspace_store import WorkspaceStore
from smartagent.workspace.file_output import (
    list_output_files,
    output_file_count,
    write_output_file,
)

__all__ = [
    "Workspace",
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspaceStatus",
    "WorkspaceStore",
    "list_output_files",
    "output_file_count",
    "validate_workspace_name",
    "write_output_file",
]
