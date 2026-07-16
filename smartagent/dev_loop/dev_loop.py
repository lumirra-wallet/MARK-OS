"""
DevLoop — Milestone 24 + v2.0 upgrade + v2.0 file-write fix.

Implements the full autonomous cycle:
    Receive Goal → Plan → Workers → Coding → Testing → Quality → Debugging
    → Reflection → Retry → Success

v2.0 adds:
  - Phase 5: QualityRunner (ruff, black, mypy) executed after tests pass.
  - ExecutionDashboard integration for live progress tracking.
  - More granular stop reasons and iteration metadata.

v2.0 file-write fix:
  - ``run()`` accepts ``project_dir`` — the directory where generated files live.
  - Before planning, the Orchestrator's FileEditor is rooted at ``project_dir``.
  - After planning, the file_editor is retrieved from the execution context so
    ``_run_test_phase`` can scope pytest to only the generated test files.
  - ``_run_test_phase`` and ``_run_debug_phase`` run ``subprocess`` with
    ``cwd=project_dir`` so relative imports in generated code work correctly.
  - The LoopResult carries ``files_created`` / ``files_modified`` / ``project_dir``.

Usage::

    loop = DevLoop.with_agent(agent)
    result = loop.run("Build a login system", test_cmd="pytest tests/")
    print("\\n".join(result.as_display_lines()))
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from smartagent.dev_loop.loop_result import LoopIteration, LoopResult
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TEST_CMD       = "pytest"
_DEFAULT_MAX_ITERATIONS = 5


class DevLoop:
    """
    Autonomous development loop: plan → code → test → quality → debug → reflect → retry.

    Args:
        executive:         :class:`~smartagent.executive.executive_controller.ExecutiveController`
                           for goal planning and coding.
        debug_loop:        :class:`~smartagent.debug.debug_loop.DebugLoop` for
                           self-healing (None disables auto-fixing).
        reflection_engine: :class:`~smartagent.reflection.reflection_engine.ReflectionEngine`
                           for post-cycle learning.
        quality_runner:    :class:`~smartagent.quality.QualityRunner` for
                           ruff/black/mypy checks (None skips quality phase).
        dashboard:         :class:`~smartagent.ui.dashboard.ExecutionDashboard`
                           for live progress (None disables dashboard).
        memory_manager:    Optional — persists loop summary.
        git_client:        Optional — commits successful code automatically.
        max_iterations:    Maximum plan→code→test→fix cycles.  Default 5.
    """

    def __init__(
        self,
        executive: Any | None = None,
        debug_loop: Any | None = None,
        reflection_engine: Any | None = None,
        quality_runner: Any | None = None,
        dashboard: Any | None = None,
        memory_manager: Any | None = None,
        git_client: Any | None = None,
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self._executive         = executive
        self._debug_loop        = debug_loop
        self._reflection_engine = reflection_engine
        self._quality_runner    = quality_runner
        self._dashboard         = dashboard
        self._memory            = memory_manager
        self._git               = git_client
        self._max_iterations    = max(1, max_iterations)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_agent(
        cls,
        agent: Any,
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
        cwd: str = ".",
    ) -> "DevLoop":
        """Build a fully-wired DevLoop from a live ``SmartAgent``."""
        debug_loop = None
        try:
            from smartagent.debug.debug_loop import DebugLoop
            debug_loop = DebugLoop(max_attempts=3, cwd=cwd)
        except Exception as exc:
            logger.debug("DevLoop.with_agent: could not build DebugLoop: %s", exc)

        quality_runner = None
        try:
            from smartagent.quality.quality_runner import QualityRunner
            quality_runner = QualityRunner(cwd=cwd)
        except Exception as exc:
            logger.debug("DevLoop.with_agent: could not build QualityRunner: %s", exc)

        return cls(
            executive=getattr(agent, "executive", None),
            debug_loop=debug_loop,
            reflection_engine=getattr(agent, "reflection_engine", None),
            quality_runner=quality_runner,
            memory_manager=getattr(agent, "memory", None),
            git_client=None,
            max_iterations=max_iterations,
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def run(
        self,
        goal: str,
        test_cmd: str = _DEFAULT_TEST_CMD,
        auto_commit: bool = False,
        commit_message: str = "",
        run_quality: bool = True,
        project_dir: str | None = None,
    ) -> LoopResult:
        """
        Run the autonomous development loop for *goal*.

        Args:
            goal:         Natural-language development goal.
            test_cmd:     Shell command to run tests (default: ``pytest``).
            auto_commit:  If True and loop succeeds, auto-commit via GitClient.
            commit_message: Commit message override (derived from goal if empty).
            run_quality:  Whether to run the quality phase (ruff/black/mypy).
            project_dir:  Directory where generated files should be written and
                          where tests should run.  Defaults to ``os.getcwd()``.

        Returns:
            :class:`LoopResult` — success=True when all tests pass.
        """
        t0 = time.monotonic()

        # Resolve the project directory once for the whole run
        resolved_dir = os.path.abspath(project_dir) if project_dir else os.getcwd()
        logger.info(
            "DevLoop: starting  goal=%r  project_dir=%s  max_iterations=%d",
            goal[:80], resolved_dir, self._max_iterations,
        )

        # v2.0 fix — tell the orchestrator where to root the FileEditor so
        # generated files land in the project directory (not in ./output/).
        _set_orchestrator_project_dir(self._executive, resolved_dir)

        result = LoopResult(goal=goal, success=False, project_dir=resolved_dir)
        iterations: list[LoopIteration] = []
        file_editor: Any = None  # retrieved after first planning phase

        # Dashboard
        if self._dashboard is not None:
            try:
                self._dashboard.start(goal)
            except Exception:
                pass

        for cycle in range(1, self._max_iterations + 1):
            logger.info("DevLoop: cycle %d/%d", cycle, self._max_iterations)
            self._dash_set("current_worker", f"Cycle {cycle}/{self._max_iterations}")

            # ──────────────────────────────────────────────────────────
            # PHASE 1: Planning + Coding via Executive
            # ──────────────────────────────────────────────────────────
            self._dash_set("current_worker", "Planner")
            plan_iter = self._run_planning_phase(cycle, goal)
            iterations.append(plan_iter)

            if not plan_iter.success:
                logger.warning("DevLoop: planning failed on cycle %d", cycle)
                result.stop_reason = "planning_failed"
                break

            # v2.0 fix — retrieve the file_editor from the execution context
            # so we can scope pytest to only the generated test files.
            file_editor = _get_file_editor(self._executive)

            self._dash_add_completed("Planning")

            # ──────────────────────────────────────────────────────────
            # PHASE 2: Testing
            # ──────────────────────────────────────────────────────────
            self._dash_set("current_worker", "TestRunner")
            test_iter = self._run_test_phase(cycle, test_cmd, file_editor, resolved_dir)
            iterations.append(test_iter)
            self._dash_set_tests(test_iter.tests_passed, test_iter.tests_failed)

            if test_iter.success:
                logger.info("DevLoop: tests passed on cycle %d", cycle)

                # ──────────────────────────────────────────────────────
                # PHASE 2b: Quality (only after tests pass)
                # ──────────────────────────────────────────────────────
                if run_quality and self._quality_runner is not None:
                    self._dash_set("current_worker", "QualityRunner")
                    quality_iter = self._run_quality_phase(cycle)
                    iterations.append(quality_iter)
                    if quality_iter.success:
                        self._dash_add_completed("Quality checks")

                result.success     = True
                result.stop_reason = "success"
                result.final_summary = (
                    f"All tests passed after {cycle} cycle(s). "
                    f"Goal accomplished: {goal[:80]}"
                )
                if auto_commit and self._git is not None:
                    self._auto_commit(goal, commit_message, iterations)
                break

            # ──────────────────────────────────────────────────────────
            # PHASE 3: Debugging (self-healing)
            # ──────────────────────────────────────────────────────────
            self._dash_set("current_worker", "DebugLoop")
            # Build the same scoped test command the debug loop should use
            scoped_cmd = _build_scoped_test_cmd(test_cmd, file_editor, resolved_dir)
            debug_iter = self._run_debug_phase(cycle, scoped_cmd, test_iter.notes, resolved_dir)
            iterations.append(debug_iter)
            if not debug_iter.success:
                self._dash_increment_retries()

            # ──────────────────────────────────────────────────────────
            # PHASE 4: Reflection
            # ──────────────────────────────────────────────────────────
            self._dash_set("current_worker", "ReflectionEngine")
            reflect_iter = self._run_reflection_phase(cycle, goal, test_iter, debug_iter)
            iterations.append(reflect_iter)
            self._dash_add_completed(f"Cycle {cycle}")

            if cycle == self._max_iterations:
                result.stop_reason = "max_iterations"
                result.final_summary = (
                    f"Max iterations ({self._max_iterations}) reached. "
                    "Some tests are still failing."
                )
        else:
            if not result.success:
                result.stop_reason = "max_iterations"

        result.iterations    = iterations
        result.total_elapsed = time.monotonic() - t0

        # v2.0 fix — collect which files were created/modified during this run
        if file_editor is not None:
            try:
                edits = file_editor.list_edits()
                result.files_created = [
                    e.path for e in edits
                    if e.success and e.operation == "create"
                ]
                result.files_modified = [
                    e.path for e in edits
                    if e.success and e.operation in ("edit", "patch")
                ]
            except Exception:
                pass

        if self._dashboard is not None:
            try:
                self._dashboard.complete(result.success)
            except Exception:
                pass

        self._persist(goal, result)

        logger.info(
            "DevLoop: done  success=%s  cycles=%d  elapsed=%.1fs  "
            "files_created=%d  files_modified=%d",
            result.success, _cycle_count(iterations), result.total_elapsed,
            len(result.files_created), len(result.files_modified),
        )
        return result

    # ------------------------------------------------------------------
    # Phase runners
    # ------------------------------------------------------------------

    def _run_planning_phase(self, cycle: int, goal: str) -> LoopIteration:
        t0 = time.monotonic()
        notes = ""
        success = False
        try:
            if self._executive is not None:
                ctx   = self._executive.receive_goal(goal)
                state = str(getattr(ctx, "state", "")).lower()
                success = "completed" in state or "ready" in state
                notes   = f"State: {state}"
            else:
                success = True
                notes   = "No executive — skipping planning phase."
        except Exception as exc:
            notes = f"Planning error: {exc}"
            logger.warning("DevLoop: planning raised: %s", exc)

        return LoopIteration(
            iteration=cycle,
            phase="planning",
            success=success,
            notes=notes,
            elapsed=time.monotonic() - t0,
        )

    def _run_test_phase(
        self,
        cycle: int,
        test_cmd: str,
        file_editor: Any = None,
        project_dir: str | None = None,
    ) -> LoopIteration:
        """
        Run tests for the generated project.

        v2.0 fix: when ``file_editor`` is available, pytest is scoped to
        only the test files generated by this run (so SmartAgent's own 2000+
        tests are never accidentally discovered).  The subprocess runs with
        ``cwd=project_dir`` so relative imports in generated code work.
        """
        import subprocess
        t0 = time.monotonic()
        passed = failed = 0
        notes  = ""

        # Build the scoped command targeting only generated test files
        scoped_cmd = _build_scoped_test_cmd(test_cmd, file_editor, project_dir)
        cwd = project_dir or None

        logger.info("DevLoop: running tests: %r (cwd=%s)", scoped_cmd, cwd)

        try:
            proc = subprocess.run(
                scoped_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=cwd,
            )
            output  = proc.stdout + proc.stderr
            success = proc.returncode == 0
            passed, failed = _parse_pytest_counts(output)
            notes   = _last_lines(output, 6)
        except subprocess.TimeoutExpired:
            success = False
            notes   = f"Test command timed out after 300s: {scoped_cmd}"
        except Exception as exc:
            success = False
            notes   = str(exc)

        return LoopIteration(
            iteration=cycle,
            phase="testing",
            success=success,
            notes=notes,
            tests_passed=passed,
            tests_failed=failed,
            elapsed=time.monotonic() - t0,
        )

    def _run_quality_phase(self, cycle: int) -> LoopIteration:
        """Run ruff / black / mypy via QualityRunner."""
        t0 = time.monotonic()
        try:
            report  = self._quality_runner.run_all(tools=["ruff", "black", "mypy"])
            success = report.all_passed
            failing = report.failing_tools()
            notes   = (
                "All quality checks passed."
                if success
                else f"Failing: {', '.join(failing)}"
            )
        except Exception as exc:
            success = False
            notes   = f"Quality runner error: {exc}"
            logger.warning("DevLoop: quality raised: %s", exc)

        return LoopIteration(
            iteration=cycle,
            phase="quality",
            success=success,
            notes=notes,
            elapsed=time.monotonic() - t0,
        )

    def _run_debug_phase(
        self,
        cycle: int,
        test_cmd: str,
        test_output: str,
        project_dir: str | None = None,
    ) -> LoopIteration:
        t0 = time.monotonic()
        notes = ""
        success = False

        if self._debug_loop is None:
            return LoopIteration(
                iteration=cycle,
                phase="debugging",
                success=False,
                notes="No DebugLoop wired.",
                elapsed=0.0,
            )

        try:
            # v2.0 fix — point the DebugLoop at the generated project dir
            if project_dir is not None:
                _patch_debug_loop_cwd(self._debug_loop, project_dir)

            debug_result = self._debug_loop.run(test_cmd)
            success      = debug_result.success
            attempts     = len(debug_result.attempts)
            notes        = f"{attempts} attempt(s). " + (
                "Fixed." if success else "Still failing."
            )
        except Exception as exc:
            notes = f"Debug error: {exc}"
            logger.warning("DevLoop: debug raised: %s", exc)

        return LoopIteration(
            iteration=cycle,
            phase="debugging",
            success=success,
            notes=notes,
            elapsed=time.monotonic() - t0,
        )

    def _run_reflection_phase(
        self,
        cycle: int,
        goal: str,
        test_iter: LoopIteration,
        debug_iter: LoopIteration,
    ) -> LoopIteration:
        t0    = time.monotonic()
        notes = ""

        if self._reflection_engine is not None:
            try:
                self._reflection_engine.reflect(
                    task_name=f"dev_loop_cycle_{cycle}",
                    succeeded=debug_iter.success,
                    what_happened=(
                        f"Goal: {goal[:80]}  |  "
                        f"Tests: {test_iter.tests_passed} passed, "
                        f"{test_iter.tests_failed} failed  |  "
                        f"Debug: {'fixed' if debug_iter.success else 'still failing'}"
                    ),
                )
                notes = "Reflection stored."
            except Exception as exc:
                notes = f"Reflection skipped: {exc}"
        else:
            notes = "No reflection engine wired."

        return LoopIteration(
            iteration=cycle,
            phase="reflection",
            success=True,
            notes=notes,
            elapsed=time.monotonic() - t0,
        )

    # ------------------------------------------------------------------
    # Dashboard helpers (all safe — never raise)
    # ------------------------------------------------------------------

    def _dash_set(self, key: str, value: str) -> None:
        if self._dashboard is None:
            return
        try:
            self._dashboard.set(key, value)
        except Exception:
            pass

    def _dash_add_completed(self, task: str) -> None:
        if self._dashboard is None:
            return
        try:
            self._dashboard.add_completed(task)
        except Exception:
            pass

    def _dash_set_tests(self, passed: int, failed: int) -> None:
        if self._dashboard is None:
            return
        try:
            self._dashboard.set_tests(passed, failed)
        except Exception:
            pass

    def _dash_increment_retries(self) -> None:
        if self._dashboard is None:
            return
        try:
            self._dashboard.increment_retries()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Auto-commit
    # ------------------------------------------------------------------

    def _auto_commit(
        self,
        goal: str,
        commit_message: str,
        iterations: list[LoopIteration],
    ) -> None:
        try:
            msg        = commit_message or f"feat: {goal[:72]}"
            add_result = self._git.add(".")
            if add_result.success:
                commit_result = self._git.commit(msg)
                if commit_result.success:
                    logger.info(
                        "DevLoop: auto-committed  sha=%s",
                        getattr(commit_result, "sha", "?"),
                    )
        except Exception as exc:
            logger.warning("DevLoop: auto-commit failed: %s", exc)

    # ------------------------------------------------------------------
    # Memory persistence
    # ------------------------------------------------------------------

    def _persist(self, goal: str, result: LoopResult) -> None:
        if self._memory is None:
            return
        try:
            status = "succeeded" if result.success else "did not complete"
            entry  = (
                f"DevLoop {status}: {goal[:60]}  |  "
                f"Cycles: {_cycle_count(result.iterations)}  |  "
                f"Elapsed: {result.total_elapsed:.1f}s"
            )
            self._memory.remember(entry, category="DevLoop")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# v2.0 fix — helpers for project_dir threading
# ---------------------------------------------------------------------------

def _set_orchestrator_project_dir(executive: Any, project_dir: str) -> None:
    """
    Propagate *project_dir* to the Orchestrator so its FileEditor is rooted
    at the right location before ``receive_goal()`` is called.
    """
    try:
        if executive is None:
            return
        orch = getattr(executive, "_orchestrator", None)
        if orch is not None and hasattr(orch, "set_project_dir"):
            orch.set_project_dir(project_dir)
            logger.debug("DevLoop: project_dir=%s set on orchestrator", project_dir)
    except Exception as exc:
        logger.debug("DevLoop._set_orchestrator_project_dir: %s", exc)


def _get_file_editor(executive: Any) -> Any:
    """Retrieve the FileEditor from the executive's current execution context."""
    try:
        ctx = getattr(executive, "current_context", None)
        if ctx is not None:
            return ctx.metadata.get("file_editor")
    except Exception:
        pass
    return None


