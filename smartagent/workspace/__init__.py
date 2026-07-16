"""
smartagent.workspace — Milestone 15: Project Workspace Manager.

A workspace is a named, persistent project context that isolates
memory, knowledge, execution history, output files, and lessons per
project so MARK can manage multiple independent software projects.

Milestone 18 adds: ProjectScanner — build a mental model of any codebase.
Milestone 19 adds: FileEditor — tracked, scoped file create/edit/patch/delete.

Usage::

    from smartagent.workspace import WorkspaceManager

    wm = WorkspaceManager(base_path="workspaces")
    ws = wm.create("weather-api")
    wm.activate("weather-api")
    wm.set_goal("Build a FastAPI weather service")
    # ... run executions ...
    wm.deactivate()

    # Milestone 18 — scan a project
    from smartagent.workspace import ProjectScanner
    snapshot = ProjectScanner("/path/to/project").scan()

    # Milestone 19 — edit files with tracking
    from smartagent.workspace import FileEditor
    editor = FileEditor(ws.output_path)
    editor.create("auth.py", "def login(): ...")
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
from smartagent.workspace.scanner import ProjectScanner, ProjectSnapshot
from smartagent.workspace.file_editor import EditResult, FileEditor

__all__ = [
    # Milestone 15
    "Workspace",
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspaceStatus",
    "WorkspaceStore",
    "list_output_files",
    "output_file_count",
    "validate_workspace_name",
    "write_output_file",
    # Milestone 18
    "ProjectScanner",
    "ProjectSnapshot",
    # Milestone 19
    "EditResult",
    "FileEditor",
]
