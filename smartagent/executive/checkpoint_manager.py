"""
CheckpointManager — Task #11: Automatic git checkpoints after each milestone.

Creates a local git commit at the end of every successfully completed
milestone so each phase is trivially rollback-able via ``git revert`` or
``git reset --hard``.

Commit message format:
    checkpoint: milestone {phase}/{total} — {title} ✓  [{n} tasks]

Design rules:
- A commit is only made when **every** task in the milestone has status
  ``TaskStatus.COMPLETED`` (none failed or blocked).
- If git is unavailable, the workspace is not a git repo, or any subprocess
  call fails, the manager returns ``CheckpointResult(skipped=True)`` and
  logs a warning — it never raises.
- ``git add -A`` followed by ``git commit`` is run in the workspace directory.
  If there is nothing to commit (clean working tree), git exits with code 1;
  this is treated as a successful (trivially-skippable) checkpoint.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.milestone_planner import Milestone

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CheckpointResult:
    """
    Outcome of one ``CheckpointManager.commit()`` call.

    Attributes:
        success:  True when a commit was created successfully.
        skipped:  True when no commit was attempted (failed tasks, git absent,
                  or nothing to commit).
        sha:      First 8 characters of the commit hash (empty when skipped).
        message:  The commit message used (empty when skipped).
        error:    Error description when success=False and skipped=False.
    """

    success: bool = False
    skipped: bool = False
    sha: str = ""
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "skipped": self.skipped,
            "sha":     self.sha,
            "message": self.message,
            "error":   self.error,
        }


# ---------------------------------------------------------------------------
# CheckpointManager
# ---------------------------------------------------------------------------

class CheckpointManager:
    """
    Commits the workspace to git after each successful milestone.

    Args:
        workspace_path: Root directory to run ``git`` in.  Defaults to cwd.
    """

    def __init__(self, workspace_path: "str | Path | None" = None) -> None:
        import os
        self._workspace = Path(workspace_path or os.getcwd()).resolve()
        self._git_available: bool = self._detect_git()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _detect_git(self) -> bool:
        """Return True when git is found AND the workspace is inside a repo."""
        if not shutil.which("git"):
            logger.warning("CheckpointManager: git not found in PATH — skipping commits")
            return False
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.warning(
                    "CheckpointManager: workspace %s is not a git repo — skipping commits",
                    self._workspace,
                )
                return False
            return True
        except Exception as exc:
            logger.warning("CheckpointManager: git detection failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def commit(self, milestone: "Milestone") -> CheckpointResult:
        """
        Create a git commit for *milestone* if all its tasks completed.

        Returns a ``CheckpointResult`` — never raises.
        """
        from smartagent.executive.task import TaskStatus

        if not self._git_available:
            return CheckpointResult(skipped=True, error="git not available")

        # Guard: skip when any task did not complete successfully
        incomplete = [
            t for t in milestone.tasks
            if t.status != TaskStatus.COMPLETED
        ]
        if incomplete:
            reasons = ", ".join(
                f"{t.title!r}={t.status.value}" for t in incomplete
            )
            logger.info(
                "CheckpointManager: milestone %d has incomplete tasks (%s) — skipping",
                milestone.phase, reasons,
            )
            return CheckpointResult(skipped=True, error=f"incomplete tasks: {reasons}")

        msg = self._build_message(milestone)
        return self._run_commit(msg)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_message(self, milestone: "Milestone") -> str:
        """Build the standardised commit message."""
        return (
            f"checkpoint: milestone {milestone.phase}/{milestone.total} "
            f"— {milestone.title} ✓  [{len(milestone.tasks)} tasks]"
        )

    def _run_commit(self, message: str) -> CheckpointResult:
        """Stage all changes and create the commit.  Returns a CheckpointResult."""
        ws = str(self._workspace)
        try:
            # Stage everything
            add = subprocess.run(
                ["git", "add", "-A"],
                cwd=ws, capture_output=True, text=True, timeout=30,
            )
            if add.returncode != 0:
                return CheckpointResult(
                    success=False, skipped=True,
                    error=f"git add failed: {add.stderr.strip()}",
                )

            # Commit
            commit = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=ws, capture_output=True, text=True, timeout=30,
            )

            # "nothing to commit" exits with code 1 on most git versions
            if commit.returncode != 0:
                stderr = commit.stderr.strip()
                stdout = commit.stdout.strip()
                combined = f"{stdout} {stderr}".lower()
                if "nothing to commit" in combined or "nothing added" in combined:
                    logger.info("CheckpointManager: nothing to commit — checkpoint skipped")
                    return CheckpointResult(skipped=True, message=message)
                return CheckpointResult(
                    success=False, skipped=True,
                    error=f"git commit failed: {stderr or stdout}",
                )

            sha = self._parse_sha(commit.stdout)
            logger.info("CheckpointManager: checkpoint commit %s — %s", sha, message)
            return CheckpointResult(success=True, sha=sha, message=message)

        except subprocess.TimeoutExpired:
            return CheckpointResult(success=False, skipped=True, error="git timed out")
        except Exception as exc:  # noqa: BLE001
            logger.warning("CheckpointManager: unexpected error: %s", exc)
            return CheckpointResult(success=False, skipped=True, error=str(exc))

    @staticmethod
    def _parse_sha(stdout: str) -> str:
        """
        Extract the short commit SHA from ``git commit`` stdout.

        git commit outputs lines like::

            [main abc1234] checkpoint: …

        We grab the 7–40-char hex after the first ``]``.
        """
        # Pattern: "[branch-or-HEAD sha-prefix]"
        m = re.search(r"\[[\w/\-()]+\s+([0-9a-f]{4,40})\]", stdout)
        if m:
            return m.group(1)[:8]
        # Fallback: any 7-char hex sequence
        m = re.search(r"\b([0-9a-f]{7,40})\b", stdout)
        return m.group(1)[:8] if m else ""