def _build_scoped_test_cmd(
    test_cmd: str,
    file_editor: Any,
    project_dir: str | None,
) -> str:
    """
    Build a pytest command targeting only the generated test files.

    When *file_editor* has recorded test files (``test_*.py`` / ``*_test.py``),
    the default ``pytest`` command is replaced with ``pytest <test_files>``.
    Custom test commands (e.g. ``pytest tests/`` or ``python -m pytest -x``)
    are returned unchanged so the user retains full control.

    If no test files have been generated yet, returns the original command so
    the caller can handle the empty-output case.
    """
    if file_editor is None:
        return test_cmd

    # Only scope the bare default command; leave user-specified commands alone
    bare_cmds = {"pytest", "python -m pytest"}
    is_bare = test_cmd.strip() in bare_cmds

    try:
        edits = file_editor.list_edits()
        test_files = [
            e.path for e in edits
            if e.success
            and e.operation in ("create", "edit")
            and _is_test_file(e.path)
        ]
    except Exception:
        return test_cmd

    if not test_files:
        # No generated test files — return as-is; tests will fail/warn naturally
        return test_cmd

    if is_bare:
        return "pytest " + " ".join(test_files)

    return test_cmd


def _patch_debug_loop_cwd(debug_loop: Any, project_dir: str) -> None:
    """Redirect the DebugLoop's working directory to *project_dir*."""
    try:
        if hasattr(debug_loop, "_cwd"):
            debug_loop._cwd = project_dir
        elif hasattr(debug_loop, "cwd"):
            debug_loop.cwd = project_dir
    except Exception:
        pass


def _is_test_file(path: str) -> bool:
    """Return True if *path* looks like a pytest test file."""
    name = os.path.basename(path)
    return name.startswith("test_") or name.endswith("_test.py")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_pytest_counts(output: str) -> tuple[int, int]:
    """Extract (passed, failed) counts from pytest output."""
    import re
    passed = failed = 0
    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", output)
    if m:
        failed = int(m.group(1))
    return passed, failed


def _last_lines(text: str, n: int) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:]) if lines else ""


def _cycle_count(iterations: list[LoopIteration]) -> int:
    if not iterations:
        return 0
    return max(it.iteration for it in iterations)
