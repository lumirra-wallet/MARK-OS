"""
SoftwareEngineer — Milestone 25 + v2.0 upgrade.

MARK as a professional coding agent.  Given a goal like "Build me a Trello
clone", it:

  1. Analyzes requirements (RequirementAnalyzer)
  2. Generates clarification questions (ClarificationEngine) — skipped in
     non-interactive mode, defaults applied
  3. Scans the workspace (WorkspaceScanner) to understand the codebase
  4. Plans the work (CEOAgent / TeamPlanner)
  5. Executes via DevLoop (autonomous code → test → quality → debug → reflect)
  6. Commits successful code via GitClient (optional)
  7. Returns a SoftwareEngineerReport

v2.0 adds:
  - Workspace scan step (step 3) using the existing scanner.
  - ExecutionDashboard injected into DevLoop for live progress.
  - Graceful fallbacks for every optional subsystem.
  - Richer SoftwareEngineerReport with quality data.

Usage::

    eng = SoftwareEngineer.with_agent(agent)
    report = eng.build("Build a FastAPI auth service")
    print("\\n".join(report.as_display_lines()))
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from smartagent.engineer.clarification_engine import ClarificationEngine, ClarificationSet
from smartagent.engineer.requirement_analyzer import RequirementAnalyzer, RequirementReport
from smartagent.logs.logger import get_logger
from smartagent.performance.complexity import TaskComplexity, classify_complexity

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
        workspace_summary: Brief description of the scanned workspace.
        loop_result:      Result from the DevLoop execution.
        quality_summary:  One-line quality gate result (if run).
        committed:        True if git commit was made.
        commit_sha:       Short SHA of the commit (if committed).
        total_elapsed:    Wall-clock seconds.
        success:          True when all phases passed.
        summary:          One-paragraph prose summary.
        files_created:    Paths of files created in the project directory.
        files_modified:   Paths of files modified in the project directory.
        project_dir:      Absolute path where generated files were written.
    """

    goal:              str                          = ""
    requirements:      Optional[RequirementReport]  = None
    clarifications:    Optional[ClarificationSet]   = None
    workspace_summary: str                          = ""
    loop_result:       Any                          = None  # LoopResult
    quality_summary:   str                          = ""
    committed:         bool                         = False
    commit_sha:        str                          = ""
    total_elapsed:     float                        = 0.0
    success:           bool                         = False
    summary:           str                          = ""
    files_created:     list                         = field(default_factory=list)
    files_modified:    list                         = field(default_factory=list)
    project_dir:       str                          = ""

    def as_display_lines(self) -> list[str]:
        icon  = "✓" if self.success else "~"
        lines: list[str] = [
            f"{icon} Software Engineer Report",
            "─" * 60,
            f"  Goal    : {self.goal[:72]}",
            "",
        ]

        # Workspace
        if self.workspace_summary:
            lines.append(f"  Workspace: {self.workspace_summary}")
            lines.append("")

        # Requirements
        if self.requirements:
            lines.append("  Requirements:")
            lines.extend("  " + ln for ln in self.requirements.as_display_lines())
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
            lines.extend("  " + ln for ln in self.loop_result.as_display_lines())
            lines.append("")

        # Quality
        if self.quality_summary:
            lines.append(f"  Quality  : {self.quality_summary}")
            lines.append("")

        # Git
        if self.committed:
            lines.append(f"  ✓ Committed  sha={self.commit_sha or '(see log)'}")
            lines.append("")

        # Files created / modified
        if self.files_created or self.files_modified:
            lines.append("  Files:")
            for f in self.files_created:
                lines.append(f"    + {f}")
            for f in self.files_modified:
                lines.append(f"    ~ {f}")
            if self.project_dir:
                lines.append(f"    (in {self.project_dir})")
            lines.append("")

        # Summary
        if self.summary:
            lines.append("  Summary:")
            for chunk in [
                self.summary[i : i + 80]
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
    Full-stack autonomous coding agent (Milestone 25 + v2.0).

    Args:
        dev_loop:           :class:`~smartagent.dev_loop.DevLoop` for autonomous
                            code→test→debug cycles.
        ceo_agent:          :class:`~smartagent.multi_agent.ceo_agent.CEOAgent`
                            for multi-team planning (optional).
        memory_manager:     Persists summaries across sessions.
        git_client:         For auto-committing successful builds (optional).
        model_manager:      For AI-enriched requirement analysis (optional).
        project_memory:     Injects project context into prompts (optional).
        workspace_scanner:  For scanning the project before coding (optional).
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
        workspace_scanner: Any | None = None,
        interactive: bool = False,
        event_bus: Any | None = None,
    ) -> None:
        self._dev_loop          = dev_loop
        self._ceo               = ceo_agent
        self._memory            = memory_manager
        self._git               = git_client
        self._model_manager     = model_manager
        self._project_memory    = project_memory
        self._workspace_scanner = workspace_scanner
        self._interactive       = interactive
        self._event_bus         = event_bus

        self._analyzer  = RequirementAnalyzer(model_manager=model_manager)
        self._clarifier = ClarificationEngine(model_manager=model_manager)

    def _emit(self, name: str, **payload: Any) -> None:
        """Publish an event on the wired EventBus, silently ignoring failures."""
        if self._event_bus is not None:
            try:
                self._event_bus.publish(name, **payload)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_agent(
        cls,
        agent: Any,
        interactive: bool = False,
        cwd: str = ".",
        event_bus: Any | None = None,
    ) -> "SoftwareEngineer":
        """Build a fully-wired SoftwareEngineer from a live ``SmartAgent``."""
        from smartagent.dev_loop.dev_loop import DevLoop

        # Build dashboard for live progress
        dashboard = None
        try:
            from smartagent.ui.dashboard import ExecutionDashboard
            dashboard = ExecutionDashboard()
        except Exception:
            pass

        dev_loop = DevLoop.with_agent(agent, cwd=cwd, event_bus=event_bus)
        # Inject dashboard into dev_loop
        if dashboard is not None:
            dev_loop._dashboard = dashboard  # type: ignore[attr-defined]

        # Workspace scanner (optional)
        workspace_scanner = None
        try:
            workspace_scanner = getattr(
                getattr(agent, "workspace_manager", None),
                "scanner",
                None,
            )
            if workspace_scanner is None:
                from smartagent.workspace.scanner import WorkspaceScanner
                workspace_scanner = WorkspaceScanner()
        except Exception:
            pass

        return cls(
            dev_loop=dev_loop,
            ceo_agent=getattr(agent, "ceo", None),
            memory_manager=getattr(agent, "memory", None),
            git_client=None,
            model_manager=getattr(agent, "model_manager", None),
            project_memory=getattr(agent, "project_memory", None),
            workspace_scanner=workspace_scanner,
            interactive=interactive,
            event_bus=event_bus,
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
        run_quality: bool = True,
        scan_path: str = ".",
        project_dir: str | None = None,
    ) -> SoftwareEngineerReport:
        """
        Full engineer pipeline: scan → analyze → clarify → plan → code → test
        → quality → debug → reflect → commit → summarize.

        Args:
            goal:           Natural-language development goal.
            test_cmd:       Shell command to run tests.
            auto_commit:    If True, commit successful code to git.
            commit_message: Git commit message override.
            interactive:    Override the instance-level ``interactive`` flag.
            project_name:   Load this project from ProjectMemory for context.
            max_iterations: Override max dev-loop iterations.
            run_quality:    Whether to run ruff/black/mypy after tests pass.
            scan_path:      Path to scan for workspace intelligence.
            project_dir:    Directory where generated files should be written and
                            where tests should run.  Defaults to the current
                            working directory.

        Returns:
            :class:`SoftwareEngineerReport`
        """
        t0 = time.monotonic()
        use_interactive = self._interactive if interactive is None else interactive
        resolved_project_dir = os.path.abspath(project_dir) if project_dir else os.getcwd()

        # ----------------------------------------------------------
        # Classify complexity and route to the right execution tier.
        # ----------------------------------------------------------
        complexity = classify_complexity(goal)

        print(f"  [tier] Complexity : {complexity.value}")

        # ── Tier 1: TRIVIAL / SMALL — fast path (one LLM call, no pipeline) ──
        if complexity in (TaskComplexity.TRIVIAL, TaskComplexity.SMALL):
            return self._fast_path_build(
                goal, test_cmd, resolved_project_dir, complexity, t0,
                auto_commit=auto_commit, commit_message=commit_message,
            )

        # ── Tier 2: MEDIUM — lean pipeline (no research/architecture/docs) ──
        # ── Tier 3: LARGE / ENTERPRISE — full pipeline as before ─────────────
        print(
            f"  [tier] Tier: {'medium (lean pipeline)' if complexity == TaskComplexity.MEDIUM else 'full pipeline'}"
        )

        report = SoftwareEngineerReport(goal=goal, project_dir=resolved_project_dir)

        logger.info("SoftwareEngineer: starting  goal=%r  tier=%s", goal[:80], complexity.value)

        # ----------------------------------------------------------
        # Step 0: Workspace scan — skip for medium (speed)
        # ----------------------------------------------------------
        if complexity not in (TaskComplexity.MEDIUM,):
            self._emit("WorkerStarted", worker="Research", task="workspace scan")
            report.workspace_summary = self._scan_workspace(scan_path)
            self._emit("WorkerFinished", worker="Research", success=True)
            logger.info("SoftwareEngineer: workspace=%r", report.workspace_summary[:80])

        # ----------------------------------------------------------
        # Step 1: Requirement analysis
        # ----------------------------------------------------------
        self._emit("WorkerStarted", worker="Planning", task="requirement analysis")
        print(f"  [req]  Analyzing requirements...")
        req = self._analyze(goal, project_name)
        report.requirements = req
        self._emit("WorkerFinished", worker="Planning", success=True)
        logger.info(
            "SoftwareEngineer: analysis done  complexity=%s  domains=%s",
            req.complexity, req.domains,
        )

        # ----------------------------------------------------------
        # Step 2: Clarification
        # ----------------------------------------------------------
        cset = self._clarify(req, use_interactive)
        report.clarifications = cset

        # Enrich goal with workspace + clarification context
        enriched_goal = self._enrich_goal(
            goal, req, cset, report.workspace_summary
        )

        # ----------------------------------------------------------
        # Step 3: Execute via DevLoop
        # ----------------------------------------------------------
        if self._dev_loop is not None:
            # Tier 2 (medium): cap iterations at 2 and route faster
            effective_max_iters = max_iterations
            if complexity == TaskComplexity.MEDIUM:
                effective_max_iters = min(max_iterations, 2)
                logger.info("SoftwareEngineer: medium tier — capping iterations at %d", effective_max_iters)

            self._dev_loop._max_iterations = max(1, effective_max_iters)

            loop_result = self._dev_loop.run(
                goal=enriched_goal,
                test_cmd=test_cmd,
                auto_commit=False,  # we handle commits ourselves
                run_quality=run_quality and complexity != TaskComplexity.MEDIUM,
                project_dir=resolved_project_dir,
                complexity=complexity.value,
            )
        else:
            from smartagent.dev_loop.loop_result import LoopResult
            loop_result = LoopResult(
                goal=enriched_goal,
                success=True,
                stop_reason="no_loop",
                final_summary="No DevLoop wired — running planning only.",
            )

        report.loop_result    = loop_result
        report.success        = loop_result.success
        report.files_created  = getattr(loop_result, "files_created", [])
        report.files_modified = getattr(loop_result, "files_modified", [])

        # Quality summary from loop iterations
        quality_iters = [
            it for it in getattr(loop_result, "iterations", [])
            if getattr(it, "phase", "") == "quality"
        ]
        if quality_iters:
            last_q = quality_iters[-1]
            report.quality_summary = last_q.notes

        # ----------------------------------------------------------
        # Step 4: Auto-commit
        # ----------------------------------------------------------
        if auto_commit and loop_result.success and self._git is not None:
            sha = self._commit(goal, commit_message)
            report.committed  = bool(sha)
            report.commit_sha = sha

        # ----------------------------------------------------------
        # Step 5: Build summary
        # ----------------------------------------------------------
        report.summary       = self._build_summary(goal, req, loop_result)
        report.total_elapsed = time.monotonic() - t0

        self._persist(goal, report)

        logger.info(
            "SoftwareEngineer: done  success=%s  elapsed=%.1fs",
            report.success, report.total_elapsed,
        )
        return report

    # ------------------------------------------------------------------
    # Tier 1 fast path — TRIVIAL / SMALL
    # ------------------------------------------------------------------

    def _fast_path_build(
        self,
        goal: str,
        test_cmd: str,
        project_dir: str,
        complexity: TaskComplexity,
        t0: float,
        auto_commit: bool = False,
        commit_message: str = "",
    ) -> SoftwareEngineerReport:
        """
        Execution tier 1: one LLM call → parse fences → write files → done.

        No DevLoop, no Planner, no Scheduler, no specialist workers.
        Typical completion time: < 10 seconds.
        """
        print(
            f"  [tier] Tier: fast path"
            f" ({'trivial' if complexity == TaskComplexity.TRIVIAL else 'simple'} task)"
        )

        from smartagent.engineer.fast_path import FastPathBuilder

        builder = FastPathBuilder(
            model_manager=self._model_manager,
            project_dir=project_dir,
        )

        # Run tests only when a custom test command was supplied — the default
        # "pytest" with no args would accidentally run the entire SmartAgent suite.
        run_tests = bool(test_cmd and test_cmd != "pytest")

        fast_result = builder.build(
            goal=goal,
            test_cmd=test_cmd,
            run_tests=run_tests,
        )

        report = SoftwareEngineerReport(
            goal=goal,
            project_dir=project_dir,
            loop_result=fast_result,
            success=fast_result.success,
            files_created=fast_result.files_created,
            files_modified=fast_result.files_modified,
            total_elapsed=time.monotonic() - t0,
            summary=fast_result.final_summary,
        )

        if auto_commit and fast_result.success and self._git is not None:
            sha = self._commit(goal, commit_message)
            report.committed  = bool(sha)
            report.commit_sha = sha

        self._persist(goal, report)
        return report

    # ------------------------------------------------------------------
    # Sub-steps
    # ------------------------------------------------------------------

    def _scan_workspace(self, path: str) -> str:
        """Scan the workspace and return a brief summary string."""
        if self._workspace_scanner is None:
            return ""
        try:
            result = self._workspace_scanner.scan(path)
            # Different scanner APIs — try common attribute names
            for attr in ("summary", "as_summary", "short_summary"):
                fn = getattr(result, attr, None)
                if callable(fn):
                    return str(fn())
                if fn is not None:
                    return str(fn)
            # Fallback: stringify the result
            return str(result)[:200]
        except Exception as exc:
            logger.debug("SoftwareEngineer._scan_workspace: %s", exc)
            return ""

    def _analyze(self, goal: str, project_name: str) -> RequirementReport:
        """Analyze requirements, optionally enriching with project context."""
        enriched = goal
        if project_name and self._project_memory is not None:
            try:
                profile  = self._project_memory.load(project_name)
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
        workspace_summary: str,
    ) -> str:
        """Combine goal + workspace + analysis + clarifications into enriched prompt."""
        parts = [goal]
        if workspace_summary:
            parts.append(f"\n[Workspace]\n{workspace_summary[:400]}")
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
            msg    = commit_message or f"feat: {goal[:72]}"
            add_r  = self._git.add(".")
            if add_r.success:
                commit_r = self._git.commit(msg)
                sha = getattr(commit_r, "sha", "") or ""
                if sha:
                    self._emit("GitCommit", sha=sha, message=msg)
                return sha
        except Exception as exc:
            logger.warning("SoftwareEngineer: git commit failed: %s", exc)
        return ""

    def _build_summary(
        self,
        goal: str,
        req: RequirementReport,
        loop_result: Any,
    ) -> str:
        status  = "successfully completed" if loop_result.success else "partially completed"
        domains = ", ".join(req.domains[:4]) if req.domains else "general"
        cycles  = _count_cycles(loop_result)
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
            entry  = (
                f"Engineer {status}: {goal[:60]}  |  "
                f"Elapsed: {report.total_elapsed:.1f}s"
            )
            self._memory.remember(entry, category="Engineer")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_cycles(loop_result: Any) -> int:
    iters = getattr(loop_result, "iterations", [])
    if not iters:
        return 0
    return max((getattr(it, "iteration", 0) for it in iters), default=0)
