"""
Tests for smartagent.engineer.agent_tools — executor + permission model.

All tests run against a temp workspace; no network, no LLM.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from smartagent.engineer.agent_tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    requires_approval,
    _safe_path,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def ws(tmp_path: Path) -> str:
    """Return an absolute workspace path with some seed content."""
    (tmp_path / "hello.txt").write_text("Hello, World!\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('main')\n")
    return str(tmp_path)


# ── TOOL_DEFINITIONS schema ────────────────────────────────────────────────────

class TestToolDefinitions:
    def test_all_have_required_keys(self):
        for td in TOOL_DEFINITIONS:
            assert td["type"] == "function"
            fn = td["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_names_are_unique(self):
        names = [td["function"]["name"] for td in TOOL_DEFINITIONS]
        assert len(names) == len(set(names))

    def test_core_tools_present(self):
        names = {td["function"]["name"] for td in TOOL_DEFINITIONS}
        for expected in [
            "read_file", "write_file", "list_directory", "search_workspace",
            "run_terminal", "git_status", "git_diff", "git_commit",
            "rename_file", "delete_file",
        ]:
            assert expected in names, f"Missing tool: {expected}"


# ── Permission model ───────────────────────────────────────────────────────────

class TestRequiresApproval:
    def test_delete_file_requires_approval(self):
        assert requires_approval("delete_file") is True

    def test_git_push_requires_approval(self):
        assert requires_approval("git_push") is True

    def test_write_file_does_not_require_approval(self):
        assert requires_approval("write_file") is False

    def test_run_terminal_does_not_require_approval(self):
        assert requires_approval("run_terminal") is False

    def test_git_commit_does_not_require_approval(self):
        assert requires_approval("git_commit") is False


# ── Path safety ────────────────────────────────────────────────────────────────

class TestSafePath:
    def test_relative_path_resolves_inside_workspace(self, ws):
        p = _safe_path(ws, "foo.txt")
        assert str(p).startswith(ws)

    def test_traversal_blocked(self, ws):
        with pytest.raises(ValueError, match="traversal"):
            _safe_path(ws, "../../etc/passwd")

    def test_nested_relative_path_ok(self, ws):
        p = _safe_path(ws, "src/utils.py")
        assert str(p) == os.path.join(ws, "src", "utils.py")

    def test_sibling_directory_with_shared_prefix_is_blocked(self, tmp_path):
        """A string startswith() check would wrongly allow this; resolve()
        + is_relative_to() must not."""
        workspace = tmp_path / "project"
        workspace.mkdir()
        sibling = tmp_path / "project-evil"
        sibling.mkdir()
        (sibling / "secret.txt").write_text("nope")
        with pytest.raises(ValueError, match="traversal"):
            _safe_path(str(workspace), "../project-evil/secret.txt")


# ── Per-task permission scoping ────────────────────────────────────────────────

class TestPermissionScoping:
    def test_unrestricted_when_no_allowed_paths(self, ws):
        result = execute_tool("write_file", {"path": "new.py", "content": "x"}, ws)
        assert "Written" in result

    def test_write_denied_outside_scope(self, ws):
        result = execute_tool(
            "write_file", {"path": "other.py", "content": "x"}, ws,
            allowed_paths=["app.py"],
        )
        assert "Permission denied" in result
        assert not Path(ws, "other.py").exists()

    def test_write_allowed_inside_scope(self, ws):
        result = execute_tool(
            "write_file", {"path": "app.py", "content": "x = 1\n"}, ws,
            allowed_paths=["app.py"],
        )
        assert "Written" in result
        assert Path(ws, "app.py").read_text() == "x = 1\n"

    def test_rename_denied_outside_scope(self, ws):
        result = execute_tool(
            "rename_file", {"src": "hello.txt", "dst": "renamed.txt"}, ws,
            allowed_paths=["app.py"],
        )
        assert "Permission denied" in result

    def test_reads_never_restricted(self, ws):
        """Scoping only limits writes — MARK can still read broadly for context."""
        result = execute_tool(
            "read_file", {"path": "hello.txt"}, ws,
            allowed_paths=["app.py"],
        )
        assert "Hello, World!" in result

    def test_empty_allowed_paths_is_unrestricted(self, ws):
        result = execute_tool(
            "write_file", {"path": "anything.py", "content": "x"}, ws,
            allowed_paths=[],
        )
        assert "Written" in result


# ── read_file ──────────────────────────────────────────────────────────────────

class TestReadFile:
    def test_reads_existing_file(self, ws):
        result = execute_tool("read_file", {"path": "hello.txt"}, ws)
        assert "Hello, World!" in result

    def test_missing_file_returns_error_message(self, ws):
        result = execute_tool("read_file", {"path": "nonexistent.txt"}, ws)
        assert "not found" in result.lower() or "File not found" in result

    def test_nested_file_reads_ok(self, ws):
        result = execute_tool("read_file", {"path": "src/main.py"}, ws)
        assert "print" in result


# ── write_file ─────────────────────────────────────────────────────────────────

class TestWriteFile:
    def test_creates_new_file(self, ws):
        result = execute_tool("write_file", {"path": "new.py", "content": "x = 1\n"}, ws)
        assert "Written" in result
        assert Path(ws, "new.py").read_text() == "x = 1\n"

    def test_creates_nested_dirs(self, ws):
        execute_tool("write_file", {"path": "deep/nested/file.txt", "content": "hi"}, ws)
        assert Path(ws, "deep", "nested", "file.txt").exists()

    def test_overwrites_existing_file(self, ws):
        execute_tool("write_file", {"path": "hello.txt", "content": "Updated\n"}, ws)
        assert Path(ws, "hello.txt").read_text() == "Updated\n"

    def test_path_traversal_blocked(self, ws):
        result = execute_tool("write_file", {"path": "../../evil.txt", "content": "x"}, ws)
        assert "error" in result.lower() or "blocked" in result.lower() or "traversal" in result.lower()


# ── list_directory ─────────────────────────────────────────────────────────────

class TestListDirectory:
    def test_lists_root(self, ws):
        result = execute_tool("list_directory", {}, ws)
        assert "hello.txt" in result
        assert "src" in result

    def test_lists_subdirectory(self, ws):
        result = execute_tool("list_directory", {"path": "src"}, ws)
        assert "main.py" in result

    def test_missing_dir_returns_error(self, ws):
        result = execute_tool("list_directory", {"path": "nosuchdir"}, ws)
        assert "not found" in result.lower()


# ── search_workspace ───────────────────────────────────────────────────────────

class TestSearchWorkspace:
    def test_finds_matching_content(self, ws):
        result = execute_tool("search_workspace", {"query": "Hello"}, ws)
        # Should find "Hello, World!" in hello.txt
        assert "hello.txt" in result or "Hello" in result

    def test_no_matches_returns_no_matches(self, ws):
        result = execute_tool("search_workspace", {"query": "XYZZY_NOT_FOUND_12345"}, ws)
        assert "no match" in result.lower() or result.strip() == "(no matches)"


# ── run_terminal ───────────────────────────────────────────────────────────────

class TestRunTerminal:
    def test_runs_echo(self, ws):
        result = execute_tool("run_terminal", {"command": "echo hello_from_test"}, ws)
        assert "hello_from_test" in result

    def test_captures_stderr_on_error(self, ws):
        result = execute_tool("run_terminal", {"command": "ls /nonexistent_path_xyz"}, ws)
        # Should include exit code indicator or error text
        assert result  # non-empty

    def test_returns_exit_code_on_failure(self, ws):
        result = execute_tool("run_terminal", {"command": "exit 1"}, ws)
        assert "[exit 1]" in result or "exit" in result.lower()

    def test_runs_python(self, ws):
        result = execute_tool(
            "run_terminal",
            {"command": f"{sys.executable} -c \"print('mark_test_ok')\""},
            ws,
        )
        assert "mark_test_ok" in result


# ── rename_file ────────────────────────────────────────────────────────────────

class TestRenameFile:
    def test_renames_file(self, ws):
        result = execute_tool("rename_file", {"src": "hello.txt", "dst": "renamed.txt"}, ws)
        assert "renamed" in result.lower() or "→" in result
        assert not Path(ws, "hello.txt").exists()
        assert Path(ws, "renamed.txt").exists()

    def test_missing_src_returns_error(self, ws):
        result = execute_tool("rename_file", {"src": "nosuch.txt", "dst": "out.txt"}, ws)
        assert "not found" in result.lower()


# ── delete_file — gated behind approval ───────────────────────────────────────

class TestDeleteFile:
    def test_delete_file_is_approval_required(self):
        assert requires_approval("delete_file") is True

    def test_execute_delete_actually_deletes(self, ws):
        # Only called after approval logic in the loop; test raw executor
        result = execute_tool("delete_file", {"path": "hello.txt"}, ws)
        assert "Deleted" in result
        assert not Path(ws, "hello.txt").exists()

    def test_delete_missing_file_returns_error(self, ws):
        result = execute_tool("delete_file", {"path": "nosuch.txt"}, ws)
        assert "not found" in result.lower()


# ── git operations ─────────────────────────────────────────────────────────────

class TestGitOperations:
    @pytest.fixture()
    def git_ws(self, tmp_path):
        """Workspace with a git repo initialised."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        return str(tmp_path)

    def test_git_status_returns_text(self, git_ws):
        result = execute_tool("git_status", {}, git_ws)
        assert isinstance(result, str) and len(result) > 0

    def test_git_diff_returns_text(self, git_ws):
        result = execute_tool("git_diff", {}, git_ws)
        assert isinstance(result, str)

    def test_git_commit_creates_commit(self, git_ws):
        (Path(git_ws) / "test.py").write_text("x = 1\n")
        result = execute_tool("git_commit", {"message": "initial commit"}, git_ws)
        assert "initial commit" in result or "master" in result or "main" in result or "commit" in result.lower()


# ── unknown tool ───────────────────────────────────────────────────────────────

class TestUnknownTool:
    def test_unknown_tool_returns_error(self, ws):
        result = execute_tool("nonexistent_tool", {}, ws)
        assert "Unknown tool" in result
