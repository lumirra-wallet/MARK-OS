"""
ExecutiveController — top-level interface for the Executive Framework.

Phase 2/3 upgrade: real workers, cancellation, run/cancel support.

Public API (unchanged from Phase 1):
    controller.plan(goal)          → ExecutionContext (READY, not executed)
    controller.receive_goal(goal)  → ExecutionContext (COMPLETED/FAILED)
    controller.run()               → ExecutionContext (execute current plan)
    controller.cancel()            → cancels current plan mid-run

Phase 2 change:
    ``build_default_registry()`` now registers real ``BaseWorker`` classes.
    The pipeline and interface are identical — only execution output changes.

Phase 3 change:
    ``cancel()`` method added.  ``run()`` returns the updated context even
    when cancelled.  Console commands ``run`` and ``cancel`` call these.

Note on naming:
    ``smartagent.mind.executive.executive_controller.ExecutiveController``
    (Milestone 6) controls MARK's internal mental processes.
    This class is the *planning and task orchestration* controller.
    On ``SmartAgent``: ``agent.mind`` = Mind OS; ``agent.executive`` = this.
"""

from __future__ import annotations

from typing import Optional

from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.orchestrator import Orchestrator
from smartagent.executive.planner import Planner
from smartagent.executive.scheduler import Scheduler
from smartagent.executive.task import Task
from smartagent.executive.task_graph import TaskGraph
from smartagent.executive.task_queue import TaskQueue
from smartagent.executive.worker_registry import WorkerRegistry, build_default_registry
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


class ExecutiveController:
    """
    Top-level coordinator for the MARK Executive Framework (Milestone 11).

    Attributes:
        current_context: Most recent ``ExecutionContext``, or ``None``.
    """

    def __init__(
        self,
        planner: Planner | None = None,
        scheduler: Scheduler | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._worker_registry = worker_registry or build_default_registry()
        self._planner = planner or Planner()
        self._scheduler = scheduler or Scheduler(
            worker_registry=self._worker_registry
        )
        self._orchestrator = Orchestrator(
            planner=self._planner,
            scheduler=self._scheduler,
            worker_registry=self._worker_registry,
        )
        self.current_context: Optional[ExecutionContext] = None

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def receive_goal(self, goal: str) -> ExecutionContext:
        """
        Full pipeline: plan + execute.  Returns the completed context.
        """
        logger.info("ExecutiveController: received goal=%r", goal)
        context = self._orchestrator.execute_goal(goal)
        self.current_context = context
        return context

    def plan(self, goal: str) -> ExecutionContext:
        """
        Build a plan for *goal* WITHOUT executing it (READY state).

        Stores the context so ``run()`` / ``tasks`` / ``queue`` can use it.
        """
        logger.info("ExecutiveController: planning goal=%r (preview)", goal)
        context = self._orchestrator.preview_plan(goal)
        self.current_context = context
        return context

    def run(self) -> ExecutionContext:
        """
        Execute the current plan (from the last ``plan()`` call).

        Phase 3: respects cancellation — if ``cancel()`` was called on the
        context before ``run()`` finishes, execution stops cleanly.

        Raises:
            RuntimeError: If no plan has been created yet.
        """
        if self.current_context is None:
            raise RuntimeError(
                "No plan to run.  Call plan(<goal>) or receive_goal(<goal>) first."
            )
        logger.info(
            "ExecutiveController: running plan for goal=%r",
            self.current_context.goal,
        )
        context = self._scheduler.run(self.current_context)
        self.current_context = context
        return context

    def cancel(self) -> bool:
        """
        Cancel the current plan.

        Marks all non-terminal tasks as BLOCKED and sets the context state
        to CANCELLED.  Returns ``True`` if there was a plan to cancel,
        ``False`` otherwise.
        """
        if self.current_context is None:
            return False
        if self.current_context.state.is_terminal:
            return False
        logger.info(
            "ExecutiveController: cancelling goal=%r",
            self.current_context.goal,
        )
        self.current_context.cancel()
        return True

    # ------------------------------------------------------------------
    # Expose pipeline steps individually
    # ------------------------------------------------------------------

    def create_plan(self, goal: str) -> list[Task]:
        """Step 1: decompose *goal* into a list of Tasks."""
        return self._planner.create_plan(goal)

    def build_task_graph(self, tasks: list[Task]) -> TaskGraph:
        """Step 2: arrange *tasks* into a validated TaskGraph."""
        return self._orchestrator.build_task_graph(tasks)

    def submit_to_queue(self, graph: TaskGraph) -> TaskQueue:
        """Step 3: seed a TaskQueue with initially-ready tasks."""
        return self._orchestrator.submit_to_queue(graph)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def worker_registry(self) -> WorkerRegistry:
        return self._worker_registry

    @property
    def planner(self) -> Planner:
        return self._planner

    def has_plan(self) -> bool:
        return self.current_context is not None

    def __repr__(self) -> str:
        ctx = self.current_context
        if ctx:
            return (
                f"ExecutiveController(goal={ctx.goal!r}, "
                f"state={ctx.state.value}, tasks={ctx.task_count})"
            )
        return "ExecutiveController(no plan)"
