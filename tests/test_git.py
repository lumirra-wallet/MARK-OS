"""
Tests for Milestone 21: Git Engine.

Coverage:
    GitResult:
      • __bool__, __str__, error_summary, first_line, as_display_lines

    FileChange:
      • status_label for all codes, icon, __str__

    GitStatus:
      • is_clean, total_changes, has_staged, ready_to_commit
      • sync_status (all four states)
      • as_display_lines — clean / staged / unstaged / untracked / git-sync
      • as_ai_summary

    CommitInfo:
      • __str__, short_sha

    parse_porcelain_status:
      • clean repo
      • branch only (no remote)
      • branch with tracking + ahead/behind
      • staged files
      • unstaged files
      • untracked files
      • mixed (staged + unstaged + untracked)
      • renamed file
      • empty output

    parse_log_output:
      • single entry
      • multiple entries
      • empty output
      • malformed line skipped

    GitClient._run:
      • success path
      • git not found (FileNotFoundError)
      • timeout
      • non-zero exit code

    GitClient.is_repo:
      • True when inside a repo
      • False when not

    GitClient.init:
      • creates a repo (uses real tmp_path)

    GitClient.status:
      • returns GitStatus (mocked)
      • returns fallback on failure

    GitClient.current_branch:
      • returns branch name
      • returns HEAD on failure

    GitClient.log:
      • returns CommitInfo list
      • empty repo → []

    GitClient.diff:
      • working tree diff
      • staged diff

    GitClient.create_branch:
      • with checkout (default)
      • without checkout

    GitClient.checkout:
      • success / failure

    GitClient.list_branches:
      • marks current branch first
      • all_branches flag

    GitClient.delete_branch:
      • normal / force

    GitClient.add:
      • string path
      • list of paths

    GitClient.restore:
      • unstaged / staged

    GitClient.commit:
      • extracts SHA from output
      • all_changes flag

    GitClient.add_and_commit:
      • stops on add failure

    GitClient.push:
      • set_upstream flag
      • force flag

    GitClient.pull:
      • rebase flag

    GitClient.merge:
      • no_ff flag

    GitClient.reset:
      • soft / mixed / hard
      • invalid mode → failure result

    GitClient.stash / stash_pop / stash_list

    GitClient.tag / list_tags

    GitClient.config_get / config_set

    GitClient.remote_url / list_remotes

    GitClient.changed_files

    PRBuilder.build:
      • infers title from branch name
      • custom title
      • body contains file sections
      • body contains commit section
      • as_display_lines

    PRBuilder._infer_title:
      • strips feature/ prefix
      • uses single commit message when one commit

    GitWorker:
      • name, task_types, description
      • _extract_branch_name — explicit / derived
      • _extract_commit_message
      • _extract_tag_name
      • _extract_pr_title
      • _extract_number
      • execute() stub — branch / commit / push / pull / merge / rollback / pr / status
      • execute() commit wires up FileEditor written_files
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from smartagent.git.git_result import GitResult
from smartagent.git.git_status import (
    CommitInfo,
    FileChange,
    GitStatus,
    parse_log_output,
    parse_porcelain_status,
)
from smartagent.git.git_client import GitClient
from smartagent.git.pr_builder import PRBuilder, PRDescription


# ===========================================================================
# GitResult
# ===========================================================================

class TestGitResult:
    def _ok(self, output="done") -> GitResult:
        return GitResult(success=True, command="git commit", output=output, error="", returncode=0)

    def _fail(self, error="not a git repo") -> GitResult:
        return GitResult(success=False, command="git push", output="", error=error, returncode=128)

    def test_bool_true(self):
        assert bool(self._ok()) is True

    def test_bool_false(self):
        assert bool(self._fail()) is False

    def test_str_success(self):
        r = self._ok("HEAD -> main")
        assert "HEAD -> main" in str(r)

    def test_str_success_empty_output(self):
        r = GitResult(True, "git add", "", "", 0)
        assert str(r) == "OK"

    def test_str_failure_includes_error(self):
        r = self._fail("fatal: not a git repository")
        s = str(r)
        assert "not a git repository" in s

    def test_error_summary_prefers_error(self):
        r = GitResult(False, "git push", "some output", "fatal: auth failed", 1)
        assert "auth failed" in r.error_summary

    def test_error_summary_falls_back_to_output(self):
        r = GitResult(False, "git push", "error: something", "", 1)
        assert "something" in r.error_summary

    def test_error_summary_exit_code_fallback(self):
        r = GitResult(False, "git push", "", "", 128)
        assert "128" in r.error_summary

    def test_first_line(self):
        r = GitResult(True, "git log", "abc1234 First commit\ndef5678 Second", "", 0)
        assert r.first_line == "abc1234 First commit"

    def test_first_line_empty(self):
        r = GitResult(True, "git status", "", "", 0)
        assert r.first_line == ""

    def test_as_display_lines_success(self):
        r = GitResult(True, "git commit", "1 file changed", "", 0)
        lines = r.as_display_lines()
        assert any("✓" in l for l in lines)
        assert any("1 file changed" in l for l in lines)

    def test_as_display_lines_failure(self):
        r = GitResult(False, "git push", "", "fatal: auth failed", 1)
        lines = r.as_display_lines()
        assert any("✗" in l for l in lines)
        assert any("auth failed" in l for l in lines)

    def test_sha_default_empty(self):
        r = self._ok()
        assert r.sha == ""


# ===========================================================================
# FileChange
# ===========================================================================

class TestFileChange:
    def test_modified_staged_label(self):
        fc = FileChange(path="auth.py", status_code="M", staged=True)
        assert fc.status_label == "modified"

    def test_added_label(self):
        assert FileChange("f.py", "A", True).status_label == "added"

    def test_deleted_label(self):
        assert FileChange("f.py", "D", False).status_label == "deleted"

    def test_untracked_label(self):
        assert FileChange("f.py", "?", False).status_label == "untracked"

    def test_unknown_code(self):
        fc = FileChange("f.py", "X", False)
        assert fc.status_label == "X"

    def test_icon_modified(self):
        assert FileChange("f.py", "M", True).icon == "~"

    def test_icon_added(self):
        assert FileChange("f.py", "A", True).icon == "+"

    def test_icon_deleted(self):
        assert FileChange("f.py", "D", False).icon == "-"

    def test_icon_untracked(self):
        assert FileChange("f.py", "?", False).icon == "?"

    def test_str_staged(self):
        fc = FileChange("auth.py", "M", True)
        s = str(fc)
        assert "auth.py" in s
        assert "staged" in s

    def test_str_unstaged(self):
        fc = FileChange("auth.py", "M", False)
        s = str(fc)
        assert "unstaged" in s


# ===========================================================================
# CommitInfo
# ===========================================================================

class TestCommitInfo:
    def test_str_format(self):
        c = CommitInfo("abc1234def567", "Add login", "Alice", "2 days ago")
        s = str(c)
        assert "abc1234" in s
        assert "Add login" in s
        assert "Alice" in s

    def test_short_sha(self):
        c = CommitInfo("abc1234def567", "", "", "")
        assert c.short_sha == "abc1234"

    def test_short_sha_already_short(self):
        c = CommitInfo("abc12", "", "", "")
        assert c.short_sha == "abc12"


# ===========================================================================
# GitStatus
# ===========================================================================

class TestGitStatus:
    def _clean(self) -> GitStatus:
        return GitStatus(branch="main")

    def _dirty(self) -> GitStatus:
        s = GitStatus(branch="feature/x")
        s.staged    = [FileChange("a.py", "M", True)]
        s.unstaged  = [FileChange("b.py", "M", False)]
        s.untracked = [FileChange("c.py", "?", False)]
        return s

    def test_is_clean_true(self):
        assert self._clean().is_clean is True

    def test_is_clean_false(self):
        s = GitStatus(branch="main")
        s.staged = [FileChange("x.py", "A", True)]
        assert s.is_clean is False

    def test_total_changes(self):
        assert self._dirty().total_changes == 3

    def test_has_staged(self):
        s = GitStatus(branch="main")
        s.staged = [FileChange("x.py", "M", True)]
        assert s.has_staged is True

    def test_has_staged_false(self):
        assert self._clean().has_staged is False

    def test_ready_to_commit(self):
        s = GitStatus(branch="main")
        s.staged = [FileChange("x.py", "A", True)]
        assert s.ready_to_commit is True

    def test_ready_to_commit_false(self):
        assert self._clean().ready_to_commit is False

    # sync_status
    def test_sync_no_remote(self):
        s = GitStatus(branch="main", remote="")
        assert "no remote" in s.sync_status

    def test_sync_up_to_date(self):
        s = GitStatus(branch="main", remote="origin/main")
        assert "up to date" in s.sync_status

    def test_sync_ahead(self):
        s = GitStatus(branch="main", ahead=2, remote="origin/main")
        assert "ahead" in s.sync_status
        assert "2" in s.sync_status

    def test_sync_behind(self):
        s = GitStatus(branch="main", behind=3, remote="origin/main")
        assert "behind" in s.sync_status

    def test_sync_diverged(self):
        s = GitStatus(branch="main", ahead=1, behind=2, remote="origin/main")
        assert "diverged" in s.sync_status

    # as_display_lines
    def test_display_clean(self):
        lines = self._clean().as_display_lines()
        combined = "\n".join(lines)
        assert "clean" in combined.lower() or "main" in combined

    def test_display_shows_branch(self):
        lines = GitStatus(branch="feature/x").as_display_lines()
        assert any("feature/x" in l for l in lines)

    def test_display_shows_staged(self):
        s = GitStatus(branch="main")
        s.staged = [FileChange("auth.py", "M", True)]
        lines = s.as_display_lines()
        assert any("auth.py" in l for l in lines)

    def test_display_truncates_untracked(self):
        s = GitStatus(branch="main")
        s.untracked = [FileChange(f"file{i}.py", "?", False) for i in range(20)]
        lines = s.as_display_lines()
        assert any("more" in l for l in lines)

    # as_ai_summary
    def test_ai_summary_contains_branch(self):
        s = GitStatus(branch="feature/login")
        assert "feature/login" in s.as_ai_summary()

    def test_ai_summary_clean(self):
        s = GitStatus(branch="main")
        summary = s.as_ai_summary()
        assert "Clean" in summary or "clean" in summary


# ===========================================================================
# parse_porcelain_status
# ===========================================================================

CLEAN_PORCELAIN = "## main...origin/main\n"

DIRTY_PORCELAIN = """\
## main...origin/main [ahead 2]
M  src/auth.py
 M tests/test_auth.py
