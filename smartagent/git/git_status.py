"""
GitStatus — structured representation of ``git status`` and ``git log`` output.

Data model::

    FileChange   — one changed/staged/untracked file entry
    CommitInfo   — one line from ``git log``
    GitStatus    — complete snapshot of working-tree state

These are produced by :class:`~smartagent.git.git_client.GitClient` and are
designed to be easy to display, compare, and pass into AI prompts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Porcelain status code → human label
_STATUS_LABELS: dict[str, str] = {
    "M":  "modified",
    "A":  "added",
    "D":  "deleted",
    "R":  "renamed",
    "C":  "copied",
    "U":  "unmerged",
    "?":  "untracked",
    "!":  "ignored",
    " ":  "unchanged",
}


# ---------------------------------------------------------------------------
# FileChange
# ---------------------------------------------------------------------------

@dataclass
class FileChange:
    """
    A single file entry from ``git status --porcelain``.

    Attributes:
        path:        Workspace-relative file path (may include "→" for renames).
        status_code: Single-character git porcelain code (M, A, D, R, ??, …).
        staged:      Whether this change is in the index (staged).
    """

    path:        str
    status_code: str
    staged:      bool

    @property
    def status_label(self) -> str:
        """Human-readable status, e.g. ``"modified"``, ``"added"``."""
        code = self.status_code.strip()[:1]
        return _STATUS_LABELS.get(code, code)

    @property
    def icon(self) -> str:
        """Single-character console icon for the status."""
        code = self.status_code.strip()[:1]
        icons = {"M": "~", "A": "+", "D": "-", "R": "→", "U": "!", "?": "?"}
        return icons.get(code, code)

    def __str__(self) -> str:
        staging = "staged" if self.staged else "unstaged"
        return f"{self.icon} [{staging}] {self.path}"


# ---------------------------------------------------------------------------
# CommitInfo
# ---------------------------------------------------------------------------

@dataclass
class CommitInfo:
    """
    One entry from ``git log``.

    Attributes:
        sha:     Full or abbreviated commit SHA.
        message: Subject line of the commit message.
        author:  Author name.
        date:    Human-readable relative date, e.g. ``"2 days ago"``.
    """

    sha:     str
    message: str
    author:  str
    date:    str

    def __str__(self) -> str:
        short_sha = self.sha[:7] if len(self.sha) > 7 else self.sha
        return f"{short_sha} {self.message}  ({self.author}, {self.date})"

    @property
    def short_sha(self) -> str:
        return self.sha[:7]


# ---------------------------------------------------------------------------
# GitStatus
# ---------------------------------------------------------------------------

@dataclass
class GitStatus:
    """
    Complete snapshot of a Git working tree.

    Attributes:
        branch:    Current branch name.
        ahead:     Commits ahead of the upstream tracking branch.
        behind:    Commits behind the upstream tracking branch.
        staged:    Files staged for the next commit.
        unstaged:  Files with working-tree changes not yet staged.
        untracked: Files not tracked by Git.
        remote:    Upstream remote/branch string (e.g. ``"origin/main"``).
    """

    branch:    str
    ahead:     int = 0
    behind:    int = 0
    staged:    list[FileChange] = field(default_factory=list)
    unstaged:  list[FileChange] = field(default_factory=list)
    untracked: list[FileChange] = field(default_factory=list)
    remote:    str = ""

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def is_clean(self) -> bool:
        """True when there are no staged, unstaged, or untracked files."""
        return not (self.staged or self.unstaged or self.untracked)

    @property
    def total_changes(self) -> int:
        return len(self.staged) + len(self.unstaged) + len(self.untracked)

    @property
    def has_staged(self) -> bool:
        return bool(self.staged)

    @property
    def ready_to_commit(self) -> bool:
        """True when there are staged changes and nothing to merge."""
        return bool(self.staged)

    @property
    def sync_status(self) -> str:
        """Human-readable remote sync state."""
        if not self.remote:
            return "no remote"
        if self.ahead and self.behind:
            return f"↑{self.ahead} ↓{self.behind} (diverged)"
        if self.ahead:
            return f"↑{self.ahead} ahead of {self.remote}"
        if self.behind:
            return f"↓{self.behind} behind {self.remote}"
        return f"up to date with {self.remote}"

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def as_display_lines(self) -> list[str]:
        """Format the status for console output."""
        lines: list[str] = []

        # Header
        branch_line = f"  Branch: {self.branch}"
        if self.remote:
            branch_line += f"  [{self.sync_status}]"
        lines.append(branch_line)

        if self.is_clean:
            lines.append("  ✓ Working tree clean")
            return lines

        # Staged
        if self.staged:
            lines.append(f"\n  Staged ({len(self.staged)}):")
            for fc in self.staged:
                lines.append(f"    {fc.icon} {fc.path}")

        # Unstaged
        if self.unstaged:
            lines.append(f"\n  Not staged ({len(self.unstaged)}):")
            for fc in self.unstaged:
                lines.append(f"    {fc.icon} {fc.path}")

        # Untracked
        if self.untracked:
            lines.append(f"\n  Untracked ({len(self.untracked)}):")
            for fc in self.untracked[:10]:
                lines.append(f"    ? {fc.path}")
            if len(self.untracked) > 10:
                lines.append(f"    … and {len(self.untracked) - 10} more")

        return lines

    def as_ai_summary(self) -> str:
        """Compact text for inclusion in an AI prompt."""
        parts = [f"Branch: {self.branch}"]
        if self.remote:
            parts.append(self.sync_status)
        if self.staged:
            paths = ", ".join(fc.path for fc in self.staged[:5])
            parts.append(f"Staged: {paths}")
        if self.unstaged:
            paths = ", ".join(fc.path for fc in self.unstaged[:5])
            parts.append(f"Modified: {paths}")
        if self.untracked:
            parts.append(f"Untracked: {len(self.untracked)} file(s)")
        if self.is_clean:
            parts.append("Clean working tree")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Parsing helpers (used by GitClient internally)
# ---------------------------------------------------------------------------

_AHEAD_RE  = re.compile(r"ahead (\d+)")
_BEHIND_RE = re.compile(r"behind (\d+)")


def parse_porcelain_status(output: str) -> GitStatus:
    """
    Parse the output of ``git status --porcelain=v1 -b`` into a
    :class:`GitStatus`.

    This function is internal to the git package; external code should
    call :meth:`GitClient.status` instead.
    """
    lines   = output.splitlines()
    branch  = ""
    remote  = ""
    ahead   = 0
    behind  = 0
    staged:    list[FileChange] = []
    unstaged:  list[FileChange] = []
    untracked: list[FileChange] = []

    for line in lines:
        # Branch / tracking header (porcelain v1)
        if line.startswith("## "):
            rest = line[3:]
            if "..." in rest:
                branch_part, remote_rest = rest.split("...", 1)
                branch = branch_part.strip()
                # remote/branch [ahead N, behind M]
                remote = remote_rest.split("[")[0].strip()
                m = _AHEAD_RE.search(line)
                if m:
                    ahead = int(m.group(1))
                m = _BEHIND_RE.search(line)
                if m:
                    behind = int(m.group(1))
            else:
                # No upstream — "## main" or "## No commits yet on main"
                branch = rest.split(" ")[0].strip()
            continue

        if len(line) < 3:
            continue

        x     = line[0]   # index (staged)
        y     = line[1]   # working tree
        path  = line[3:]  # may contain " -> " for renames

        # Untracked
        if x == "?" and y == "?":
            untracked.append(FileChange(path=path, status_code="?", staged=False))
            continue

        # Staged change
        if x != " ":
            staged.append(FileChange(path=path, status_code=x, staged=True))

        # Unstaged change
        if y not in (" ", "?"):
            unstaged.append(FileChange(path=path, status_code=y, staged=False))

    return GitStatus(
        branch=branch,
        ahead=ahead,
        behind=behind,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        remote=remote,
    )


def parse_log_output(output: str, sep: str = "\x00") -> list[CommitInfo]:
    """
    Parse the output of ``git log --format=<sha><sep><msg><sep><author><sep><date>``
    into a list of :class:`CommitInfo`.
    """
    commits: list[CommitInfo] = []
    for block in output.strip().split("\n"):
        block = block.strip()
        if not block:
            continue
        parts = block.split(sep)
        if len(parts) >= 4:
            commits.append(CommitInfo(
                sha=parts[0].strip(),
                message=parts[1].strip(),
                author=parts[2].strip(),
                date=parts[3].strip(),
            ))
        elif len(parts) == 1 and len(parts[0]) >= 7:
            # Fallback: bare SHA only
            commits.append(CommitInfo(
                sha=parts[0][:40],
                message="",
                author="",
                date="",
            ))
    return commits
