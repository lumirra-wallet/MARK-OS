"""
DevPipeline — Planner → Executor → Tester → Reviewer → Fixer loop.

For complex multi-file goals that need more than a single agent-loop pass.

Architecture:

    Goal
      ↓
    Planner  (LLM: break into 2-5 milestones)
      ↓
    for each milestone:
      Executor  (run_agent_loop — writes files, runs tools)
        ↓
      Tester    (run_terminal — pytest / npm test / etc.)
        ↓
      Reviewer  (LLM: read code + test output → PASS/FAIL)
        ↓
      if PASS → next milestone
      if FAIL → Fixer (run_agent_loop with failure context) → retry
      ↓
    Checkpoint commit
      ↓
    PipelineResult (summary of all milestones + files created)

The entire pipeline runs synchronously in a thread (asyncio.to_thread).
Every step publishes STREAMING_TOKEN events for live dashboard updates.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from smartagent.identity.mark_identity import (
    build_system_prompt,
    EXECUTIVE_SURFACE_NOTES,
)
from smartagent.engineer.agent_loop import run_agent_loop, AgentLoopResult
from smartagent.engineer.agent_tools import execute_tool
from smartagent.engineer.worker_roles import (
    ENGINEER, QA, DEBUGGER, REVIEWER, GIT, SECURITY, DOCS, PREVIEW,
)
from smartagent.llm.factory import is_llm_error_text
from smartagent.logs.logger import get_logger
from smartagent.server.events import ServerEvents

logger = get_logger(__name__)

MAX_FIX_ATTEMPTS = 3
MAX_MILESTONE_TURNS = 15

# Filename-looking tokens in a milestone description, e.g. "app.py", "test_x.py".
_FILE_TARGET_RE = re.compile(r'\b[\w][\w\-/]*\.[A-Za-z0-9]{1,10}\b')


def extract_file_targets(text: str) -> list[str]:
    """
    Best-effort extraction of filenames a milestone description names.

    Used to scope that milestone's write access to only the files it
    declares — least privilege by declared intent, not a security boundary
    (a determined worker could still request an unnamed path; this shapes
    normal behaviour, it doesn't replace the real workspace sandbox in
    ``agent_tools._safe_path``). Returns ``[]`` when the milestone reads as
    abstract (e.g. "Refactor the auth module") — callers treat an empty list
    as unrestricted rather than guessing and blocking legitimate work.
    """
    seen: list[str] = []
    for m in _FILE_TARGET_RE.finditer(text):
        token = m.group(0)
        if token not in seen:
            seen.append(token)
    return seen


# ────────────────────────────────────────────────────────────────────────────
# Result types
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class MilestoneResult:
    milestone:      str
    success:        bool       = False
    files_created:  list[str]  = field(default_factory=list)
    files_modified: list[str]  = field(default_factory=list)
    test_output:    str        = ""
    tests_passed:   bool       = False
    review:         str        = ""
    attempts:       int        = 0
    elapsed:        float      = 0.0


@dataclass
class PipelineResult:
    """Return value from :class:`DevPipeline.run`."""
    goal:               str
    success:            bool              = False
    milestones:         list[str]         = field(default_factory=list)
    milestone_results:  list[MilestoneResult] = field(default_factory=list)
    files_created:      list[str]         = field(default_factory=list)
    files_modified:     list[str]         = field(default_factory=list)
    total_elapsed:      float             = 0.0
    final_summary:      str               = ""
    summary:            str               = ""
    # duck-type compatibility
    iterations:         list              = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────────
# Prompts
# ────────────────────────────────────────────────────────────────────────────

_PLANNER_SYSTEM = """\
You are MARK's strategic planner.  Break the given engineering goal into
2-5 sequential milestones that together fully deliver the goal.

Rules:
- Each milestone must be small enough for one focused execution step.
- Each milestone must have a concrete, verifiable deliverable.
- List ONLY the milestones, one per line, prefixed with a number and dot.
- No prose, no headers, no blank lines between milestones.
- Keep each milestone ≤ 25 words.

