"""
Tests for smartagent.server.deploy_awareness — restart/redeploy change
detection ("remember and check if changes were made").

Covers: first-run baseline (no summary), unchanged HEAD (no summary),
a real new commit producing a summary, and persistence via a fake
in-memory StorageProvider (mirrors tests/test_conversation_store.py's
pattern) so this never touches real storage.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from smartagent.server import deploy_awareness


class _FakeStorage:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, object]] = {}

    def get(self, namespace: str, key: str):
        return self._data.get(namespace, {}).get(key)

    def set(self, namespace: str, key: str, value) -> None:
        self._data.setdefault(namespace, {})[key] = value


@pytest.fixture()
def fake_storage():
    store = _FakeStorage()
    with patch("smartagent.server.deploy_awareness.get_storage", return_value=store):
        yield store


@pytest.fixture()
def git_ws(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "first commit"], cwd=repo, capture_output=True)
    return str(repo)


def _commit(ws: str, filename: str, message: str) -> None:
    (Path(ws) / filename).write_text(f"{filename}\n")
    subprocess.run(["git", "add", "-A"], cwd=ws, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=ws, capture_output=True)


class TestCheckForNewCommits:
    def test_first_run_returns_none_and_stores_baseline(self, git_ws, fake_storage):
        result = deploy_awareness.check_for_new_commits(git_ws)
        assert result is None
        key = deploy_awareness._key(git_ws)
        assert fake_storage.get("agent_state", key) is not None

    def test_unchanged_head_returns_none(self, git_ws, fake_storage):
        deploy_awareness.check_for_new_commits(git_ws)          # establishes baseline
        result = deploy_awareness.check_for_new_commits(git_ws)  # nothing changed since
        assert result is None

    def test_new_commit_produces_summary(self, git_ws, fake_storage):
        deploy_awareness.check_for_new_commits(git_ws)  # baseline at first commit
        _commit(git_ws, "b.txt", "second commit")
        result = deploy_awareness.check_for_new_commits(git_ws)
        assert result is not None
        assert "1 new commit" in result
        assert "second commit" in result

    def test_multiple_new_commits_counted(self, git_ws, fake_storage):
        deploy_awareness.check_for_new_commits(git_ws)
        _commit(git_ws, "b.txt", "second commit")
        _commit(git_ws, "c.txt", "third commit")
        result = deploy_awareness.check_for_new_commits(git_ws)
        assert "2 new commits" in result

    def test_updates_baseline_after_reporting(self, git_ws, fake_storage):
        deploy_awareness.check_for_new_commits(git_ws)
        _commit(git_ws, "b.txt", "second commit")
        first = deploy_awareness.check_for_new_commits(git_ws)
        assert first is not None
        # Baseline should now be the new HEAD — calling again with no new
        # commits reports nothing.
        second = deploy_awareness.check_for_new_commits(git_ws)
        assert second is None

    def test_non_git_workspace_returns_none(self, tmp_path, fake_storage):
        result = deploy_awareness.check_for_new_commits(str(tmp_path))
        assert result is None

    def test_workspaces_are_isolated(self, tmp_path, fake_storage):
        repo_a = tmp_path / "a"; repo_a.mkdir()
        repo_b = tmp_path / "b"; repo_b.mkdir()
        for repo in (repo_a, repo_b):
            subprocess.run(["git", "init"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
            subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
            (repo / "x.txt").write_text("x\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

        deploy_awareness.check_for_new_commits(str(repo_a))
        _commit(str(repo_a), "y.txt", "a-only commit")

        # repo_b's baseline was never advanced past its own first commit,
        # and it has no new commits — must not be affected by repo_a's history.
        result_b = deploy_awareness.check_for_new_commits(str(repo_b))
        assert result_b is None
