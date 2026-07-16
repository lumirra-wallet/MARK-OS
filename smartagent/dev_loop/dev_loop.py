"""
DevLoop — Milestone 24: Autonomous Development Loop.

Implements the full autonomous cycle:
    Receive Goal → Plan → Workers → Coding → Testing → Debugging → Reflection → Retry → Success

The loop is designed to be self-healing: if tests fail after coding, the
DebugLoop fires to patch files, then the tests are re-run.  After each full
cycle, the ReflectionEngine stores lessons.  The loop retries up to
``max_iterations`` times or until all tests pass.

Usage::

    loop = DevLoop.with_agent(agent)
    result = loop.run("Build a login system", test_cmd="pytest tests/")
    print("\\n".join(result.as_display_lines()))
"""

from __future__ import annotations

import time
from typing import Any, Optional

from smartagent.dev_loop.loop_result import LoopIteration, LoopResult
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TEST_CMD = "pytest"
_DEFAULT_MAX_ITERATIONS = 5


class DevLoop:
    """
    Autonomous development loop: plan → code → test → debug → reflect → retry.

    Args:
        executive:         :class:`~smartagent.executive.executive_controller.ExecutiveController`
                           for goal planning and coding.
        debug_loop:        :class:`~smartagent.debug.debug_loop.DebugLoop` for
                           self-healing (None disables auto-fixing).
        reflection_engine: :class:`~smartagent.reflection.reflection_engine.ReflectionEngine`
                           for post-cycle learning.
        memory_manager:    Optional — persists loop summary.
        git_client:        Optional — commits successful code automatically.
        max_iterations:    Maximum plan→code→test→fix cycles.  Default 5.
    """

    def __init__(
        self,
        executive: Any | None = None,
        debug_loop: Any | None = None,
        reflection_engine: Any | None = None,
        memory_manager: Any | None = None,
        git_client: Any | None = None,
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self._executive         = executive
        self._debug_loop        = debug_loop
        self._reflection_engine = reflection_engine
        self._memory            = memory_manager
        self._git               = git_client
        self._max_iterations    = max(1, max_iterations)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def with_agent(cls, agent: Any, max_iterations: int = _DEFAULT_MAX_ITERATIONS) -> "DevLoop":
        """Build a fully-wired DevLoop from a live ``SmartAgent``."""
        debug_loop = None
        try:
            from smartagent.debug.debug_loop import DebugLoop
            # DebugLoop accepts debug_worker=None; model-based fixing is optional.
            debug_loop = DebugLoop(max_attempts=3)
        except Exception as exc:
            logger.debug("DevLoop.with_agent: could not build DebugLoop: %s", exc)

        return cls(
            executive=getattr(agent, "executive", None),
            debug_loop=debug_loop,
            reflection_engine=getattr(agent, "reflection_engine", None),
            memory_manager=getattr(agent, "memory", None),
            git_client=None,  # caller can inject one
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
    ) -> LoopResult:
        """
        Run the autonomous development loop for *goal*.

        Args:
            goal:           Natural-language development goal.
            test_cmd:       Shell command to run tests (default: ``pytest``).
            auto_commit:    If True and loop succeeds, auto-commit via GitClient.
            commit_message: Commit message override (derived from goal if empty).

        Returns:
            :class:`LoopResult` — success=True when all tests pass.
        """
        t0 = time.monotonic()
        result = LoopResult(goal=goal, success=False)
        iterations: list[LoopIteration] = []

        logger.info("DevLoop: starting  goal=%r  max_iterations=%d", goal[:80], self._max_iterations)

        for cycle in range(1, self._max_iterations + 1):
            logger.info("DevLoop: cycle %d/%d", cycle, self._max_iterations)

            # ----------------------------------------------------------
            # PHASE 1: Planning + Coding via Executive
            # ----------------------------------------------------------
            plan_iter = self._run_planning_phase(cycle, goal)
            iterations.append(plan_iter)

            if not plan_iter.success:
                logger.warning("DevLoop: planning failed on cycle %d", cycle)
                result.stop_reason = "planning_failed"
                break

            # ----------------------------------------------------------
            # PHASE 2: Testing
            # ----------------------------------------------------------
            test_iter = self._run_test_phase(cycle, test_cmd)
            iterations.append(test_iter)

            if test_iter.success:
                # All tests pass — loop is done
                logger.info("DevLoop: tests passed on cycle %d", cycle)
                result.success = True
                result.stop_reason = "success"
                result.final_summary = (
                    f"All tests passed after {cycle} cycle(s). "
                    f"Goal accomplished: {goal[:80]}"
                )
                # Auto-commit if requested
                if auto_commit and self._git is not None:
                    self._auto_commit(goal, commit_message, iterations)
                break

            # Tests failed — try debugging
            # ----------------------------------------------------------
            # PHASE 3: Debugging (self-healing)
            # ----------------------------------------------------------
            debug_iter = self._run_debug_phase(cycle, test_cmd, test_iter.notes)
            iterations.append(debug_iter)

            # ----------------------------------------------------------
            # PHASE 4: Reflection
            # ----------------------------------------------------------
            reflect_iter = self._run_reflection_phase(cycle, goal, test_iter, debug_iter)
            iterations.append(reflect_iter)

            if cycle == self._max_iterations:
                result.stop_reason = "max_iterations"
                result.final_summary = (
                    f"Max iterations ({self._max_iterations}) reached. "
                    "Some tests are still failing."
                )
        else:
            if not result.success:
                result.stop_reason = "max_iterations"

        result.iterations = iterations
        result.total_elapsed = time.monotonic() - t0

        # Persist summary to memory
        self._persist(goal, result)

        logger.info(
            "DevLoop: done  success=%s  cycles=%d  elapsed=%.1fs",
            result.success, _cycle_count(iterations), result.total_elapsed,
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
                ctx = self._executive.receive_goal(goal)
                state = str(getattr(ctx, "state", "")).lower()
                success = "completed" in state or "ready" in state
                notes = f"State: {state}"
            else:
                # No executive wired — mark success so loop can proceed
                success = True
                notes = "No executive — skipping planning phase."
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

    def _run_test_phase(self, cycle: int, test_cmd: str) -> LoopIteration:
        import subprocess
        t0 = time.monotonic()
        passed = failed = 0
        notes = ""

        try:
            proc = subprocess.run(
                test_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = proc.stdout + proc.stderr
            success = proc.returncode == 0
            passed, failed = _parse_pytest_counts(output)
            notes = _last_lines(output, 6)
        except subprocess.TimeoutExpired:
            success = False
            notes = f"Test command timed out after 300s: {test_cmd}"
        except Exception as exc:
            success = False
            notes = str(exc)

        return LoopIteration(
            iteration=cycle,
            phase="testing",
            success=success,
            notes=notes,
            tests_passed=passed,
            tests_failed=failed,
            elapsed=time.monotonic() - t0,
        )

    def _run_debug_phase(
        self,
        cycle: int,
        test_cmd: str,
        test_output: str,
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
            debug_result = self._debug_loop.run(test_cmd)
            success = debug_result.success
            attempts = len(debug_result.attempts)
            notes = f"{attempts} attempt(s). " + (
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
        t0 = time.monotonic()
        notes = ""

        if self._reflection_engine is not None:
            try:
                self._reflection_engine.reflect(
                    task_name=f"dev_loop_cycle_{cycle}",
                    succeeded=debug_iter.success,
                    what_happened=(
                        f"Goal: {goal[:80]}  |  "
                        f"Tests: {test_iter.tests_passed} passed, {test_iter.tests_failed} failed  |  "
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
    # Auto-commit
    # ------------------------------------------------------------------

    def _auto_commit(
        self,
        goal: str,
        commit_message: str,
        iterations: list[LoopIteration],
    ) -> None:
        try:
            msg = commit_message or f"feat: {goal[:72]}"
            add_result = self._git.add(".")
            if add_result.success:
                commit_result = self._git.commit(msg)
                if commit_result.success:
                    logger.info("DevLoop: auto-committed  sha=%s", getattr(commit_result, "sha", "?"))
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
            entry = (
                f"DevLoop {status}: {goal[:60]}  |  "
                f"Cycles: {_cycle_count(result.iterations)}  |  "
                f"Elapsed: {result.total_elapsed:.1f}s"
            )
            self._memory.remember(entry, category="DevLoop")
        except Exception:
            pass


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