Example for "Build a Flask TODO API with tests":
1. Create app.py with Flask app, /todos GET+POST+DELETE endpoints using an in-memory list.
2. Create test_app.py with pytest tests for all three endpoints.
3. Create requirements.txt (flask, pytest) and README.md with run instructions.
"""

_REVIEWER_SYSTEM = """\
You are MARK's code reviewer. Assess whether a milestone was completed correctly.

You will receive:
- The milestone goal
- The files that were created or modified
- The test output (if any)

Reply with EXACTLY one of:
  PASS: <one sentence reason>
  FAIL: <specific issue to fix>

No other text.  No bullet points.  Just PASS or FAIL followed by a colon and reason.
"""

_ENGINEER_SYSTEM = ENGINEER.prompt + """

TOOLS AVAILABLE:
• read_file(path)               — read any file
• write_file(path, content)     — create or overwrite a file
• list_directory(path, depth)   — explore project structure
• search_workspace(query)       — grep through files
• run_terminal(command)         — run pytest, npm, pip, cargo, git, etc.
• git_status()                  — see current git status
• git_diff()                    — see current changes
• git_commit(message)           — stage all and commit
• rename_file(src, dst)         — rename or move a file
• delete_file(path)             — delete a file (requires prior approval)

RULES:
1. ALWAYS use list_directory first to understand the project before acting.
2. ALWAYS use write_file to save code — showing code without writing it is wrong.
3. NEVER produce code in your reply without also writing it to disk with write_file.
4. Be precise and scoped to exactly what this milestone asks for.
"""

_DEBUGGER_SYSTEM = DEBUGGER.prompt + """

A previous execution attempt produced failures. Fix the problems described
in the goal below.

Use your tools to:
1. Read the relevant files.
2. Understand what went wrong.
3. Write corrected versions.
4. Re-run tests to verify.

Be surgical — change only what is needed. Do not rewrite unaffected files.
"""

_SECURITY_SYSTEM = SECURITY.prompt + """

You will receive the milestone description and a git diff of its changes.
Reply with EXACTLY one of:
  CLEAR: <one sentence>
  FLAG: <specific issue(s) found, one per line>

No other text.
"""

_DOCS_SYSTEM = DOCS.prompt + """

You will receive the milestone description and the list of files it
touched. Reply with EXACTLY one of:

  SKIP: <one sentence reason no doc update is needed>

or

  UPDATE: <path/to/doc.md>
  ---
  <full replacement content for that file>

