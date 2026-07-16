"""
ExecutiveController — top-level interface for the Executive Framework.

This is the single entry point that the ``SmartAgent`` (and console
commands) interact with.  All internal wiring (Planner, Orchestrator,
Scheduler, WorkerRegistry) is hidden behind this clean API:

    controller = ExecutiveController()

    # Display a plan without executing it:
    context = controller.plan(goal)

    # Execute a plan end-to-end:
    context = controller.receive_goal(goal)

    # Inspect the last context:
    context = controller.current_context

The four-step pipeline (for documentation / mental model):

    receive_goal()
        ↓
    create_plan()          — Planner decomposes the goal
        ↓
    build_task_graph()     — TaskGraph validates and arranges tasks
        ↓
    submit_to_queue()      — TaskQueue seeds with ready tasks
        ↓
    scheduler executes     — each task runs (stub in Phase 1)
        ↓
    return results         — ExecutionContext with final state

Note on naming:
    The ``smartagent.mind.executive.executive_controller.ExecutiveController``
    (Milestone 6) controls MARK's internal mental processes.  This class
    (``smartagent.executive.executive_controller.ExecutiveController``) is
    the *planning and task orchestration* controller — a separate concern.
    On ``SmartAgent`` the mind controller lives at ``agent.mind``; this
    one lives at ``agent.executive``.
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

    Owns the Orchestrator (which owns Planner + Scheduler + WorkerRegistry)
    and keeps track of the most recent ``ExecutionContext`` so console
    commands (``tasks``, ``queue``) can inspect it between calls.

    Attributes:
        current_context: The most recently created ``ExecutionContext``, or
                         ``None`` if no goal has been received yet.
    """

    def __init__(
        self,
        planner: Planner | None = None,
        scheduler: Scheduler | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._worker_registry = worker_registry or build_default_registry()
        self._planner = planner or Planner()
        self._scheduler = scheduler or Scheduler(worker_registry=self._worker_registry)
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
        Accept *goal*, create a full plan, execute it, and return results.

        This is the full pipeline: plan + execute.  Use ``plan()`` instead
        to preview the task breakdown without running it.

        Args:
            goal: Free-form goal string (e.g. "Build a REST API for tasks").

        Returns:
            A completed ``ExecutionContext`` (state = COMPLETED or FAILED).
        """
        logger.info("ExecutiveController: received goal=%r", goal)
        context = self._orchestrator.execute_goal(goal)
        self.current_context = context
        return context

    def plan(self, goal: str) -> ExecutionContext:
        """
        Create and return a plan for *goal* WITHOUT executing it.

        The returned context is in READY state — tasks are built and
        validated but the Scheduler has not run.  Subsequent calls to
        ``run()`` will execute this plan.

        Args:
            goal: Free-form goal string.

        Returns:
            An ``ExecutionContext`` in READY state.
        """
        logger.info("ExecutiveController: planning goal=%r (preview only)", goal)
        context = self._orchestrator.preview_plan(goal)
        self.current_context = context
        return context

    def run(self) -> ExecutionContext:
        """
        Execute the current plan (from the last ``plan()`` call).

        Raises:
            RuntimeError: If no plan has been created yet.

        Returns:
            The updated ``ExecutionContext`` (state = COMPLETED or FAILED).
        """
        if self.current_context is None:
            raise RuntimeError(
                "No plan to run.  Call plan(<goal>) or receive_goal(<goal>) first."
            )
        logger.info("ExecutiveController: running current plan for goal=%r", self.current_context.goal)
        context = self._scheduler.run(self.current_context)
        self.current_context = context
        return context

    # ------------------------------------------------------------------
    # Expose pipeline steps individually (for testing and console commands)
    # ------------------------------------------------------------------

    def create_plan(self, goal: str) -> list[Task]:
        """
        Step 1: Use the Planner to decompose *goal* into a list of Tasks.

        Does not modify ``current_context``.  Useful for displaying the
        raw task list before building the graph.
        """
        return self._planner.create_plan(goal)

    def build_task_graph(self, tasks: list[Task]) -> TaskGraph:
        """
        Step 2: Arrange *tasks* into a validated TaskGraph.

        Does not modify ``current_context``.
        """
        return self._orchestrator.build_task_graph(tasks)

    def submit_to_queue(self, graph: TaskGraph) -> TaskQueue:
        """
        Step 3: Seed a TaskQueue with the initially-ready tasks from *graph*.

        Does not modify ``current_context``.
        """
        return self._orchestrator.submit_to_queue(graph)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def worker_registry(self) -> WorkerRegistry:
        """The WorkerRegistry used by this controller."""
        return self._worker_registry

    @property
    def planner(self) -> Planner:
        """The Planner used for goal decomposition."""
        return self._planner

    def has_plan(self) -> bool:
        """True when a plan (ExecutionContext) has been created."""
        return self.current_context is not None

    def __repr__(self) -> str:
        ctx = self.current_context
        if ctx:
            return (
                f"ExecutiveController(goal={ctx.goal!r}, "
                f"state={ctx.state.value}, "
                f"tasks={ctx.task_count})"
            )
        return "ExecutiveController(no plan)"
