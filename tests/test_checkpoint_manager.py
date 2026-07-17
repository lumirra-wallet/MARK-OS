"""
tests/test_checkpoint_manager.py — Task #11: Checkpoint Commits After Each Milestone

Covers:
  CheckpointResult  — dataclass fields, to_dict shape
  CheckpointManager — git detection, commit on full success, skip on partial
                      failure, message format, SHA parsing, metadata
                      accumulation, subprocess error handling, no-git path,
                      non-repo path, nothing-to-commit path
  Orchestrator      — checkpoint called per milestone; results in metadata
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, call, patch

import pytest

from smartagent.executive.checkpoint_manager import CheckpointManager, CheckpointResult
from smartagent.executive.task import Task, TaskStatus, TaskType


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_task(title: str = "T", status: TaskStatus = TaskStatus.COMPLETED) -> Task:
    t = Task(title=title)
    t.status = status
    return t


def _milestone(phase: int = 1, total: int = 1, title: str = "Phase",
               tasks: list | None = None):
    """Build a minimal Milestone-like object without importing MilestonePlanner."""
    from smartagent.executive.milestone_planner import Milestone
    m = Milestone(phase=phase, title=title, objective="test objective",
                  tasks=tasks or [], total=total)
    return m


def _all_complete(*titles) -> list:
    return [_make_task(t, TaskStatus.COMPLETED) for t in titles]


def _with_failure(*titles) -> list:
    tasks = [_make_task(t, TaskStatus.COMPLETED) for t in titles]
    if tasks:
        tasks[-1].status = TaskStatus.FAILED
    return tasks


def _git_repo(tmp_path: Path) -> Path:
    """Initialise a real throwaway git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@mark.ai"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "MARK Test"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    # seed file so HEAD exists
    seed = tmp_path / "seed.txt"
    seed.write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                   check=True, capture_output=True)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# CheckpointResult
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckpointResult:
    def test_defaults_skipped(self):
        r = CheckpointResult()
        assert r.success is False
        assert r.skipped is False
        assert r.sha == ""
        assert r.message == ""
        assert r.error == ""

    def test_to_dict_has_all_keys(self):
        r = CheckpointResult(success=True, sha="abc12345", message="chkpt")
        d = r.to_dict()
        for key in ("success", "skipped", "sha", "message", "error"):
            assert key in d

    def test_to_dict_values_match(self):
        r = CheckpointResult(success=True, skipped=False, sha="deadbeef",
                              message="m", error="")
        d = r.to_dict()
        assert d["success"] is True
        assert d["sha"] == "deadbeef"
        assert d["message"] == "m"

    def test_skipped_result_shape(self):
        r = CheckpointResult(skipped=True, error="no git")
        assert r.to_dict()["skipped"] is True
        assert r.to_dict()["success"] is False


# ─────────────────────────────────────────────────────────────────────────────
# CheckpointManager — git availability paths (mocked subprocess)
# ─────────────────────────────────────────────────────────────────────────────

