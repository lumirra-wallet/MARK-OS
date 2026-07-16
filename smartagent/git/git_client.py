"""
GitClient — the core Git interface for MARK.

A thin, subprocess-backed wrapper around Git.  Every operation returns a
:class:`~smartagent.git.git_result.GitResult` so callers always have a
structured, inspectable response — no surprises.

Usage::

    from smartagent.git import GitClient

    git = GitClient("/path/to/repo")

    if not git.is_repo():
        git.init()

    status = git.status()
    print("\\n".join(status.as_display_lines()))

    git.create_branch("feature/login")
    git.add(".")
    git.commit("Add login system")
    git.push(set_upstream=True)

All ``subprocess.run`` calls are isolated to :meth:`_run` so they can be
trivially mocked in tests.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import TYPE_CHECKING

from smartagent.git.git_result import GitResult
from smartagent.git.git_status import (
    CommitInfo,
    FileChange,
    GitStatus,
    parse_log_output,
    parse_porcelain_status,
)
from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.git.pr_builder import PRBuilder, PRDescription

logger = get_logger(__name__)

# Separator used in git log format strings — chosen to be very unlikely in messages
_LOG_SEP = "\x00"
_LOG_FORMAT = f"%H{_LOG_SEP}%s{_LOG_SEP}%an{_LOG_SEP}%ar"


class GitClient:
    """
    Subprocess-backed Git client scoped to a single repository root.

    Args:
        repo_path: Absolute or relative path to the repository root.
                   Defaults to the current working directory.
        timeout:   Per-command subprocess timeout in seconds.  Default 30.
    """

    def __init__(self, repo_path: str = ".", timeout: int = 30) -> None:
        self._repo_path = os.path.abspath(repo_path)
        self._timeout   = timeout

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def repo_path(self) -> str:
        """Absolute path to the repository root."""
        return self._repo_path

    def __repr__(self) -> str:
        return f"GitClient({self._repo_path!r})"

    # ------------------------------------------------------------------
    # Core subprocess runner
    # ------------------------------------------------------------------

    def _run(self, *args: str, timeout: int | None = None) -> GitResult:
        """
        Run ``git <args>`` in the repository directory.

        Returns a :class:`GitResult` — never raises.
        """
        cmd = ["git"] + list(args)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self._repo_path,
                timeout=timeout or self._timeout,
            )
            result = GitResult(
                success=proc.returncode == 0,
                command=" ".join(cmd),
                output=proc.stdout,
                error=proc.stderr,
                returncode=proc.returncode,
            )
            # Extract commit SHA from commit output if present
            if proc.returncode == 0 and args and args[0] == "commit":
                m = re.search(r"\[[\w/]+\s+([0-9a-f]{7,40})\]", proc.stdout)
                if m:
                    result.sha = m.group(1)
            return result
        except FileNotFoundError:
            return GitResult(
                success=False,
                command=" ".join(cmd),
                output="",
                error="git not found — install git and ensure it is on PATH",
                returncode=-1,
            )
        except subprocess.TimeoutExpired:
            return GitResult(
                success=False,
                command=" ".join(cmd),
                output="",
                error=f"git command timed out after {timeout or self._timeout}s",
                returncode=-1,
            )

    # ------------------------------------------------------------------
    # Repository state
    # ------------------------------------------------------------------

    def is_repo(self) -> bool:
        """Return ``True`` if *repo_path* is inside a git repository."""
        result = self._run("rev-parse", "--is-inside-work-tree")
        return result.success and result.output.strip() == "true"

    def init(self, bare: bool = False) -> GitResult:
        """Initialise a new git repository at *repo_path*."""
        args = ["init"]
        if bare:
            args.append("--bare")
        return self._run(*args)

    def clone(self, url: str, dest: str | None = None) -> GitResult:
        """Clone *url* into *dest* (or the default directory derived from the URL)."""
        args = ["clone", url]
        if dest:
            args.append(dest)
        return self._run(*args)

    # ------------------------------------------------------------------
    # Status / info
    # ------------------------------------------------------------------

    def status(self) -> GitStatus:
        """
        Return the current working-tree state as a :class:`GitStatus`.

        Equivalent to ``git status --porcelain=v1 -b``.
        """
        result = self._run("status", "--porcelain=v1", "-b")
        if not result.success:
            return GitStatus(branch="(unknown)")
        return parse_porcelain_status(result.output)

    def current_branch(self) -> str:
        """Return the name of the current branch, or ``"HEAD"`` when detached."""
        result = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return result.output.strip() if result.success else "HEAD"

    def log(self, n: int = 10) -> list[CommitInfo]:
        """
        Return the *n* most recent commits.

        Args:
            n: Maximum number of entries to return.

        Returns:
            List of :class:`CommitInfo`, newest first.
        """
        result = self._run(
            "log",
            f"--max-count={n}",
            f"--format={_LOG_FORMAT}",
            "--no-walk",      # avoid walking merges deeply
        )
        if not result.success or not result.output.strip():
            # Retry without --no-walk (valid for single-commit repos)
            result = self._run("log", f"--max-count={n}", f"--format={_LOG_FORMAT}")
        if not result.success:
            return []
        return parse_log_output(result.output, sep=_LOG_SEP)

    def diff(self, staged: bool = False, path: str | None = None) -> str:
        """
        Return the diff of working-tree (or staged) changes.

        Args:
            staged: When ``True``, show staged (index) diff.
            path:   Limit diff to a specific file path.

        Returns:
            Unified diff string.
        """
        args = ["diff"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
        return self._run(*args).output

    def show(self, commit: str = "HEAD") -> str:
        """Return the full diff for a specific commit."""
        return self._run("show", commit).output

    def remote_url(self, remote: str = "origin") -> str:
        """Return the fetch URL for *remote*, or empty string."""
        result = self._run("remote", "get-url", remote)
        return result.output.strip() if result.success else ""

    def list_remotes(self) -> dict[str, str]:
        """Return mapping of ``{remote_name: fetch_url}``."""
        result = self._run("remote", "-v")
        remotes: dict[str, str] = {}
        for line in result.output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "(fetch)" in line:
                remotes[parts[0]] = parts[1]
        return remotes

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    def create_branch(
        self,
        name: str,
        checkout: bool = True,
        from_branch: str | None = None,
    ) -> GitResult:
        """
        Create a new branch.

        Args:
            name:        New branch name.
            checkout:    Also switch to the new branch.  Default ``True``.
            from_branch: Base branch to branch from.  Defaults to HEAD.

        Returns:
            :class:`GitResult`
        """
        if checkout:
            args = ["checkout", "-b", name]
        else:
            args = ["branch", name]
        if from_branch:
            args.append(from_branch)
        result = self._run(*args)
        return result

    def checkout(self, branch: str) -> GitResult:
        """Switch to an existing branch."""
        return self._run("checkout", branch)

    def list_branches(self, all_branches: bool = False) -> list[str]:
        """
        Return branch names, current branch first.

        Args:
            all_branches: Include remote-tracking branches.
        """
        args = ["branch"]
        if all_branches:
            args.append("-a")
        result = self._run(*args)
        branches: list[str] = []
        current: str | None = None
        for line in result.output.splitlines():
            name = line.strip().lstrip("* ").strip()
            if name:
                if line.strip().startswith("*"):
                    current = name
                else:
                    branches.append(name)
        return ([current] if current else []) + branches

    def delete_branch(self, name: str, force: bool = False) -> GitResult:
        """Delete a branch. Use *force* to delete unmerged branches."""
        flag = "-D" if force else "-d"
        return self._run("branch", flag, name)

    def rename_branch(self, old: str, new: str) -> GitResult:
        """Rename a branch."""
        return self._run("branch", "-m", old, new)

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    def add(self, paths: list[str] | str = ".") -> GitResult:
        """
        Stage files for commit.

        Args:
            paths: A path string, list of paths, or ``"."`` for all changes.
        """
        if isinstance(paths, str):
            paths = [paths]
        return self._run("add", "--", *paths)

    def restore(self, path: str, staged: bool = False) -> GitResult:
        """
        Discard changes in a file.

        Args:
            path:   File to restore.
            staged: When ``True``, un-stage the file (``git restore --staged``).
        """
        args = ["restore"]
        if staged:
            args.append("--staged")
        args += ["--", path]
        return self._run(*args)

    def commit(
        self,
        message: str,
        all_changes: bool = False,
        allow_empty: bool = False,
    ) -> GitResult:
        """
        Create a commit from the current index.

        Args:
            message:      Commit message string.
            all_changes:  Automatically stage all tracked modifications
                          (``git commit -a``).
            allow_empty:  Allow an empty commit (useful for branch markers).
        """
        args = ["commit", "-m", message]
        if all_changes:
            args.insert(1, "-a")
        if allow_empty:
            args.append("--allow-empty")
        return self._run(*args)

    def add_and_commit(
        self,
        message: str,
        paths: list[str] | str = ".",
    ) -> GitResult:
        """
        Stage *paths* and commit in one step.

        Args:
            message: Commit message.
            paths:   Paths to stage (default ``"."`` = all).

        Returns:
            The :class:`GitResult` from the commit step.  If staging fails,
            returns the add result without committing.
        """
        add_result = self.add(paths)
        if not add_result.success:
            return add_result
        return self.commit(message)

    # ------------------------------------------------------------------
    # Remote operations
    # ------------------------------------------------------------------

    def push(
        self,
        remote: str = "origin",
        branch: str | None = None,
        set_upstream: bool = False,
        force: bool = False,
        tags: bool = False,
    ) -> GitResult:
        """
        Push to a remote.

        Args:
            remote:       Remote name.  Default ``"origin"``.
            branch:       Branch to push.  Defaults to current branch.
            set_upstream: Set the upstream tracking reference (``-u``).
            force:        Force push (``--force-with-lease``).
            tags:         Also push tags.
        """
        if branch is None:
            branch = self.current_branch()
        args = ["push"]
        if set_upstream:
            args += ["-u"]
        if force:
            args.append("--force-with-lease")
        if tags:
            args.append("--tags")
        args += [remote, branch]
        return self._run(*args, timeout=60)

    def pull(
        self,
        remote: str = "origin",
        branch: str | None = None,
        rebase: bool = False,
    ) -> GitResult:
        """
        Pull from a remote.

        Args:
            remote: Remote name.
            branch: Branch to pull.  Defaults to current branch's tracking branch.
            rebase: Use ``--rebase`` instead of merge.
        """
        args = ["pull"]
        if rebase:
            args.append("--rebase")
        args.append(remote)
        if branch:
            args.append(branch)
        return self._run(*args, timeout=60)

    def fetch(self, remote: str = "origin", all_remotes: bool = False) -> GitResult:
        """
        Fetch from a remote without merging.

        Args:
            remote:      Remote name.
            all_remotes: Fetch all configured remotes.
        """
        if all_remotes:
            return self._run("fetch", "--all", timeout=60)
        return self._run("fetch", remote, timeout=60)

    def add_remote(self, name: str, url: str) -> GitResult:
        """Add a remote named *name* pointing at *url*."""
        return self._run("remote", "add", name, url)

    def set_remote_url(self, name: str, url: str) -> GitResult:
        """Update the URL for an existing remote."""
        return self._run("remote", "set-url", name, url)

    # ------------------------------------------------------------------
    # Merge / rebase
    # ------------------------------------------------------------------

    def merge(
        self,
        branch: str,
        message: str | None = None,
        no_ff: bool = False,
        squash: bool = False,
    ) -> GitResult:
        """
        Merge *branch* into the current branch.

        Args:
            branch:  Branch to merge.
            message: Optional commit message override.
            no_ff:   Disable fast-forward merges.
            squash:  Squash all commits into a single staged change.
        """
        args = ["merge"]
        if no_ff:
            args.append("--no-ff")
        if squash:
            args.append("--squash")
        if message:
            args += ["-m", message]
        args.append(branch)
        return self._run(*args)

    def rebase(self, onto: str) -> GitResult:
        """Rebase the current branch onto *onto*."""
        return self._run("rebase", onto)

    def abort_merge(self) -> GitResult:
        """Abort an in-progress merge."""
        return self._run("merge", "--abort")

    # ------------------------------------------------------------------
    # Rollback / undo
    # ------------------------------------------------------------------

    def reset(
        self,
        mode: str = "soft",
        target: str = "HEAD~1",
    ) -> GitResult:
        """
        Reset the current branch HEAD.

        Args:
            mode:   ``"soft"`` (keep staged), ``"mixed"`` (unstage),
                    ``"hard"`` (discard all).
            target: Git ref to reset to.  Default ``"HEAD~1"``.
        """
        valid_modes = {"soft", "mixed", "hard", "merge", "keep"}
        if mode not in valid_modes:
            return GitResult(
                success=False,
                command=f"git reset --{mode} {target}",
                output="",
                error=f"invalid mode {mode!r}; choose from {sorted(valid_modes)}",
                returncode=1,
            )
        return self._run("reset", f"--{mode}", target)

    def revert(self, commit: str = "HEAD", no_edit: bool = True) -> GitResult:
        """Create a new commit that undoes the changes from *commit*."""
        args = ["revert", commit]
        if no_edit:
            args.append("--no-edit")
        return self._run(*args)

    def stash(self, message: str | None = None) -> GitResult:
        """Stash working-tree changes."""
        args = ["stash", "push"]
        if message:
            args += ["-m", message]
        return self._run(*args)

    def stash_pop(self) -> GitResult:
        """Apply and drop the most recent stash entry."""
        return self._run("stash", "pop")

    def stash_list(self) -> list[str]:
        """Return all stash entries as human-readable strings."""
        result = self._run("stash", "list")
        return [l.strip() for l in result.output.splitlines() if l.strip()]

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def config_get(self, key: str) -> str:
        """Read a git config value (e.g. ``"user.name"``)."""
        result = self._run("config", "--get", key)
        return result.output.strip() if result.success else ""

    def config_set(
        self,
        key: str,
        value: str,
        global_: bool = False,
    ) -> GitResult:
        """Write a git config value."""
        args = ["config"]
        if global_:
            args.append("--global")
        args += [key, value]
        return self._run(*args)

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def tag(
        self,
        name: str,
        message: str | None = None,
        commit: str | None = None,
    ) -> GitResult:
        """
        Create a tag.

        Args:
            name:    Tag name.
            message: Annotated tag message.  When omitted, creates a lightweight tag.
            commit:  SHA to tag.  Defaults to HEAD.
        """
        args = ["tag"]
        if message:
            args += ["-a", name, "-m", message]
        else:
            args.append(name)
        if commit:
            args.append(commit)
        return self._run(*args)

    def list_tags(self) -> list[str]:
        """Return all tag names, sorted."""
        result = self._run("tag", "--sort=-version:refname")
        return [t.strip() for t in result.output.splitlines() if t.strip()]

    def push_tags(self, remote: str = "origin") -> GitResult:
        """Push all tags to *remote*."""
        return self._run("push", remote, "--tags", timeout=60)

    def delete_tag(self, name: str) -> GitResult:
        """Delete a local tag."""
        return self._run("tag", "-d", name)

    # ------------------------------------------------------------------
    # PR helpers
    # ------------------------------------------------------------------

    def pr_builder(self) -> "PRBuilder":
        """Return a :class:`~smartagent.git.pr_builder.PRBuilder` for this repo."""
        from smartagent.git.pr_builder import PRBuilder
        return PRBuilder(self)

    def changed_files(self, base: str = "main") -> list[str]:
        """
        Return files changed between *base* and HEAD.

        Useful for computing the scope of a PR.
        """
        result = self._run("diff", "--name-only", f"{base}...HEAD")
        if not result.success:
            result = self._run("diff", "--name-only", f"{base}..HEAD")
        return [f.strip() for f in result.output.splitlines() if f.strip()]