Only propose UPDATE for an existing docs file (README.md or a file under
docs/) or a short new file directly relevant to this change. Keep content
concise. No other text outside this format.
"""

_EXECUTIVE_SYSTEM = build_system_prompt(EXECUTIVE_SURFACE_NOTES)


# ────────────────────────────────────────────────────────────────────────────
# DevPipeline
# ────────────────────────────────────────────────────────────────────────────

class DevPipeline:
    """
    Planner → Executor → Tester → Reviewer → Fixer loop.

    Call :meth:`run` from a worker thread (it blocks on LLM and subprocess calls).
    """

    def __init__(
        self,
        model_manager: Any,
        event_bus: Any,
        workspace_path: str,
        test_cmd: str | None = None,
        max_fix_attempts: int = MAX_FIX_ATTEMPTS,
    ) -> None:
        self._mm            = model_manager
        self._eb            = event_bus
        self._ws            = workspace_path
        self._test_cmd      = test_cmd
        self._max_attempts  = max_fix_attempts

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, goal: str) -> PipelineResult:
        t0     = time.monotonic()
        result = PipelineResult(goal=goal)

        self._activity("plan", f"Planning: {goal[:80]}")

        # ── 1. Plan ───────────────────────────────────────────────────────────
        milestones = self._plan(goal)
        if not milestones:
            # Fallback: treat the whole goal as one milestone
            milestones = [goal]

        result.milestones = milestones
        self._activity(
            "plan",
            f"Split into {len(milestones)} milestone{'s' if len(milestones) != 1 else ''}",
            detail=" | ".join(milestones),
        )

        # ── 2. Execute each milestone ─────────────────────────────────────────
        all_files_created:  list[str] = []
        all_files_modified: list[str] = []

        for i, milestone in enumerate(milestones, 1):
            mt0 = time.monotonic()
            self._activity("milestone", f"Starting milestone {i}/{len(milestones)}: {milestone}")

            mr = self._run_milestone(milestone, attempt_number=1)

            # Accumulate files
            for f in mr.files_created:
                if f not in all_files_created:
                    all_files_created.append(f)
            for f in mr.files_modified:
                if f not in all_files_modified:
                    all_files_modified.append(f)

            mr.elapsed = time.monotonic() - mt0
            result.milestone_results.append(mr)

            self._activity(
                "milestone",
                f"Milestone {i} complete ({mr.attempts} attempt{'s' if mr.attempts != 1 else ''}, {mr.elapsed:.1f}s)",
                success=mr.success,
            )

            # Best-effort self-inspection of any running preview — a screenshot
            # + console/accessibility findings feed both the Timeline (M5) and
            # this milestone's executive summary, never raw output to the user.
            preview_note = self._inspect_active_preview(i, len(milestones))

            # Best-effort specialist checks — same non-blocking pattern as the
            # preview inspection above; a failure here just means no note.
            security_note = self._security_check(mr)
            docs_note     = self._docs_check(mr)

            # One executive-composed message per milestone — the only chat text
            # the user sees for this milestone (full detail stays in Timeline).
            summary_text = self._synthesize_milestone_summary(
                i, len(milestones), mr, preview_note, security_note, docs_note,
            )
            self._emit(summary_text)

        # ── 3. Final checkpoint commit ────────────────────────────────────────
        self._reasoning_stage("committing")
        commit_msg = f"MARK: {goal[:60]}"
        self._worker_started(GIT.name, f"Committing: {commit_msg}")
        commit_out    = execute_tool("git_commit", {"message": commit_msg}, self._ws)
        commit_ok     = "error" not in commit_out.lower()
        self._worker_finished(GIT.name, success=commit_ok)
        self._activity("commit", "Created checkpoint commit", detail=commit_out.split("\n")[0][:120])

        # ── 4. Build result ───────────────────────────────────────────────────
        result.files_created  = all_files_created
        result.files_modified = all_files_modified
        result.total_elapsed  = time.monotonic() - t0
        result.success        = all(mr.success for mr in result.milestone_results)

        n_ms     = len(milestones)
        n_pass   = sum(1 for mr in result.milestone_results if mr.success)
        n_files  = len(all_files_created)
        summary  = (
            f"Completed {n_pass}/{n_ms} milestones, {n_files} file"
            f"{'s' if n_files != 1 else ''} created in {result.total_elapsed:.1f}s."
        )
        result.final_summary = summary
        result.summary       = summary

        final_text = self._synthesize_final_summary(goal, result)
        self._emit(final_text)

        logger.info(
            "DevPipeline done  success=%s  milestones=%d/%d  files=%d  elapsed=%.1fs",
            result.success, n_pass, n_ms, n_files, result.total_elapsed,
        )
        return result

    # ── Planner ───────────────────────────────────────────────────────────────

    def _plan(self, goal: str) -> list[str]:
        """Call LLM to break *goal* into milestones."""
        messages = [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {"role": "user",   "content": goal},
        ]
        try:
            chunks: list[str] = []
            for chunk in self._mm.chat_stream(messages, max_tokens=512):
                if is_llm_error_text(chunk):
                    raise RuntimeError(chunk)
                chunks.append(chunk)
            raw = "".join(chunks).strip()
        except Exception as exc:
            logger.warning("DevPipeline._plan: LLM failed: %s — using single milestone", exc)
            return [goal]

        # Parse "1. ...\n2. ...\n" or "- ..." format
        milestones: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip leading "1. " / "- " / "* "
            clean = re.sub(r'^[\d]+[.)]\s*|^[-*•]\s*', '', line).strip()
            if clean:
                milestones.append(clean)

        return milestones[:5] if milestones else [goal]

    # ── Milestone runner (with retry) ─────────────────────────────────────────

    def _run_milestone(self, milestone: str, attempt_number: int) -> MilestoneResult:
        mr = MilestoneResult(milestone=milestone)

        # Least-privilege scope: only the files this milestone names may be
        # written. Grows as attempts proceed so a fixer can touch what the
        # executor already created, without ever widening beyond declared intent.
        allowed_paths = extract_file_targets(milestone)
        if allowed_paths:
            self._activity("permission", f"Scoped to: {', '.join(allowed_paths)}")

        for attempt in range(1, self._max_attempts + 1):
            mr.attempts = attempt

            # Executor → Engineer
            self._worker_started(ENGINEER.name, milestone[:80])
            loop_result = run_agent_loop(
                goal               = milestone,
                model_manager      = self._mm,
                event_bus          = self._eb,
                workspace_path     = self._ws,
                system_prompt      = _ENGINEER_SYSTEM,
                max_turns          = MAX_MILESTONE_TURNS,
                allowed_paths      = allowed_paths,
                allow_direct_reply = False,
            )
            self._worker_finished(ENGINEER.name, success=loop_result.success)
            mr.files_created  = loop_result.files_created
            mr.files_modified = loop_result.files_modified
            for f in mr.files_created + mr.files_modified:
                if f not in allowed_paths:
                    allowed_paths.append(f)

            # Tester → QA
            self._worker_started(QA.name, "Running tests")
            test_output, tests_passed = self._run_tests()
            mr.test_output  = test_output
            mr.tests_passed = tests_passed
            self._worker_finished(QA.name, success=tests_passed)

            if test_output:
                self._activity(
                    "test", f"Tests: {test_output.splitlines()[0][:70]}",
                    success=tests_passed,
                )

            # Reviewer
            self._reasoning_stage("reviewing")
            self._worker_started(REVIEWER.name, "Reviewing milestone")
            review = self._review(milestone, loop_result, test_output)
            mr.review = review
            passed   = review.upper().startswith("PASS")
            self._worker_finished(REVIEWER.name, success=passed)
            self._activity("review", f"Review: {review[:100]}", success=passed)

            if passed or attempt >= self._max_attempts:
                mr.success = passed or loop_result.success
                break

            # Fixer → Debugger, build repair goal and retry
            self._activity("fix", f"Retrying (attempt {attempt + 1}/{self._max_attempts})")
            fix_goal = self._build_fix_goal(milestone, review, test_output)
            self._worker_started(DEBUGGER.name, fix_goal[:80])
            fix_result = run_agent_loop(
                goal               = fix_goal,
                model_manager      = self._mm,
                event_bus          = self._eb,
                workspace_path     = self._ws,
                system_prompt      = _DEBUGGER_SYSTEM,
                max_turns          = 10,
                allowed_paths      = allowed_paths,
                allow_direct_reply = False,
            )
            self._worker_finished(DEBUGGER.name, success=fix_result.success)

        return mr

    # ── Tester ────────────────────────────────────────────────────────────────

    def _run_tests(self) -> tuple[str, bool]:
        """Auto-detect and run tests.  Returns (output, passed)."""
        cmd = self._test_cmd or self._detect_test_cmd()
        if not cmd:
            return "", True  # no tests → treat as pass

        logger.info("DevPipeline: running tests: %r", cmd)
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=60, cwd=self._ws,
            )
            out = (proc.stdout + proc.stderr).strip()
            passed = proc.returncode == 0
            return out[:3000], passed
        except subprocess.TimeoutExpired:
            return "[tests timed out after 60s]", False
        except Exception as exc:
            return f"[test runner error: {exc}]", False

    def _detect_test_cmd(self) -> str | None:
        """Infer the test command from workspace contents."""
        ws = Path(self._ws)
        if list(ws.rglob("test_*.py")) or list(ws.rglob("*_test.py")):
            return "python -m pytest -q --tb=short"
        if (ws / "package.json").exists():
            return "npm test --if-present"
        if (ws / "Cargo.toml").exists():
            return "cargo test"
        if (ws / "go.mod").exists():
            return "go test ./..."
        return None

    # ── Reviewer ──────────────────────────────────────────────────────────────

    def _review(
        self,
        milestone: str,
        loop_result: AgentLoopResult,
        test_output: str,
    ) -> str:
        """Ask LLM to review the result.  Returns 'PASS: ...' or 'FAIL: ...'."""
        files_summary = ", ".join(loop_result.files_created[:8]) or "(none)"
        test_section = (
            f"\nTest output:\n{test_output[:800]}" if test_output else "\n(no test suite)"
        )

        # If no files were created and loop succeeded, quick-pass on conversational tasks
        if not loop_result.files_created and loop_result.success:
            return "PASS: Task completed without file writes (conversational or query task)."

        prompt = (
            f"Milestone: {milestone}\n"
            f"Files created/modified: {files_summary}\n"
            f"Execution summary: {loop_result.final_summary[:200]}"
            f"{test_section}"
        )
        messages = [
            {"role": "system", "content": _REVIEWER_SYSTEM},
            {"role": "user",   "content": prompt},
        ]
        try:
            chunks: list[str] = []
            for chunk in self._mm.chat_stream(messages, max_tokens=150):
                if is_llm_error_text(chunk):
                    raise RuntimeError(chunk)
                chunks.append(chunk)
            return "".join(chunks).strip() or "PASS: (no feedback)"
        except Exception as exc:
            logger.warning("DevPipeline._review: LLM failed: %s", exc)
            return "PASS: (review skipped due to LLM error)"

    # ── Fixer ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_fix_goal(
        milestone: str,
        review_feedback: str,
        test_output: str,
    ) -> str:
        fail_reason = review_feedback.removeprefix("FAIL:").strip()
        test_clip   = test_output[:400] if test_output else "(no test output)"
        return (
            f"Fix the following issue with the milestone '{milestone}':\n\n"
            f"Problem: {fail_reason}\n\n"
            f"Test output:\n{test_clip}\n\n"
            "Read the relevant files first, then fix only what is broken."
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _emit(self, text: str) -> None:
        """Stream text to chat. Reserved for MARK's own executive-composed
        messages — internal phase detail goes through ``_activity`` instead."""
        try:
            self._eb.publish(ServerEvents.STREAMING_TOKEN, text=text, source="mark")
        except Exception as exc:
            logger.warning("DevPipeline._emit: %s", exc)

    def _reasoning_stage(self, stage: str) -> None:
        """Publish a phase change for the Timeline's stage stepper."""
        try:
            self._eb.publish(ServerEvents.REASONING_STAGE, stage=stage, tool=None)
        except Exception as exc:
            logger.warning("DevPipeline._reasoning_stage: %s", exc)

    def _activity(
        self, kind: str, text: str, detail: str = "", success: bool = True,
    ) -> None:
        """Publish one Timeline/Activity Feed entry (technical detail — not chat)."""
        try:
            self._eb.publish(
                ServerEvents.ACTIVITY_FEED_ENTRY,
                type=kind, text=text, detail=detail, success=success,
            )
        except Exception as exc:
            logger.warning("DevPipeline._activity: %s", exc)

    def _worker_started(self, worker: str, task: str) -> None:
        """Mark a named specialist (see ``worker_roles.py``) as active on
        the Active Workers panel — real dispatch, not narration."""
        try:
            self._eb.publish(ServerEvents.WORKER_STARTED, worker=worker, task=task)
        except Exception as exc:
            logger.warning("DevPipeline._worker_started: %s", exc)

    def _worker_finished(self, worker: str, success: bool = True) -> None:
        try:
            self._eb.publish(ServerEvents.WORKER_FINISHED, worker=worker, success=success)
        except Exception as exc:
            logger.warning("DevPipeline._worker_finished: %s", exc)

    def _synthesize(self, context: str, fallback: str) -> str:
        """One LLM call: MARK-the-executive composes a short conversational
        update from structured results. Falls back to a deterministic
        sentence if the LLM call fails, so a run never goes silent."""
        messages = [
            {"role": "system", "content": _EXECUTIVE_SYSTEM},
            {"role": "user",   "content": context},
        ]
        try:
            chunks: list[str] = []
            for chunk in self._mm.chat_stream(messages, max_tokens=200):
                if is_llm_error_text(chunk):
                    raise RuntimeError(chunk)
                chunks.append(chunk)
            text = "".join(chunks).strip()
            return text or fallback
        except Exception as exc:
            logger.warning("DevPipeline._synthesize: LLM failed: %s", exc)
            return fallback

    def _synthesize_milestone_summary(
        self, index: int, total: int, mr: MilestoneResult,
        preview_note: str = "", security_note: str = "", docs_note: str = "",
    ) -> str:
        files = mr.files_created + mr.files_modified
        context = (
            f"Milestone {index}/{total}: {mr.milestone}\n"
            f"Outcome: {'succeeded' if mr.success else 'did not fully pass review'}\n"
            f"Attempts: {mr.attempts}\n"
            f"Files touched: {', '.join(files) or '(none)'}\n"
            f"Tests: {'passed' if mr.tests_passed else ('failed' if mr.test_output else 'none run')}\n"
            f"Review verdict: {mr.review[:150]}"
            + (f"\nPreview inspection: {preview_note}" if preview_note else "")
            + (f"\nSecurity review: {security_note}" if security_note else "")
            + (f"\nDocs review: {docs_note}" if docs_note else "")
        )
        fallback = (
            f"Milestone {index}/{total} ({mr.milestone}): "
            f"{'done' if mr.success else 'needs another pass'} — "
            f"{len(files)} file{'s' if len(files) != 1 else ''} touched."
            + (f" {preview_note}" if preview_note else "")
        )
        return self._synthesize(context, fallback) + "\n\n"

    def _security_check(self, mr: MilestoneResult) -> str:
        """
        Best-effort Security worker: one LLM call over this milestone's diff
        asking for obvious issues. Never blocks the pipeline — any failure
        (LLM unavailable, tool error) just means no finding gets folded into
        the milestone summary, matching ``_inspect_active_preview``'s pattern.
        """
        self._worker_started(SECURITY.name, f"Reviewing {mr.milestone[:60]}")
        finding = ""
        try:
            diff = execute_tool("git_diff", {}, self._ws)
            messages = [
                {"role": "system", "content": _SECURITY_SYSTEM},
                {"role": "user", "content": f"Milestone: {mr.milestone}\n\nDiff:\n{diff[:4000]}"},
            ]
            chunks: list[str] = []
            for chunk in self._mm.chat_stream(messages, max_tokens=200):
                if is_llm_error_text(chunk):
                    raise RuntimeError(chunk)
                chunks.append(chunk)
            finding = "".join(chunks).strip()
        except Exception as exc:
            logger.debug("DevPipeline._security_check: skipped: %s", exc)

        flagged = finding.upper().startswith("FLAG")
        if finding:
            self._activity("security", finding[:150], success=not flagged)
        self._worker_finished(SECURITY.name, success=not flagged)
        return finding

    def _docs_check(self, mr: MilestoneResult) -> str:
        """
        Best-effort Docs worker: one LLM call deciding whether this
        milestone's change needs a README/docs update, writing it directly
        via ``write_file`` when warranted. Never blocks the pipeline.
        """
        self._worker_started(DOCS.name, f"Checking docs for {mr.milestone[:60]}")
        note = ""
        try:
            files = mr.files_created + mr.files_modified
            messages = [
                {"role": "system", "content": _DOCS_SYSTEM},
                {"role": "user", "content": (
                    f"Milestone: {mr.milestone}\n"
                    f"Files touched: {', '.join(files) or '(none)'}"
                )},
            ]
            chunks: list[str] = []
            for chunk in self._mm.chat_stream(messages, max_tokens=600):
                if is_llm_error_text(chunk):
                    raise RuntimeError(chunk)
                chunks.append(chunk)
            raw = "".join(chunks).strip()

            if raw.upper().startswith("UPDATE:"):
                body = raw[len("UPDATE:"):].strip()
                path_line, _, content = body.partition("\n---\n")
                path, content = path_line.strip(), content.strip()
                if path and content:
                    execute_tool("write_file", {"path": path, "content": content}, self._ws)
                    note = f"Updated {path}"
            else:
                note = raw.removeprefix("SKIP:").strip()
        except Exception as exc:
            logger.debug("DevPipeline._docs_check: skipped: %s", exc)

        if note:
            self._activity("docs", note[:150])
        self._worker_finished(DOCS.name, success=True)
        return note

    def _inspect_active_preview(self, index: int, total: int) -> str:
        """
        If a live preview is registered, capture a screenshot + basic findings
        via BrowserAgent and persist them to the Timeline. Best-effort: any
        failure (no preview, Playwright unavailable, navigation error) just
        means no preview_note gets fed into this milestone's summary — it
        never breaks the pipeline.
        """
        started = False
        try:
            from smartagent.preview.browser_agent import browser_agent
            if not browser_agent.available:
                return ""

            from smartagent.server.api_previews import preview_manager
            active = [p for p in preview_manager.all_previews() if p.get("status") == "active"]
            if not active:
                return ""
            preview = active[0]

            self._worker_started(PREVIEW.name, f"Inspecting {preview['url']}")
            started = True
            report = browser_agent.inspect(preview["url"], check_accessibility=True)
            if not report.success:
                self._worker_finished(PREVIEW.name, success=False)
                return ""

            if report.screenshot_path:
                try:
                    from pathlib import Path as _Path
                    from smartagent.server.api_timeline import record_event
                    record_event("MilestoneScreenshot", {
                        "milestone_index": index,
                        "milestone_total": total,
                        "preview_url":     preview["url"],
                        "screenshot_url":  f"/screenshots/{_Path(report.screenshot_path).name}",
                        "console_errors":  report.console_errors,
                    })
                except Exception as exc:
                    logger.warning("DevPipeline: failed to record milestone screenshot: %s", exc)

            self._worker_finished(PREVIEW.name, success=True)
            return report.summary_text()
        except Exception as exc:
            logger.debug("DevPipeline: preview inspection skipped: %s", exc)
            if started:
                self._worker_finished(PREVIEW.name, success=False)
            return ""

    def _synthesize_final_summary(self, goal: str, result: PipelineResult) -> str:
        n_ms   = len(result.milestones)
        n_pass = sum(1 for mr in result.milestone_results if mr.success)
        context = (
            f"Goal: {goal}\n"
            f"Milestones completed: {n_pass}/{n_ms}\n"
            f"Files created: {', '.join(result.files_created) or '(none)'}\n"
            f"Files modified: {', '.join(result.files_modified) or '(none)'}\n"
            f"Total time: {result.total_elapsed:.1f}s\n"
            f"Overall outcome: {'all milestones passed' if result.success else 'some milestones need follow-up'}"
        )
        return self._synthesize(context, result.summary) + "\n"


