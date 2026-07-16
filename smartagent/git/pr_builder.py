"""
PRBuilder — compose pull-request titles and bodies from git metadata.

``PRBuilder`` reads the git log, changed files, and branch name to produce
a structured :class:`PRDescription` that is ready to paste into GitHub,
GitLab, or Bitbucket.

Usage::

    from smartagent.git import GitClient

    git = GitClient("/path/to/repo")
    pr  = git.pr_builder().build(title="Login System", base_branch="main")

    print(pr.title)
    print(pr.body)
    print("\\n".join(pr.as_display_lines()))
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.git.git_client import GitClient


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PRDescription:
    """
    A fully-composed pull-request description.

    Attributes:
        title:         PR title.
        body:          Markdown PR body.
        head_branch:   Source branch (the one being merged in).
        base_branch:   Target branch (e.g. ``"main"``).
        files_changed: List of changed file paths.
        commit_count:  Number of commits in the branch.
        remote_url:    Inferred remote URL (may be empty).
    """

    title:         str
    body:          str
    head_branch:   str
    base_branch:   str
    files_changed: list[str] = field(default_factory=list)
    commit_count:  int = 0
    remote_url:    str = ""

    def as_display_lines(self) -> list[str]:
        """Format the PR description for console display."""
        separator = "─" * 60
        lines = [
            separator,
            f"  Title : {self.title}",
            f"  Branch: {self.head_branch} → {self.base_branch}",
            f"  Commits: {self.commit_count}  |  Files: {len(self.files_changed)}",
            separator,
            "",
        ]
        for line in self.body.splitlines():
            lines.append(f"  {line}")
        lines.append(separator)
        return lines

    def __str__(self) -> str:
        return f"## {self.title}\n\n{self.body}"


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class PRBuilder:
    """
    Compose a :class:`PRDescription` from the current git state.

    Args:
        git: A :class:`~smartagent.git.git_client.GitClient` for the repo.
    """

    def __init__(self, git: "GitClient") -> None:
        self._git = git

    def build(
        self,
        title: str | None = None,
        base_branch: str = "main",
        include_commits: int = 20,
    ) -> PRDescription:
        """
        Build a :class:`PRDescription` from the current repository state.

        Args:
            title:           PR title.  When omitted, inferred from the branch
                             name and commit log.
            base_branch:     The branch the PR targets.  Default ``"main"``.
            include_commits: Maximum number of commits to include in the body.

        Returns:
            :class:`PRDescription` ready for copy-paste into GitHub/GitLab.
        """
        head_branch = self._git.current_branch()
        remote_url  = self._git.remote_url()
        commits     = self._git.log(n=include_commits)
        changed     = self._git.changed_files(base=base_branch)

        # Infer title from branch name when not provided
        if not title:
            title = self._infer_title(head_branch, commits)

        body = self._compose_body(
            title=title,
            head_branch=head_branch,
            base_branch=base_branch,
            commits=commits,
            changed=changed,
        )

        return PRDescription(
            title=title,
            body=body,
            head_branch=head_branch,
            base_branch=base_branch,
            files_changed=changed,
            commit_count=len(commits),
            remote_url=remote_url,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_title(branch: str, commits) -> str:
        """
        Derive a readable PR title from the branch name and/or commits.

        Priority:
          1. Branch name, prettified (``feature/login-system`` → ``Login System``),
             when the branch has a recognised feature-prefix (indicating the
             name was chosen to describe the work).
          2. First commit subject (if only one commit and no meaningful prefix).
          3. Cleaned branch name (no prefix) as last resort.
        """
        _PREFIX_RE = re.compile(
            r"^(feature|feat|fix|bugfix|hotfix|chore|refactor|docs)/"
        )
        has_prefix = bool(_PREFIX_RE.match(branch))

        # Strip the prefix and prettify the branch name
        clean = _PREFIX_RE.sub("", branch)
        clean = clean.replace("-", " ").replace("_", " ").title()

        # When the branch name (after stripping the prefix) is descriptive —
        # more than one word or more than 3 characters — prefer it.
        # Short/single-char slugs like "x" fall through to the commit message.
        branch_is_descriptive = bool(clean) and (" " in clean or len(clean) > 3)

        if has_prefix and branch_is_descriptive:
            return clean

        # Single-commit PR — use the commit subject when available
        if len(commits) == 1 and commits[0].message:
            return commits[0].message.strip().rstrip(".")

        return clean or "Update"

    @staticmethod
    def _compose_body(
        title: str,
        head_branch: str,
        base_branch: str,
        commits: list,
        changed: list[str],
    ) -> str:
        """Compose the Markdown PR body."""
        sections: list[str] = []

        # Summary
        sections.append(f"Merges `{head_branch}` into `{base_branch}`.")

        # Changed files
        if changed:
            sections.append("\n## Files changed\n")
            # Group by directory
            by_dir: dict[str, list[str]] = {}
            for f in changed:
                d = f.rsplit("/", 1)[0] if "/" in f else ""
                by_dir.setdefault(d, []).append(f)

            for dir_, files in sorted(by_dir.items()):
                if dir_:
                    sections.append(f"**`{dir_}/`**")
                for fp in sorted(files):
                    name = fp.rsplit("/", 1)[-1]
                    sections.append(f"- `{name}`")
        else:
            sections.append("\n_No files tracked between branches (may be same-branch diff)._")

        # Commits
        if commits:
            sections.append("\n## Commits\n")
            for c in commits:
                sha   = c.sha[:7] if len(c.sha) >= 7 else c.sha
                msg   = c.message or "(no message)"
                sections.append(f"- `{sha}` {msg}")

        # Checklist
        sections.append(
            "\n## Checklist\n"
            "- [ ] Tests pass\n"
            "- [ ] Code reviewed\n"
            "- [ ] Documentation updated"
        )

        return "\n".join(sections)