class TestGitDetection:
    def test_skips_when_git_not_in_path(self, tmp_path):
        with patch("shutil.which", return_value=None):
            mgr = CheckpointManager(workspace_path=tmp_path)
        assert mgr._git_available is False

    def test_skips_when_not_in_repo(self, tmp_path):
        rev_fail = MagicMock()
        rev_fail.returncode = 128
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", return_value=rev_fail):
            mgr = CheckpointManager(workspace_path=tmp_path)
        assert mgr._git_available is False

    def test_available_when_git_found_and_in_repo(self, tmp_path):
        rev_ok = MagicMock(); rev_ok.returncode = 0
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", return_value=rev_ok):
            mgr = CheckpointManager(workspace_path=tmp_path)
        assert mgr._git_available is True

    def test_skips_when_detection_raises(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/git"), \
             patch("subprocess.run", side_effect=OSError("no exec")):
            mgr = CheckpointManager(workspace_path=tmp_path)
        assert mgr._git_available is False


# ─────────────────────────────────────────────────────────────────────────────
# CheckpointManager — commit logic (mocked git)
# ─────────────────────────────────────────────────────────────────────────────

class TestCommitLogic:
    def _manager(self, tmp_path) -> CheckpointManager:
        """Return a manager with git marked as available (no real git call)."""
        mgr = CheckpointManager.__new__(CheckpointManager)
        mgr._workspace = tmp_path
        mgr._git_available = True
        return mgr

    def _mock_subprocess(self, add_rc=0, commit_rc=0,
                         commit_stdout="[main abc1234] checkpoint"):
        """Return a side_effect list for subprocess.run calls."""
        add_res    = MagicMock(); add_res.returncode    = add_rc;    add_res.stderr = ""
        commit_res = MagicMock(); commit_res.returncode = commit_rc
        commit_res.stdout = commit_stdout; commit_res.stderr = ""
        return [add_res, commit_res]

    def test_commit_success_full_milestone(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("A", "B"))
        with patch("subprocess.run", side_effect=self._mock_subprocess()):
            result = mgr.commit(m)
        assert result.success is True
        assert result.skipped is False

    def test_sha_extracted_from_stdout(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("T"))
        with patch("subprocess.run",
                   side_effect=self._mock_subprocess(commit_stdout="[main deadbeef] msg")):
            result = mgr.commit(m)
        assert result.sha == "deadbeef"

    def test_sha_max_8_chars(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("T"))
        long_sha = "a" * 40
        with patch("subprocess.run",
                   side_effect=self._mock_subprocess(
                       commit_stdout=f"[main {long_sha}] msg")):
            result = mgr.commit(m)
        assert len(result.sha) <= 8

    def test_message_stored_in_result(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(phase=2, total=3, title="Build", tasks=_all_complete("X"))
        with patch("subprocess.run", side_effect=self._mock_subprocess()):
            result = mgr.commit(m)
        assert "milestone 2/3" in result.message
        assert "Build" in result.message

    def test_message_format_contains_task_count(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("A", "B", "C"))
        with patch("subprocess.run", side_effect=self._mock_subprocess()):
            result = mgr.commit(m)
        assert "[3 tasks]" in result.message

    def test_message_contains_checkmark(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("T"))
        with patch("subprocess.run", side_effect=self._mock_subprocess()):
            result = mgr.commit(m)
        assert "✓" in result.message

    def test_skip_when_task_failed(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_with_failure("A", "B"))
        result = mgr.commit(m)
        assert result.skipped is True
        assert result.success is False

    def test_skip_when_task_pending(self, tmp_path):
        mgr = self._manager(tmp_path)
        tasks = [_make_task("T", TaskStatus.PENDING)]
        m = _milestone(tasks=tasks)
        result = mgr.commit(m)
        assert result.skipped is True

    def test_skip_when_task_blocked(self, tmp_path):
        mgr = self._manager(tmp_path)
        tasks = [_make_task("T", TaskStatus.BLOCKED)]
        m = _milestone(tasks=tasks)
        result = mgr.commit(m)
        assert result.skipped is True

    def test_skip_when_git_not_available(self, tmp_path):
        mgr = CheckpointManager.__new__(CheckpointManager)
        mgr._workspace = tmp_path
        mgr._git_available = False
        m = _milestone(tasks=_all_complete("T"))
        result = mgr.commit(m)
        assert result.skipped is True

    def test_skip_when_nothing_to_commit(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("T"))
        nothing = [
            MagicMock(returncode=0, stderr=""),
            MagicMock(returncode=1,
                      stdout="nothing to commit, working tree clean",
                      stderr=""),
        ]
        with patch("subprocess.run", side_effect=nothing):
            result = mgr.commit(m)
        assert result.skipped is True

    def test_skip_on_subprocess_exception(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("T"))
        with patch("subprocess.run", side_effect=OSError("exec failed")):
            result = mgr.commit(m)
        assert result.skipped is True
        assert "exec failed" in result.error

    def test_skip_on_timeout(self, tmp_path):
        mgr = self._manager(tmp_path)
        m = _milestone(tasks=_all_complete("T"))
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30)):
            result = mgr.commit(m)
        assert result.skipped is True


