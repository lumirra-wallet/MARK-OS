"""
smartagent.git — Milestone 21: Git Engine.

MARK understands Git.  Every operation is available both as a Python API
(via :class:`GitClient`) and as a console command (``git <sub>``).

Key classes::

    GitClient    — thin, subprocess-backed wrapper for all Git operations
    GitStatus    — structured representation of ``git status`` output
    FileChange   — one changed/staged/untracked file
    CommitInfo   — one entry from ``git log``
    GitResult    — outcome of any Git operation (success, output, error)
    PRBuilder    — compose a pull-request title and body from git metadata

Usage::

    from smartagent.git import GitClient

    git = GitClient("/path/to/repo")

    if not git.is_repo():
        git.init()

    git.create_branch("feature/login")
    git.add(".")
    git.commit("Add login system")
    git.push(set_upstream=True)

    pr = git.pr_builder().build(title="Login System")
    print(pr.body)
"""

from smartagent.git.git_result import GitResult
from smartagent.git.git_status import CommitInfo, FileChange, GitStatus
from smartagent.git.git_client import GitClient
from smartagent.git.pr_builder import PRBuilder, PRDescription

__all__ = [
    "CommitInfo",
    "FileChange",
    "GitClient",
    "GitResult",
    "GitStatus",
    "PRBuilder",
    "PRDescription",
]
