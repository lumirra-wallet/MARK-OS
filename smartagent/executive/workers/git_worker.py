"""
GitWorker — Milestone 21: Git Engine.

Specialist worker for GIT tasks inside an Orchestrator execution plan.

Two usage modes
---------------
1. **Orchestrator mode** — wired into the WorkerRegistry for ``GIT`` tasks.
   Receives full :class:`~smartagent.executive.execution_context.ExecutionContext`
   with injected ``git_client``, ``file_editor``, and optionally a
   ``model_manager``.

2. **Direct mode** — instantiated and called by the CEO pipeline or console
   commands with a bare :class:`~smartagent.git.git_client.GitClient`.

Stub behaviour (Phase 2)
------------------------
Keyword routing:  task title → git operation(s).

  * "branch" / "create branch"  → ``git.create_branch(…)``
  * "commit"                    → ``git.add_and_commit(…)``
  * "push"                      → ``git.push(…)``
  * "pull"                      → ``git.pull()``
  * "merge"                     → ``git.merge(…)``
  * "tag"                       → ``git.tag(…)``
  * "rollback" / "reset"        → ``git.reset(…)``
  * "pr" / "pull request"       → build PR description
  * (anything else)             → ``git.status()``

Ollama behaviour (Phase 4)
--------------------------
When a ``model_manager`` is available, the worker asks the LLM to emit a
structured set of git commands (branch name, commit message, etc.) and
executes them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task
    from smartagent.git.git_client import GitClient


# ---------------------------------------------------------------------------
# GitWorker
# ---------------------------------------------------------------------------

class GitWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for Git operations inside the Orchestrator execution graph.

    Handles: ``TaskType.GIT``
    """

    _system_prompt = """\
You are a senior Git engineer for MARK, an AI assistant.

Given a task description, emit ONE JSON object with these optional fields:
  "branch"   — branch name to create (snake_case or kebab-case, no spaces)
  "commit"   — commit message (imperative, ≤72 chars, no period at end)
  "push"     — true/false
  "merge"    — branch name to merge into current
  "tag"      — tag name
  "pr_title" — pull-request title

Rules:
- Branch names: lowercase, hyphens, no spaces. Prefix: feature/, fix/, chore/.
- Commit messages: imperative mood ("Add login" not "Added login").
- Only include fields that are explicitly required by the task.
- Output ONLY the JSON — no markdown, no explanation.\
"""

    _preferred_model = "coding"

    @property
    def name(self) -> str:
        return "Git Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.GIT]

    @property
    def description(self) -> str:
        return (
            "Performs Git operations: branch, add, commit, push, pull, "
            "merge, tag, rollback, and PR description generation."
        )

    # ------------------------------------------------------------------
    # BaseWorker interface
    # ------------------------------------------------------------------

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        git = self._resolve_git(context)

        # Phase 4: AI-powered execution
        mm = context.metadata.get("model_manager")
        if mm is not None:
            return self._execute_with_ai(task, context, git, mm)

        # Phase 2: keyword-routed stub
        return self._stub_execute(task, context, git)

    # ------------------------------------------------------------------
    # Stub execution (Phase 2)
    # ------------------------------------------------------------------

    def _stub_execute(
        self,
        task: "Task",
        context: "ExecutionContext",
        git: "GitClient",
    ) -> str:
        title = (task.title or "").lower()
        desc  = (task.description or "").lower()
        combined = f"{title} {desc}"

        results: list[str] = []

        # --- Branch creation -------------------------------------------
        if any(k in combined for k in ("create branch", "new branch", "feature branch")):
            branch_name = self._extract_branch_name(task.title, task.description)
            r = git.create_branch(branch_name)
            if r.success:
                results.append(f"✓ Created branch: {branch_name}")
            else:
                results.append(f"✗ Branch failed: {r.error_summary}")

        # --- Commit -------------------------------------------------------
        # Guard: "rollback 2 commits" contains "commit" — check rollback first.
        elif "commit" in combined and not any(k in combined for k in ("rollback", "reset", "undo")):
            # Use files from FileEditor if available
            file_editor = context.metadata.get("file_editor")
            paths = "."
            if file_editor is not None:
                written = file_editor.written_files()
                if written:
                    paths = written

            msg = self._extract_commit_message(task.title, task.description)
            r   = git.add_and_commit(msg, paths=paths)
            if r.success:
                sha = f" [{r.sha}]" if r.sha else ""
                results.append(f"✓ Committed: {msg}{sha}")
                if r.output.strip():
                    for line in r.output.strip().splitlines()[:4]:
                        results.append(f"  {line}")
            else:
                results.append(f"✗ Commit failed: {r.error_summary}")

        # --- Push ---------------------------------------------------------
        elif "push" in combined:
            upstream = "upstream" in combined or "set-upstream" in combined
            r = git.push(set_upstream=upstream)
            if r.success:
                results.append(f"✓ Pushed to remote")
            else:
                results.append(f"✗ Push failed: {r.error_summary}")

        # --- Pull ---------------------------------------------------------
        elif "pull" in combined:
            r = git.pull()
            if r.success:
                results.append(f"✓ Pulled from remote")
            else:
                results.append(f"✗ Pull failed: {r.error_summary}")

        # --- Merge --------------------------------------------------------
        elif "merge" in combined:
            branch_name = self._extract_branch_name(task.title, task.description)
            r = git.merge(branch_name)
            if r.success:
                results.append(f"✓ Merged: {branch_name}")
            else:
                results.append(f"✗ Merge failed: {r.error_summary}")

        # --- Tag ----------------------------------------------------------
        elif "tag" in combined:
            tag_name = self._extract_tag_name(task.title, task.description)
            r = git.tag(tag_name)
            if r.success:
                results.append(f"✓ Tagged: {tag_name}")
            else:
                results.append(f"✗ Tag failed: {r.error_summary}")

        # --- Rollback / reset ---------------------------------------------
        elif any(k in combined for k in ("rollback", "reset", "undo")):
            n = self._extract_number(combined, default=1)
            r = git.reset(mode="soft", target=f"HEAD~{n}")
            if r.success:
                results.append(f"✓ Rolled back {n} commit(s) (soft)")
            else:
                results.append(f"✗ Rollback failed: {r.error_summary}")

        # --- PR description -----------------------------------------------
        elif any(k in combined for k in ("pull request", " pr", "open pr")):
            pr_title = self._extract_pr_title(task.title, task.description)
            try:
                pr = git.pr_builder().build(title=pr_title or None)
                results.append(f"✓ PR description generated: {pr.title}")
                results += pr.as_display_lines()
            except Exception as exc:  # noqa: BLE001
                results.append(f"✗ PR generation failed: {exc}")

        # --- Fallback: status ---------------------------------------------
        else:
            status = git.status()
            results = ["Git status:"] + status.as_display_lines()

        return "\n".join(results) if results else "✓ Git operation complete"

    # ------------------------------------------------------------------
    # AI execution (Phase 4)
    # ------------------------------------------------------------------

    def _execute_with_ai(
        self,
        task: "Task",
        context: "ExecutionContext",
        git: "GitClient",
        model_manager: Any,
    ) -> str:
        """Ask the LLM to emit structured git commands, then execute them."""
        import json

        status = git.status()
        prompt = (
            f"Current git state:\n{status.as_ai_summary()}\n\n"
            f"Task: {task.title}\n"
            f"Description: {task.description or '(none)'}\n\n"
            f"Emit a JSON object with the git operations to perform."
        )

        try:
            response = ""
            if hasattr(model_manager, "chat_stream"):
                for chunk in model_manager.chat_stream(messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user",   "content": prompt},
                ]):
                    response += chunk
            elif hasattr(model_manager, "generate"):
                response = model_manager.generate(
                    prompt=prompt, system=self._system_prompt
                )

            # Extract JSON from the response
            m = re.search(r"\{.*?\}", response, re.DOTALL)
            if not m:
                return self._stub_execute(task, context, git)

            plan = json.loads(m.group())
        except Exception:  # noqa: BLE001
            return self._stub_execute(task, context, git)

        results: list[str] = []

        if branch := plan.get("branch"):
            r = git.create_branch(branch)
            results.append(f"{'✓' if r else '✗'} branch: {branch}")

        if commit_msg := plan.get("commit"):
            file_editor = context.metadata.get("file_editor")
            paths = "."
            if file_editor:
                written = file_editor.written_files()
                if written:
                    paths = written
            r = git.add_and_commit(commit_msg, paths=paths)
            sha = f" [{r.sha}]" if r.sha else ""
            results.append(f"{'✓' if r else '✗'} commit: {commit_msg}{sha}")

        if plan.get("push"):
            r = git.push(set_upstream=True)
            results.append(f"{'✓' if r else '✗'} push")

        if merge_branch := plan.get("merge"):
            r = git.merge(merge_branch)
            results.append(f"{'✓' if r else '✗'} merge: {merge_branch}")

        if tag_name := plan.get("tag"):
            r = git.tag(tag_name)
            results.append(f"{'✓' if r else '✗'} tag: {tag_name}")

        if pr_title := plan.get("pr_title"):
            try:
                pr = git.pr_builder().build(title=pr_title)
                results.append(f"✓ PR: {pr.title}")
                results += pr.as_display_lines()
            except Exception:  # noqa: BLE001
                results.append(f"✗ PR generation failed")

        return "\n".join(results) if results else "✓ Git operations complete (no actions taken)"

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_git(cls, git: "GitClient") -> "GitWorker":
        """Create a GitWorker pre-wired with a specific GitClient."""
        w = cls()
        w._git_override = git  # type: ignore[attr-defined]
        return w

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_git(self, context: "ExecutionContext") -> "GitClient":
        """Get GitClient from context, override, or create a default one."""
        # Check instance override (set by with_git())
        if hasattr(self, "_git_override"):
            return self._git_override  # type: ignore[attr-defined]
        # Check context injection (by Orchestrator)
        git = context.metadata.get("git_client")
        if git is not None:
            return git
        # Fallback — create one at cwd
        from smartagent.git.git_client import GitClient
        return GitClient()

    @staticmethod
    def _extract_branch_name(title: str, description: str | None) -> str:
        """Extract or derive a git branch name from the task text."""
        combined = f"{title} {description or ''}"
        # Look for explicit branch name patterns
        patterns = [
            r"branch[:\s]+['\"]?([a-zA-Z0-9/_\-]+)['\"]?",
            r"(?:feature|fix|bugfix|hotfix|chore)/([a-zA-Z0-9/_\-]+)",
        ]
        for pat in patterns:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                return m.group(1).strip()

        # Derive from title words
        words = re.sub(r"[^a-zA-Z0-9\s]", "", title).lower().split()
        stop = {"create", "new", "branch", "feature", "implement", "add", "the", "a"}
        slug = "-".join(w for w in words if w not in stop)[:40]
        return f"feature/{slug}" if slug else "feature/task"

    @staticmethod
    def _extract_commit_message(title: str, description: str | None) -> str:
        """Derive a commit message from the task title."""
        # Remove action words that don't belong in a commit message
        clean = re.sub(r"^(commit|git commit|please commit)\s*", "", title, flags=re.IGNORECASE)
        clean = clean.strip().rstrip(".")
        # Capitalise first letter
        if clean:
            clean = clean[0].upper() + clean[1:]
        return clean or "Update files"

    @staticmethod
    def _extract_tag_name(title: str, description: str | None) -> str:
        """Extract or derive a tag name."""
        combined = f"{title} {description or ''}"
        m = re.search(r"(?:tag|version|v)[\s:]+([a-zA-Z0-9._\-]+)", combined, re.IGNORECASE)
        if m:
            return m.group(1)
        return "v0.1.0"

    @staticmethod
    def _extract_pr_title(title: str, description: str | None) -> str:
        """Extract or derive a PR title."""
        clean = re.sub(r"(?:open|create|make)\s+(?:a\s+)?(?:pull request|pr)\s*:?\s*", "", title, flags=re.IGNORECASE)
        return clean.strip() or ""

    @staticmethod
    def _extract_number(text: str, default: int = 1) -> int:
        """Extract the first integer from text, or return default."""
        m = re.search(r"\d+", text)
        return int(m.group()) if m else default
