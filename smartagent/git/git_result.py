"""
GitResult — the outcome of any GitClient operation.

Every method on :class:`~smartagent.git.git_client.GitClient` returns a
``GitResult`` so callers always have a uniform, structured response to work
with — no ``subprocess.CalledProcessError`` surprises.

Usage::

    result = git.commit("Add login module")
    if result:
        print("Committed:", result.sha)
    else:
        print("Error:", result.error_summary)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GitResult:
    """
    Outcome of a single Git operation.

    Attributes:
        success:    ``True`` when the git command exited with code 0.
        command:    The full git command string that was run.
        output:     Combined stdout from the process.
        error:      Stderr from the process.
        returncode: Raw exit code.
        sha:        Commit SHA extracted from output (when relevant).
    """

    success:    bool
    command:    str
    output:     str
    error:      str
    returncode: int
    sha:        str = field(default="")

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __bool__(self) -> bool:
        return self.success

    def __str__(self) -> str:
        if self.success:
            body = self.output.strip()
            return body if body else "OK"
        return f"[git error] {self.error_summary}"

    @property
    def error_summary(self) -> str:
        """Return the most informative error string available."""
        if self.error.strip():
            return self.error.strip().splitlines()[-1]
        if self.output.strip():
            return self.output.strip().splitlines()[-1]
        return f"exit code {self.returncode}"

    @property
    def first_line(self) -> str:
        """First non-empty line of output."""
        for line in self.output.splitlines():
            if line.strip():
                return line.strip()
        return ""

    def as_display_lines(self) -> list[str]:
        """Format for console output."""
        icon = "✓" if self.success else "✗"
        lines = [f"{icon} {self.command}"]
        if self.output.strip():
            for line in self.output.strip().splitlines():
                lines.append(f"  {line}")
        if not self.success and self.error.strip():
            for line in self.error.strip().splitlines():
                lines.append(f"  [err] {line}")
        return lines
