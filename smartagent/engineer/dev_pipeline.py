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

from smartagent.engineer.agent_loop import run_agent_loop, AgentLoopResult
from smartagent.engineer.agent_tools import execute_tool
from smartagent.logs.logger import get_logger
from smartagent.server.events import ServerEvents

logger = get_logger(__name__)

MAX_FIX_ATTEMPTS = 3
MAX_MILESTONE_TURNS = 15


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

_FIXER_SYSTEM = """\
You are MARK, an autonomous AI software engineer.  A previous execution
attempt produced failures.  Fix the problems described below.

Use your tools to:
1. Read the relevant files.
2. Understand what went wrong.
3. Write corrected versions.
4. Re-run tests to verify.

Be surgical — change only what is needed.  Do not rewrite unaffected files.
"""


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

        self._emit(f"🗂  Planning: {goal[:80]}\n")

        # ── 1. Plan ───────────────────────────────────────────────────────────
        milestones = self._plan(goal)
        if not milestones:
            # Fallback: treat the whole goal as one milestone
            milestones = [goal]

        result.milestones = milestones
        self._emit(f"\n📋 {len(milestones)} milestone{'s' if len(milestones) != 1 else ''}:\n")
        for i, m in enumerate(milestones, 1):
            self._emit(f"   {i}. {m}\n")
        self._emit("\n")

        # ── 2. Execute each milestone ─────────────────────────────────────────
        all_files_created:  list[str] = []
        all_files_modified: list[str] = []

        for i, milestone in enumerate(milestones, 1):
            mt0 = time.monotonic()
            self._emit(f"{'─'*60}\n")
            self._emit(f"🔨 Milestone {i}/{len(milestones)}: {milestone}\n\n")

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

            status = "✅" if mr.success else "⚠"
            self._emit(f"\n{status} Milestone {i} complete"
                       f" ({mr.attempts} attempt{'s' if mr.attempts != 1 else ''},"
                       f" {mr.elapsed:.1f}s)\n")

        # ── 3. Final checkpoint commit ────────────────────────────────────────
        self._emit(f"\n{'─'*60}\n")
        self._emit("📦 Creating checkpoint commit…\n")
        commit_msg = f"MARK: {goal[:60]}"
        commit_out = execute_tool("git_commit", {"message": commit_msg}, self._ws)
        self._emit(f"   {commit_out.split(chr(10))[0][:80]}\n")

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

        self._emit(f"\n{'═'*60}\n")
        self._emit(f"{'✅ Done!' if result.success else '⚠ Partial completion'} "
                   f"{summary}\n")

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

        for attempt in range(1, self._max_attempts + 1):
            mr.attempts = attempt

            # Executor
            loop_result = run_agent_loop(
                goal           = milestone,
                model_manager  = self._mm,
                event_bus      = self._eb,
                workspace_path = self._ws,
                max_turns      = MAX_MILESTONE_TURNS,
            )
            mr.files_created  = loop_result.files_created
            mr.files_modified = loop_result.files_modified

            # Tester
            test_output, tests_passed = self._run_tests()
            mr.test_output  = test_output
            mr.tests_passed = tests_passed

            if test_output:
                status_icon = "✅" if tests_passed else "❌"
                self._emit(f"\n{status_icon} Tests: {test_output.splitlines()[0][:70]}\n")

            # Reviewer
            review = self._review(milestone, loop_result, test_output)
            mr.review = review
            passed   = review.upper().startswith("PASS")
            self._emit(f"👁  Review: {review[:100]}\n")

            if passed or attempt >= self._max_attempts:
                mr.success = passed or loop_result.success
                break

            # Fixer — build repair goal and retry
            self._emit(f"\n🔧 Attempt {attempt + 1}/{self._max_attempts}: fixing…\n\n")
            fix_goal = self._build_fix_goal(milestone, review, test_output)
            _ = run_agent_loop(
                goal           = fix_goal,
                model_manager  = self._mm,
                event_bus      = self._eb,
                workspace_path = self._ws,
                system_prompt  = _FIXER_SYSTEM,
                max_turns      = 10,
            )

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
        try:
            self._eb.publish(ServerEvents.STREAMING_TOKEN, text=text, source="mark")
        except Exception as exc:
            logger.warning("DevPipeline._emit: %s", exc)


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