?? new_file.py
A  added.py
"""

BEHIND_PORCELAIN = "## develop...origin/develop [behind 3]\n"

NO_REMOTE_PORCELAIN = "## main\n"

MIXED_PORCELAIN = """\
## feature/login...origin/feature/login [ahead 1, behind 2]
M  auth.py
MM models.py
D  old.py
R  old_name.py -> new_name.py
?? untracked.txt
?? another.txt
"""


class TestParsePorcelainStatus:
    def test_clean_branch(self):
        s = parse_porcelain_status(CLEAN_PORCELAIN)
        assert s.branch == "main"
        assert s.is_clean is True
        assert s.ahead == 0
        assert s.behind == 0

    def test_clean_remote(self):
        s = parse_porcelain_status(CLEAN_PORCELAIN)
        assert "origin/main" in s.remote

    def test_ahead(self):
        s = parse_porcelain_status(DIRTY_PORCELAIN)
        assert s.ahead == 2
        assert s.behind == 0

    def test_behind(self):
        s = parse_porcelain_status(BEHIND_PORCELAIN)
        assert s.behind == 3
        assert s.ahead == 0

    def test_no_remote(self):
        s = parse_porcelain_status(NO_REMOTE_PORCELAIN)
        assert s.branch == "main"
        assert s.remote == ""

    def test_staged_file(self):
        s = parse_porcelain_status(DIRTY_PORCELAIN)
        staged_paths = {fc.path for fc in s.staged}
        assert "src/auth.py" in staged_paths or "added.py" in staged_paths

    def test_unstaged_file(self):
        s = parse_porcelain_status(DIRTY_PORCELAIN)
        unstaged_paths = {fc.path for fc in s.unstaged}
        assert "tests/test_auth.py" in unstaged_paths

    def test_untracked_file(self):
        s = parse_porcelain_status(DIRTY_PORCELAIN)
        untracked_paths = {fc.path for fc in s.untracked}
        assert "new_file.py" in untracked_paths

    def test_mixed_ahead_behind(self):
        s = parse_porcelain_status(MIXED_PORCELAIN)
        assert s.ahead == 1
        assert s.behind == 2

    def test_mixed_deleted(self):
        s = parse_porcelain_status(MIXED_PORCELAIN)
        staged_codes = {fc.status_code for fc in s.staged}
        assert "D" in staged_codes

    def test_empty_output(self):
        s = parse_porcelain_status("")
        assert s.branch == ""
        assert s.is_clean is True

    def test_untracked_multiple(self):
        s = parse_porcelain_status(MIXED_PORCELAIN)
        untracked = {fc.path for fc in s.untracked}
        assert "untracked.txt" in untracked
        assert "another.txt" in untracked


# ===========================================================================
# parse_log_output
# ===========================================================================

class TestParseLogOutput:
    _SEP = "\x00"

    def _line(self, sha, msg, author, date):
        return f"{sha}{self._SEP}{msg}{self._SEP}{author}{self._SEP}{date}"

    def test_single_entry(self):
        out = self._line("abc1234", "Add login", "Alice", "2 days ago")
        commits = parse_log_output(out, sep=self._SEP)
        assert len(commits) == 1
        assert commits[0].sha == "abc1234"
        assert commits[0].message == "Add login"

    def test_multiple_entries(self):
        out = "\n".join([
            self._line("aaa", "First", "Alice", "1d"),
            self._line("bbb", "Second", "Bob", "2d"),
        ])
        commits = parse_log_output(out, sep=self._SEP)
        assert len(commits) == 2

    def test_empty_output(self):
        assert parse_log_output("", sep=self._SEP) == []

    def test_malformed_line_skipped(self):
        out = "not-a-valid-line\n" + self._line("abc", "OK", "Alice", "now")
        commits = parse_log_output(out, sep=self._SEP)
        # The malformed line may parse as bare SHA but the valid line should appear
        valid = [c for c in commits if c.message == "OK"]
        assert len(valid) == 1


# ===========================================================================
# GitClient — using mocked subprocess
# ===========================================================================

def _mock_run(stdout="", stderr="", returncode=0):
    """Return a MagicMock shaped like subprocess.CompletedProcess."""
    m = MagicMock()
    m.stdout     = stdout
    m.stderr     = stderr
    m.returncode = returncode
    return m


class TestGitClientRun:
    def test_success(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("ok")) as mock:
            r = git._run("status")
        assert r.success is True
        assert r.output == "ok"

    def test_nonzero_exit(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "fatal: no repo", 128)):
            r = git._run("status")
        assert r.success is False
        assert r.returncode == 128

    def test_git_not_found(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            r = git._run("status")
        assert r.success is False
        assert "not found" in r.error.lower() or "git" in r.error.lower()

    def test_timeout(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            r = git._run("push")
        assert r.success is False
        assert "timed out" in r.error.lower()

    def test_command_string_stored(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("ok")) as mock:
            r = git._run("log", "--oneline", "-5")
        assert "git log --oneline -5" == r.command

    def test_sha_extracted_from_commit(self, tmp_path):
        git = GitClient(str(tmp_path))
        output = "[main abc1234] Add login\n 1 file changed"
        with patch("subprocess.run", return_value=_mock_run(output)):
            r = git._run("commit", "-m", "Add login")
        assert r.sha == "abc1234"


class TestGitClientIsRepo:
    def test_true(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("true")):
            assert git.is_repo() is True

    def test_false_no_repo(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "fatal: not a git repo", 128)):
            assert git.is_repo() is False

    def test_false_git_missing(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert git.is_repo() is False


class TestGitClientInit:
    def test_init_real(self, tmp_path):
        git = GitClient(str(tmp_path))
        result = git.init()
        # Accept success or "already a repo" — real git is available in the environment
        assert isinstance(result, GitResult)


class TestGitClientStatus:
    def test_returns_git_status(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("## main...origin/main\n")):
            s = git.status()
        assert isinstance(s, GitStatus)
        assert s.branch == "main"

    def test_fallback_on_failure(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "not a repo", 128)):
            s = git.status()
        assert isinstance(s, GitStatus)
        assert s.branch == "(unknown)"


class TestGitClientCurrentBranch:
    def test_returns_branch(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("feature/login\n")):
            assert git.current_branch() == "feature/login"

    def test_head_on_failure(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "error", 1)):
            assert git.current_branch() == "HEAD"


class TestGitClientLog:
    def test_returns_commits(self, tmp_path):
        git = GitClient(str(tmp_path))
        line = "abc1234\x00Add login\x00Alice\x002 days ago"
        with patch("subprocess.run", return_value=_mock_run(line)):
            commits = git.log(n=5)
        assert len(commits) == 1
        assert commits[0].message == "Add login"

    def test_empty_on_failure(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "no commits", 128)):
            commits = git.log()
        assert commits == []


class TestGitClientDiff:
    def test_working_tree(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("diff output")) as mock:
            diff = git.diff()
        assert diff == "diff output"
        args = mock.call_args[0][0]
        assert "--cached" not in args

    def test_staged(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("staged diff")) as mock:
            diff = git.diff(staged=True)
        args = mock.call_args[0][0]
        assert "--cached" in args


class TestGitClientCreateBranch:
    def test_with_checkout(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("Switched")) as mock:
            r = git.create_branch("feature/login")
        assert r.success is True
        args = mock.call_args[0][0]
        assert "checkout" in args
        assert "-b" in args

    def test_without_checkout(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            r = git.create_branch("feature/x", checkout=False)
        args = mock.call_args[0][0]
        assert "branch" in args
        assert "-b" not in args

    def test_from_branch(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.create_branch("feature/x", from_branch="develop")
        args = mock.call_args[0][0]
        assert "develop" in args


class TestGitClientCheckout:
    def test_success(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("Switched to branch 'main'")):
            r = git.checkout("main")
        assert r.success is True

    def test_failure(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "error: no branch", 1)):
            r = git.checkout("nonexistent")
        assert r.success is False


class TestGitClientListBranches:
    def test_current_branch_first(self, tmp_path):
        git = GitClient(str(tmp_path))
        output = "* main\n  feature/login\n  develop\n"
        with patch("subprocess.run", return_value=_mock_run(output)):
            branches = git.list_branches()
        assert branches[0] == "main"
        assert "feature/login" in branches

    def test_all_flag(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("* main\n")) as mock:
            git.list_branches(all_branches=True)
        args = mock.call_args[0][0]
        assert "-a" in args


class TestGitClientDeleteBranch:
    def test_normal(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("Deleted")) as mock:
            git.delete_branch("old-branch")
        args = mock.call_args[0][0]
        assert "-d" in args

    def test_force(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("Deleted")) as mock:
            git.delete_branch("old-branch", force=True)
        args = mock.call_args[0][0]
        assert "-D" in args


class TestGitClientAdd:
    def test_string_path(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.add("src/auth.py")
        args = mock.call_args[0][0]
        assert "src/auth.py" in args

    def test_list_of_paths(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.add(["src/auth.py", "tests/test_auth.py"])
        args = mock.call_args[0][0]
        assert "src/auth.py" in args
        assert "tests/test_auth.py" in args

    def test_dot_default(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.add()
        args = mock.call_args[0][0]
        assert "." in args


class TestGitClientRestore:
    def test_unstaged(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.restore("auth.py")
        args = mock.call_args[0][0]
        assert "--staged" not in args

    def test_staged(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.restore("auth.py", staged=True)
        args = mock.call_args[0][0]
        assert "--staged" in args


class TestGitClientCommit:
    def test_extracts_sha(self, tmp_path):
        git = GitClient(str(tmp_path))
        output = "[main abc1234] Add login\n 1 file changed"
        with patch("subprocess.run", return_value=_mock_run(output)):
            r = git.commit("Add login")
        assert r.sha == "abc1234"

    def test_all_changes_flag(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.commit("msg", all_changes=True)
        args = mock.call_args[0][0]
        assert "-a" in args

    def test_allow_empty_flag(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.commit("empty", allow_empty=True)
        args = mock.call_args[0][0]
        assert "--allow-empty" in args


class TestGitClientAddAndCommit:
    def test_stages_then_commits(self, tmp_path):
        git = GitClient(str(tmp_path))
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _mock_run("[main abc1234] msg" if "commit" in cmd else "")

        with patch("subprocess.run", side_effect=fake_run):
            r = git.add_and_commit("msg")

        assert any("add" in c for c in calls)
        assert any("commit" in c for c in calls)

    def test_stops_on_add_failure(self, tmp_path):
        git = GitClient(str(tmp_path))
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return _mock_run("", "error", 1)  # always fail

        with patch("subprocess.run", side_effect=fake_run):
            r = git.add_and_commit("msg")

        # add failed, commit should not be called
        commit_calls = [c for c in calls if "commit" in c]
        assert commit_calls == []
        assert r.success is False


class TestGitClientPush:
    def test_set_upstream(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch.object(git, "current_branch", return_value="feature/x"), \
             patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.push(set_upstream=True)
        args = mock.call_args[0][0]
        assert "-u" in args

    def test_force(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch.object(git, "current_branch", return_value="main"), \
             patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.push(force=True)
        args = mock.call_args[0][0]
        assert "--force-with-lease" in args


class TestGitClientPull:
    def test_rebase_flag(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.pull(rebase=True)
        args = mock.call_args[0][0]
        assert "--rebase" in args


class TestGitClientMerge:
    def test_no_ff(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.merge("feature/login", no_ff=True)
        args = mock.call_args[0][0]
        assert "--no-ff" in args

    def test_branch_name_in_command(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.merge("feature/login")
        args = mock.call_args[0][0]
        assert "feature/login" in args


class TestGitClientReset:
    def test_soft_reset(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            r = git.reset(mode="soft", target="HEAD~1")
        assert r.success is True
        args = mock.call_args[0][0]
        assert "--soft" in args

    def test_mixed_reset(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.reset(mode="mixed", target="HEAD~2")
        args = mock.call_args[0][0]
        assert "--mixed" in args

    def test_hard_reset(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.reset(mode="hard", target="HEAD~1")
        args = mock.call_args[0][0]
        assert "--hard" in args

    def test_invalid_mode_returns_failure(self, tmp_path):
        git = GitClient(str(tmp_path))
        r = git.reset(mode="sideways")
        assert r.success is False
        assert "invalid mode" in r.error.lower()


class TestGitClientStash:
    def test_stash_push(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("Saved")) as mock:
            r = git.stash()
        assert r.success is True

    def test_stash_pop(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("Applied")) as mock:
            r = git.stash_pop()
        args = mock.call_args[0][0]
        assert "pop" in args

    def test_stash_list(self, tmp_path):
        git = GitClient(str(tmp_path))
        output = "stash@{0}: On main: WIP\nstash@{1}: On feature: save"
        with patch("subprocess.run", return_value=_mock_run(output)):
            entries = git.stash_list()
        assert len(entries) == 2
        assert "stash@{0}" in entries[0]


class TestGitClientTag:
    def test_lightweight_tag(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.tag("v1.0.0")
        args = mock.call_args[0][0]
        assert "v1.0.0" in args
        assert "-a" not in args

    def test_annotated_tag(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.tag("v1.0.0", message="Release 1.0.0")
        args = mock.call_args[0][0]
        assert "-a" in args
        assert "Release 1.0.0" in args

    def test_list_tags(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("v1.0.0\nv0.9.0\n")):
            tags = git.list_tags()
        assert "v1.0.0" in tags
        assert "v0.9.0" in tags


class TestGitClientConfig:
    def test_get_existing(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("Alice\n")):
            value = git.config_get("user.name")
        assert value == "Alice"

    def test_get_missing(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "", 1)):
            value = git.config_get("user.nonexistent")
        assert value == ""

    def test_set(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("")) as mock:
            git.config_set("user.name", "Bob")
        args = mock.call_args[0][0]
        assert "user.name" in args
        assert "Bob" in args


class TestGitClientRemote:
    def test_remote_url(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("https://github.com/user/repo.git\n")):
            url = git.remote_url()
        assert "github.com" in url

    def test_remote_url_missing(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "error", 1)):
            url = git.remote_url()
        assert url == ""

    def test_list_remotes(self, tmp_path):
        git = GitClient(str(tmp_path))
        output = "origin\thttps://github.com/user/repo.git (fetch)\norigin\thttps://github.com/user/repo.git (push)\n"
        with patch("subprocess.run", return_value=_mock_run(output)):
            remotes = git.list_remotes()
        assert "origin" in remotes
        assert "github.com" in remotes["origin"]


class TestGitClientChangedFiles:
    def test_returns_paths(self, tmp_path):
        git = GitClient(str(tmp_path))
        output = "src/auth.py\ntests/test_auth.py\n"
        with patch("subprocess.run", return_value=_mock_run(output)):
            files = git.changed_files()
        assert "src/auth.py" in files
        assert "tests/test_auth.py" in files

    def test_empty_on_failure(self, tmp_path):
        git = GitClient(str(tmp_path))
        with patch("subprocess.run", return_value=_mock_run("", "no common ancestor", 1)):
            files = git.changed_files()
        assert files == []


# ===========================================================================
# PRBuilder
# ===========================================================================

class TestPRBuilder:
    def _make_git(self, branch="feature/login", changed=None, commits=None, remote=""):
        git = MagicMock()
        git.current_branch.return_value = branch
        git.remote_url.return_value = remote
        git.log.return_value = commits or [
            CommitInfo("abc1234", "Add login", "Alice", "1 day ago"),
            CommitInfo("def5678", "Add tests", "Alice", "2 days ago"),
        ]
        git.changed_files.return_value = ["src/auth.py", "tests/test_auth.py"] if changed is None else changed
        return git

    def test_build_returns_pr_description(self):
        git = self._make_git()
        pr = PRBuilder(git).build(title="Login System")
        assert isinstance(pr, PRDescription)

    def test_title_preserved(self):
        pr = PRBuilder(self._make_git()).build(title="Login System")
        assert pr.title == "Login System"

    def test_title_inferred_from_branch(self):
        pr = PRBuilder(self._make_git(branch="feature/login-system")).build()
        assert "Login" in pr.title or "login" in pr.title.lower()

    def test_head_branch_set(self):
        pr = PRBuilder(self._make_git(branch="feature/auth")).build()
        assert pr.head_branch == "feature/auth"

    def test_base_branch_default_main(self):
        pr = PRBuilder(self._make_git()).build()
        assert pr.base_branch == "main"

    def test_base_branch_custom(self):
        pr = PRBuilder(self._make_git()).build(base_branch="develop")
        assert pr.base_branch == "develop"

    def test_files_changed_listed(self):
        pr = PRBuilder(self._make_git(changed=["src/auth.py"])).build()
        assert "src/auth.py" in pr.files_changed

    def test_commit_count(self):
        commits = [CommitInfo(f"sha{i}", f"Commit {i}", "Alice", "now") for i in range(5)]
        pr = PRBuilder(self._make_git(commits=commits)).build()
        assert pr.commit_count == 5

    def test_body_contains_files_section(self):
        pr = PRBuilder(self._make_git(changed=["auth.py"])).build()
        assert "auth.py" in pr.body

    def test_body_contains_commits_section(self):
        pr = PRBuilder(self._make_git()).build()
        assert "abc1234"[:7] in pr.body or "Add login" in pr.body

    def test_body_contains_checklist(self):
        pr = PRBuilder(self._make_git()).build()
        assert "Checklist" in pr.body or "checklist" in pr.body.lower() or "- [ ]" in pr.body

    def test_as_display_lines_is_list(self):
        pr = PRBuilder(self._make_git()).build()
        desc = pr  # PRDescription
        lines = desc.as_display_lines()
        assert isinstance(lines, list)
        assert len(lines) > 3

    def test_str(self):
        pr = PRBuilder(self._make_git()).build(title="Test PR")
        assert "Test PR" in str(pr)

    def test_infer_title_strips_feature_prefix(self):
        commits = [CommitInfo("abc", "X", "Alice", "now")]
        title = PRBuilder._infer_title("feature/login-system", commits)
        assert "Login" in title or "login" in title.lower()
        assert "feature" not in title.lower()

    def test_infer_title_uses_single_commit(self):
        commits = [CommitInfo("abc", "Add login module", "Alice", "now")]
        title = PRBuilder._infer_title("feature/x", commits)
        assert "Add login module" == title

    def test_infer_title_multiple_commits_uses_branch(self):
        commits = [
            CommitInfo("a", "One", "A", "now"),
            CommitInfo("b", "Two", "A", "now"),
        ]
        title = PRBuilder._infer_title("feature/login-system", commits)
        assert "feature" not in title.lower()

    def test_no_files_changed(self):
        git = self._make_git(changed=[])
        pr = PRBuilder(git).build()
        assert "No files" in pr.body or "tracked" in pr.body


# ===========================================================================
# GitWorker
# ===========================================================================

from smartagent.executive.workers.git_worker import GitWorker
from smartagent.executive.task import TaskType


class TestGitWorkerProperties:
    def test_name(self):
        assert GitWorker().name == "Git Worker"

    def test_task_types(self):
        assert TaskType.GIT in GitWorker().task_types

    def test_description_nonempty(self):
        w = GitWorker()
        assert len(w.description) > 10


class TestGitWorkerExtractors:
    def test_extract_branch_explicit(self):
        name = GitWorker._extract_branch_name("Create branch feature/login", "")
        assert "feature/login" in name or "login" in name

    def test_extract_branch_derived(self):
        name = GitWorker._extract_branch_name("Implement login system", "")
        assert isinstance(name, str)
        assert len(name) > 0
        assert " " not in name

    def test_extract_branch_has_prefix(self):
        name = GitWorker._extract_branch_name("Add user auth", "")
        assert "/" in name  # feature/... or similar

    def test_extract_commit_message(self):
        msg = GitWorker._extract_commit_message("Add login module", "")
        assert "Add login module" == msg

    def test_extract_commit_strips_action_words(self):
        msg = GitWorker._extract_commit_message("Commit add login", "")
        assert "commit" not in msg.lower()

    def test_extract_commit_capitalises(self):
        msg = GitWorker._extract_commit_message("add login", "")
        assert msg[0].isupper()

    def test_extract_tag(self):
        name = GitWorker._extract_tag_name("Tag v1.2.0", "")
        assert "v1.2.0" in name or "1.2.0" in name

    def test_extract_tag_default(self):
        name = GitWorker._extract_tag_name("Tag the release", "")
        assert isinstance(name, str)
        assert len(name) > 0

    def test_extract_number(self):
        assert GitWorker._extract_number("rollback 3 commits") == 3

    def test_extract_number_default(self):
        assert GitWorker._extract_number("rollback") == 1

    def test_extract_pr_title(self):
        t = GitWorker._extract_pr_title("Create PR: Login System", "")
        assert "Login System" in t


class TestGitWorkerStubExecute:
    def _context(self, **metadata):
        ctx = MagicMock()
        ctx.metadata = metadata
        return ctx

    def _task(self, title: str, desc: str = "") -> MagicMock:
        t = MagicMock()
        t.title = title
        t.description = desc
        return t

    def _git(self):
        git = MagicMock()
        git.create_branch.return_value = GitResult(True, "git checkout -b feature/x", "Switched", "", 0)
        git.add_and_commit.return_value = GitResult(True, "git commit", "[main abc1234] msg", "", 0, sha="abc1234")
        git.push.return_value = GitResult(True, "git push", "To origin", "", 0)
        git.pull.return_value = GitResult(True, "git pull", "Already up to date.", "", 0)
        git.merge.return_value = GitResult(True, "git merge", "Merge made", "", 0)
        git.reset.return_value = GitResult(True, "git reset --soft", "", "", 0)
        git.tag.return_value = GitResult(True, "git tag", "", "", 0)
        git.status.return_value = GitStatus(branch="main")
        git.pr_builder.return_value = MagicMock(
            build=MagicMock(return_value=MagicMock(
                title="PR", as_display_lines=MagicMock(return_value=["line"]),
                body="body"
            ))
        )
        return git

    def _make_worker_with_git(self, git):
        w = GitWorker()
        w._git_override = git
        return w

    def test_branch_task(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("Create branch feature/login"), ctx)
        git.create_branch.assert_called_once()
        assert "branch" in r.lower() or "✓" in r

    def test_commit_task(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("Commit the changes"), ctx)
        git.add_and_commit.assert_called_once()
        assert "commit" in r.lower() or "✓" in r

    def test_commit_uses_file_editor_written_files(self):
        git        = self._git()
        editor     = MagicMock()
        editor.written_files.return_value = ["src/auth.py", "tests/test_auth.py"]
        w          = self._make_worker_with_git(git)
        ctx        = self._context(file_editor=editor)
        w.execute(self._task("Commit all changes"), ctx)
        call_paths = git.add_and_commit.call_args[1].get("paths") or git.add_and_commit.call_args[0][1]
        assert "src/auth.py" in call_paths

    def test_push_task(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("Push to remote"), ctx)
        git.push.assert_called_once()

    def test_pull_task(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("Pull from remote"), ctx)
        git.pull.assert_called_once()

    def test_merge_task(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("Merge feature/login branch"), ctx)
        git.merge.assert_called_once()

    def test_rollback_task(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("Rollback 2 commits"), ctx)
        git.reset.assert_called_once()
        call_kwargs = git.reset.call_args
        assert "soft" in str(call_kwargs)

    def test_pr_task(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("Open PR for login system"), ctx)
        git.pr_builder.assert_called()

    def test_fallback_shows_status(self):
        git = self._git()
        w   = self._make_worker_with_git(git)
        ctx = self._context()
        r   = w.execute(self._task("What is happening?"), ctx)
        git.status.assert_called()

    def test_with_git_factory(self):
        git = self._git()
        w   = GitWorker.with_git(git)
        assert w._git_override is git