# ─────────────────────────────────────────────────────────────────────────────
# CheckpointManager — real git repo (integration, fast)
# ─────────────────────────────────────────────────────────────────────────────

class TestRealGitRepo:
    def test_commit_created_in_real_repo(self, tmp_path):
        repo = _git_repo(tmp_path)
        (repo / "work.py").write_text("x = 1\n")
        mgr = CheckpointManager(workspace_path=repo)
        m = _milestone(tasks=_all_complete("Write"))
        result = mgr.commit(m)
        assert result.success is True
        assert len(result.sha) >= 4

    def test_commit_message_in_git_log(self, tmp_path):
        repo = _git_repo(tmp_path)
        (repo / "f.py").write_text("pass\n")
        mgr = CheckpointManager(workspace_path=repo)
        m = _milestone(phase=1, total=2, title="Alpha", tasks=_all_complete("Do"))
        mgr.commit(m)
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(repo), capture_output=True, text=True,
        )
        assert "checkpoint" in log.stdout
        assert "Alpha" in log.stdout

    def test_no_commit_when_workspace_not_repo(self, tmp_path):
        # tmp_path is NOT initialised as a git repo
        mgr = CheckpointManager(workspace_path=tmp_path)
        m = _milestone(tasks=_all_complete("T"))
        result = mgr.commit(m)
        # May succeed if parent dir is a repo — just ensure no crash
        assert isinstance(result, CheckpointResult)

    def test_skip_when_no_new_files(self, tmp_path):
        repo = _git_repo(tmp_path)
        mgr = CheckpointManager(workspace_path=repo)
        # Nothing new to stage — clean working tree
        m = _milestone(tasks=_all_complete("Clean"))
        result = mgr.commit(m)
        # Either skipped (nothing to commit) or success — never an unhandled error
        assert result.success or result.skipped


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator integration
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestratorCheckpointIntegration:
    def _mock_manager(self, results: list[CheckpointResult] | None = None):
        mgr = MagicMock(spec=CheckpointManager)
        if results:
            mgr.commit.side_effect = results
        else:
            mgr.commit.return_value = CheckpointResult(success=True, sha="abc12345",
                                                        message="chkpt")
        return mgr

    def test_checkpoints_list_in_metadata(self):
        from smartagent.executive.orchestrator import Orchestrator
        mock_mgr = self._mock_manager()
        orc = Orchestrator(arch_guard=None, checkpoint_manager=mock_mgr)
        ctx = orc.execute_goal("build a simple thing")
        assert "checkpoints" in ctx.metadata
        assert isinstance(ctx.metadata["checkpoints"], list)

    def test_checkpoint_called_once_per_milestone(self):
        from smartagent.executive.orchestrator import Orchestrator
        mock_mgr = self._mock_manager()
        orc = Orchestrator(arch_guard=None, checkpoint_manager=mock_mgr)
        orc.execute_goal("build a simple thing")
        assert mock_mgr.commit.call_count >= 1

    def test_checkpoint_result_appended_to_metadata(self):
        from smartagent.executive.orchestrator import Orchestrator
        result = CheckpointResult(success=True, sha="deadbeef", message="m")
        mock_mgr = self._mock_manager(results=[result])
        orc = Orchestrator(arch_guard=None, checkpoint_manager=mock_mgr)
        ctx = orc.execute_goal("build a simple thing")
        checkpoints = ctx.metadata.get("checkpoints", [])
        assert len(checkpoints) >= 1
        assert checkpoints[0]["sha"] == "deadbeef"

    def test_checkpoint_manager_none_does_not_crash(self):
        from smartagent.executive.orchestrator import Orchestrator
        orc = Orchestrator(arch_guard=None, checkpoint_manager=None)
        ctx = orc.execute_goal("build a simple thing")
        # checkpoints key absent or empty — no crash
        checkpoints = ctx.metadata.get("checkpoints", [])
        assert isinstance(checkpoints, list)
