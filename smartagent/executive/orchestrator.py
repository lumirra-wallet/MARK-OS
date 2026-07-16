"""
Orchestrator — wires Planner → TaskGraph → TaskQueue → Scheduler.

The ``Orchestrator`` is the coordinator that the ``ExecutiveController``
delegates to.  It owns the three-step pipeline:

    1. Planner.create_plan(goal)      → list[Task]
    2. build_task_graph(tasks)        → TaskGraph  (with dependency edges)
    3. submit_to_queue(graph)         → TaskQueue  (seed with ready tasks)
    4. Scheduler.run(context)         → ExecutionContext (results)

Separating the Orchestrator from the ExecutiveController keeps the
controller's public API clean (``receive_goal`` → result) while all the
wiring lives here and is independently testable.
"""

from __future__ import annotations

from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.planner import Planner
from smartagent.executive.scheduler import Scheduler
from smartagent.executive.task import Task, TaskStatus
from smartagent.executive.task_graph import TaskGraph, TaskGraphError
from smartagent.executive.task_queue import TaskQueue
from smartagent.executive.worker_registry import WorkerRegistry, build_default_registry
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


class Orchestrator:
    """
    Coordinates goal decomposition and task execution.

    Args:
        planner:         Decomposes goals into task lists.
        scheduler:       Executes tasks in dependency order.
        worker_registry: Maps task types to worker classes.
    """

    def __init__(
        self,
        planner: Planner | None = None,
        scheduler: Scheduler | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        self._planner = planner or Planner()
        self._worker_registry = worker_registry or build_default_registry()
        self._scheduler = scheduler or Scheduler(worker_registry=self._worker_registry)

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def execute_goal(self, goal: str) -> ExecutionContext:
        """
        Run the full pipeline for *goal* and return the completed context.

        Steps:
            1. Create a plan (list of tasks) from the goal.
            2. Build a validated TaskGraph.
            3. Seed the TaskQueue with initially-ready tasks.
            4. Run the Scheduler until all tasks complete or fail.

        Returns:
            ``ExecutionContext`` with final state = COMPLETED or FAILED.

        Raises:
            ValueError:      If *goal* is empty.
            TaskGraphError:  If the plan contains dependency cycles (bug in Planner).
        """
        context = ExecutionContext(goal=goal)
        context.transition_to(ExecutionState.PLANNING)
        logger.info("Orchestrator: planning goal=%r", goal)

        # Step 1 — decompose.
        tasks = self._planner.create_plan(goal)
        logger.info("Orchestrator: plan has %d tasks", len(tasks))

        # Step 2 — build graph.
        graph = self.build_task_graph(tasks)

        # Step 3 — wire context.
        context.task_graph = graph
        context.task_queue = self.submit_to_queue(graph)
        context.transition_to(ExecutionState.READY)

        # Step 4 — execute.
        return self._scheduler.run(context)

    # ------------------------------------------------------------------
    # Sub-steps (also used standalone by ExecutiveController for display)
    # ------------------------------------------------------------------

    def build_task_graph(self, tasks: list[Task]) -> TaskGraph:
        """
        Arrange *tasks* into a validated ``TaskGraph``.

        Validates that all dependency references exist and the graph is
        acyclic before returning.

        Raises:
            TaskGraphError: On missing dependency or cycle.
        """
        graph = TaskGraph()
        for task in tasks:
            graph.add_task(task)
        graph.validate()
        return graph

    def submit_to_queue(self, graph: TaskGraph) -> TaskQueue:
        """
        Create a ``TaskQueue`` seeded with the initially-ready tasks
        (tasks that have no dependencies).

        Moves those tasks from PENDING to READY before enqueuing.
        """
        queue = TaskQueue()
        for task in graph.all_tasks():
            if task.status == TaskStatus.PENDING and not task.dependencies:
                task.mark_ready()
                queue.enqueue(task)
        logger.debug("Orchestrator: queue seeded with %d tasks", queue.size())
        return queue

    # ------------------------------------------------------------------
    # Plan preview (no execution — used by `plan` console command)
    # ------------------------------------------------------------------

    def preview_plan(self, goal: str) -> ExecutionContext:
        """
        Build and return a context in READY state WITHOUT executing it.

        Used by the ``plan`` console command to display the task graph
        before the user commits to running it.
        """
        context = ExecutionContext(goal=goal)
        context.transition_to(ExecutionState.PLANNING)
        tasks = self._planner.create_plan(goal)
        graph = self.build_task_graph(tasks)
        context.task_graph = graph
        context.task_queue = self.submit_to_queue(graph)
        context.transition_to(ExecutionState.READY)
        logger.info("Orchestrator: preview plan built (%d tasks) for goal=%r", len(tasks), goal)
        return context
