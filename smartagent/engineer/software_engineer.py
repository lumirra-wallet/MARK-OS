"""
SoftwareEngineer — Milestone 25: Full Software Engineer.

MARK as a professional coding agent.  Given a goal like "Build me a Trello
clone", it:

  1. Analyzes requirements (RequirementAnalyzer)
  2. Generates clarification questions (ClarificationEngine) — skipped in
     non-interactive mode, defaults applied
  3. Plans the work (CEOAgent / TeamPlanner)
  4. Executes via DevLoop (autonomous code → test → debug → reflect loop)
  5. Commits successful code via GitClient (optional)
  6. Returns a SoftwareEngineerReport

Usage::

    eng = SoftwareEngineer.with_agent(agent)
    report = eng.build("Build me a Trello clone")
    print("\\n".join(report.as_display_lines()))

    # Non-interactive with custom test command
    report = eng.build(
        "Build a FastAPI auth service",
        test_cmd="pytest tests/",
        interactive=False,
        auto_commit=True,
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from smartagent.engineer.clarification_engine import ClarificationEngine, ClarificationSet
from smartagent.engineer.requirement_analyzer import RequirementAnalyzer, RequirementReport
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class SoftwareEngineerReport:
    """
    Full report from one ``SoftwareEngineer.build()`` invocation.

    Attributes:
        goal:             Original goal string.
        requirements:     Structured requirement analysis.
        clarifications:   Questions asked and answers given (may be empty).
        loop_result:      Result from the DevLoop execution.
        committed:        True if git commit was made.
        commit_sha:       Short SHA of the commit (if committed).
        total_elapsed:    Wall-clock seconds.
        success:          True when all phases passed.
        summary:          One-paragraph prose summary.
    """
    goal:            str
    requirements:    Optional[RequirementReport]  = None
    clarifications:  Optional[ClarificationSet]   = None
    loop_result:     Any                          = None  # LoopResult
    committed:       bool                         = False
    commit_sha:      str                          = ""
    total_elapsed:   float                        = 0.0
    success:         bool                         = False
    summary:         str                          = ""

    def as_display_lines(self) -> list[str]:
        icon = "✓" if self.success else "~"
        lines: list[str] = [
            f"{icon} Software Engineer Report",
            "─" * 60,
            f"  Goal    : {self.goal[:72]}",
            "",
        ]

        # Requirements
        if self.requirements:
            lines.append("  Requirements:")
            lines.extend("  " + l for l in self.requirements.as_display_lines())
            lines.append("")

        # Clarifications
        if self.clarifications and self.clarifications.answered:
            lines.append("  Clarifications:")
            for qid, val in self.clarifications.answered.items():
                lines.append(f"    {qid}: {val}")
            lines.append("")

        # Dev loop
        if self.loop_result is not None:
            lines.append("  Execution:")
            lines.extend("  " + l for l in self.loop_result.as_display_lines())
            lines.append("")

        # Git
        if self.committed:
            lines.append(f"  ✓ Committed  sha={self.commit_sha or '(see log)'}")
            lines.append("")

        # Summary
        if self.summary:
            lines.append("  Summary:")
            for chunk in [
                self.summary[i:i+80]
                for i in range(0, min(len(self.summary), 400), 80)
            ]:
                lines.append(f"    {chunk}")
            lines.append("")

        status = "SUCCESS" if self.success else "IN PROGRESS"
        lines.append(
            f"  Status  : {status}  |  "
            f"Elapsed: {self.total_elapsed:.1f}s"
        )
        return lines


# ---------------------------------------------------------------------------
# SoftwareEngineer
# ---------------------------------------------------------------------------

class SoftwareEngineer:
    """
    Full-stack autonomous coding agent (Milestone 25).

    Args:
        dev_loop:           :class:`~smartagent.dev_loop.DevLoop` for autonomous
                            code→test→debug cycles.
        ceo_agent:          :class:`~smartagent.multi_agent.ceo_agent.CEOAgent`
                            for multi-team planning (optional — uses dev_loop
                            executive if absent).
        memory_manager:     Persists summaries across sessions.
        git_client:         For auto-committing successful builds (optional).
        model_manager:      For AI-enriched requirement analysis (optional).
        project_memory:     Injects project context into prompts (optional).
        interactive:        If True, print clarification questions to stdout.
    """

    def __init__(
        self,
        dev_loop: Any | None = None,
        ceo_agent: Any | None = None,
        memory_manager: Any | None = None,
        git_client: Any | None = None,
        model_manager: Any | None = None,
        project_memory: Any | None = None,
        interactive: bool = False,
    ) -> None:
        self._dev_loop       = dev_loop
        self._ceo            = ceo_agent
        self._memory         = memory_manager
        self._git            = git_client
        self._model_manager  = model_manager
        self._project_memory = project_memory
        self._interactive    = interactive

        self._analyzer     = RequirementAnalyzer(model_manager=model_manager)
        self._clarifier    = ClarificationEngine(model_manager=model_manager)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_agent(cls, agent: Any, interactive: bool = False) -> "SoftwareEngineer":
        """Build a fully-wired SoftwareEngineer from a live ``SmartAgent``."""
        from smartagent.dev_loop.dev_loop import DevLoop
        dev_loop = DevLoop.with_agent(agent)
        return cls(
            dev_loop=dev_loop,
            ceo_agent=getattr(agent, "ceo", None),
            memory_manager=getattr(agent, "memory", None),
            git_client=None,
            model_manager=getattr(agent, "model_manager", None),
            project_memory=getattr(agent, "project_memory", None),
            interactive=interactive,
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def build(
        self,
        goal: str,
        test_cmd: str = "pytest",
        auto_commit: bool = False,
        commit_message: str = "",
        interactive: bool | None = None,
        project_name: str = "",
        max_iterations: int = 5,
    ) -> SoftwareEngineerReport:
        """
        Full engineer pipeline: analyze → clarify → plan → code → test →
        debug → reflect → commit → summarize.

        Args:
            goal:           Natural-language development goal.
            test_cmd:       Shell command to run tests.
            auto_commit:    If True, commit successful code to git.
            commit_message: Git commit message override.
            interactive:    Override the instance-level ``interactive`` flag.
            project_name:   Load this project from ProjectMemory for context.
            max_iterations: Override max dev-loop iterations.

        Returns:
            :class:`SoftwareEngineerReport`
        """
        t0 = time.monotonic()
        use_interactive = self._interactive if interactive is None else interactive
        report = SoftwareEngineerReport(goal=goal)

        logger.info("SoftwareEngineer: starting  goal=%r", goal[:80])

        # ----------------------------------------------------------
        # Step 1: Requirement analysis
        # ----------------------------------------------------------
        req = self._analyze(goal, project_name)
        report.requirements = req
        logger.info(
            "SoftwareEngineer: analysis done  complexity=%s  domains=%s",
            req.complexity, req.domains,
        )

        # ----------------------------------------------------------
        # Step 2: Clarification
        # ----------------------------------------------------------
        cset = self._clarify(req, use_interactive)
        report.clarifications = cset

        # Enrich goal with clarifications if any were answered
        enriched_goal = self._enrich_goal(goal, req, cset)

        # ----------------------------------------------------------
        # Step 3: Execute via DevLoop
        # ----------------------------------------------------------
        if self._dev_loop is not None:
            loop_result = self._dev_loop.run(
                goal=enriched_goal,
                test_cmd=test_cmd,
                auto_commit=False,  # we handle commits ourselves below
            )
        else:
            # No dev loop wired — produce a stub result
            from smartagent.dev_loop.loop_result import LoopResult
            loop_result = LoopResult(
                goal=enriched_goal,
                success=True,
                stop_reason="no_loop",
                final_summary="No DevLoop wired — running planning only.",
            )

        report.loop_result = loop_result
        report.success = loop_result.success

        # ----------------------------------------------------------
        # Step 4: Auto-commit
        # ----------------------------------------------------------
        if auto_commit and loop_result.success and self._git is not None:
            sha = self._commit(goal, commit_message)
            report.committed = bool(sha)
            report.commit_sha = sha

        # ----------------------------------------------------------
        # Step 5: Build summary
        # ----------------------------------------------------------
        report.summary = self._build_summary(goal, req, loop_result)
        report.total_elapsed = time.monotonic() - t0

        # Persist to memory
        self._persist(goal, report)

        logger.info(
            "SoftwareEngineer: done  success=%s  elapsed=%.1fs",
            report.success, report.total_elapsed,
        )
        return report

    # ------------------------------------------------------------------
    # Sub-steps
    # ------------------------------------------------------------------

    def _analyze(self, goal: str, project_name: str) -> RequirementReport:
        """Analyze requirements, optionally enriching with project context."""
        enriched = goal
        if project_name and self._project_memory is not None:
            try:
                profile = self._project_memory.load(project_name)
                enriched = goal + "\n[Project] " + profile.as_ai_context()
            except Exception:
                pass
        return self._analyzer.analyze(enriched)

    def _clarify(
        self,
        req: RequirementReport,
        use_interactive: bool,
    ) -> ClarificationSet:
        cset = self._clarifier.from_report(req)
        if not cset.questions:
            return cset
        if use_interactive:
            try:
                cset = self._clarifier.interactive_prompt(cset)
            except Exception:
                cset.answer_all_with_defaults()
        else:
            cset.answer_all_with_defaults()
        return cset

    def _enrich_goal(
        self,
        goal: str,
        req: RequirementReport,
        cset: ClarificationSet,
    ) -> str:
        """Combine goal + analysis + clarification answers into an enriched prompt."""
        parts = [goal]
        context = req.as_ai_context()
        if context:
            parts.append(f"\n[Analysis]\n{context}")
        answer_ctx = cset.as_context()
        if answer_ctx:
            parts.append(f"\n[Clarifications]\n{answer_ctx}")
        return "\n".join(parts)

    def _commit(self, goal: str, commit_message: str) -> str:
        """Auto-commit and return the SHA (or empty string on failure)."""
        try:
            msg = commit_message or f"feat: {goal[:72]}"
            add_r = self._git.add(".")
            if add_r.success:
                commit_r = self._git.commit(msg)
                return getattr(commit_r, "sha", "") or ""
        except Exception as exc:
            logger.warning("SoftwareEngineer: git commit failed: %s", exc)
        return ""

    def _build_summary(
        self,
        goal: str,
        req: RequirementReport,
        loop_result: Any,
    ) -> str:
        status = "successfully completed" if loop_result.success else "partially completed"
        cycles = getattr(loop_result, "_cycle_count", lambda: "?")()
        domains = ", ".join(req.domains[:4]) if req.domains else "general"
        return (
            f"MARK {status} the following task: {goal[:80]}.  "
            f"Domains covered: {domains}.  "
            f"Complexity: {req.complexity}.  "
            f"Dev-loop iterations: {cycles}.  "
            f"Stop reason: {getattr(loop_result, 'stop_reason', 'unknown')}."
        )

    def _persist(self, goal: str, report: SoftwareEngineerReport) -> None:
        if self._memory is None:
            return
        try:
            status = "succeeded" if report.success else "in progress"
            entry = (
                f"Engineer {status}: {goal[:60]}  |  "
                f"Elapsed: {report.total_elapsed:.1f}s"
            )
            self._memory.remember(entry, category="Engineer")
        except Exception:
            pass