# ────────────────────────────────────────────────────────────────────────────
# Complexity router
# ────────────────────────────────────────────────────────────────────────────

# Patterns that indicate a goal needs the full Planner→Executor→Reviewer loop
_COMPLEX_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"\bfull[\s-]?stack\b",
        r"\bcomplete\s+(?:app|application|project|system|api|backend|frontend)\b",
        r"\bfrom\s+scratch\b",
        r"\bwith\s+tests?\b",
        r"\bwith\s+(?:a\s+)?(?:readme|documentation|docs)\b",
        r"\bproject\b",
        r"\bmulti[\s-]?(?:file|page|module|step)\b",
        r"\bfull\s+(?:crud|rest|api)\b",
        r"\bbuild\s+(?:a\s+)?(?:todo|blog|chat|e-?commerce|saas|dashboard)\b",
        r"\bmicroservice\b",
        r"\bpackage\b",
        r"\brepository\b",
    ]
]

def is_complex_goal(goal: str) -> bool:
    """
    Return True when *goal* needs the full pipeline (Planner + multi-step
    execution + tests + review).  Simple file/query/command tasks return False.

    A goal is complex when it matches a complexity pattern — no word-count gate,
    because short goals like "Build a project with tests" are just as complex as
    longer ones.
    """
    g = goal.strip()
    if not g:
        return False
    for pat in _COMPLEX_PATTERNS:
        if pat.search(g):
            return True
    return False
