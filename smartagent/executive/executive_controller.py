"""
ExecutiveController — Phase 11.4/11.5 upgrade.

Phase 11.4: accepts optional AI service references and threads them
through the Orchestrator so workers receive real ModelManager access.

Phase 11.5: exposes ``execution_summary()`` for richer post-run reporting.

Public API (unchanged from Phase 2/3):
    controller.plan(goal)          → ExecutionContext (READY, not executed)
    controller.receive_goal(goal)  → ExecutionContext (COMPLETED/FAILED)
    controller.run()               → ExecutionContext (execute current plan)
    controller.cancel()            → cancels current plan mid-run

New Phase 11.4 factory:
    ExecutiveController.with_agent(agent)  → pre-wired controller

Note on naming:
    ``smartagent.mind.executive.executive_controller.ExecutiveController``
    (Milestone 6) controls MARK's internal mental processes.
    This class is the *planning and task orchestration* controller.
    On ``SmartAgent``: ``agent.mind`` = Mind OS; ``agent.executive`` = this.
"""

from __future__ import annotations

from typing import Any, Optional

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
        model_manager: Any | None = None,
        memory_manager: Any | None = None,
        knowledge_manager: Any | None = None,
        settings: Any | None = None,
        tool_engine: Any | None = None,
        event_bus: Any | None = None,
        use_parallel: bool = False,
        max_workers: int = 4,
        show_progress: bool = True,
        reflection_engine: Any | None = None,
        workspace_manager: Any | None = None,
    ) -> None:
        self._worker_registry = worker_registry or build_default_registry()
        self._planner = planner or Planner()
        self._model_manager = model_manager
        self._memory_manager = memory_manager
        self._knowledge_manager = knowledge_manager
        self._settings = settings
        self._tool_engine = tool_engine
        self._event_bus = event_bus
        self._use_parallel = use_parallel
        self._max_workers = max_workers
        self._show_progress = show_progress
        self._reflection_engine = reflection_engine
        self._workspace_manager = workspace_manager

        if scheduler is not None:
            self._scheduler = scheduler
        elif use_parallel:
            from smartagent.executive.parallel_scheduler import ParallelScheduler
            _w = getattr(settings, "max_parallel_workers", max_workers) if settings else max_workers
            self._scheduler = ParallelScheduler(
                worker_registry=self._worker_registry,
                max_workers=_w,
                show_progress=show_progress,
            )
        else:
            self._scheduler = Scheduler(
                worker_registry=self._worker_registry,
                show_progress=show_progress,
            )

        self._orchestrator = Orchestrator(
            planner=self._planner,
            scheduler=self._scheduler,
            worker_registry=self._worker_registry,
            model_manager=model_manager,
            memory_manager=memory_manager,
            knowledge_manager=knowledge_manager,
            settings=settings,
            tool_engine=tool_engine,
            event_bus=event_bus,
            reflection_engine=reflection_engine,
            workspace_manager=workspace_manager,
        )
        self.current_context: Optional[ExecutionContext] = None

    # ------------------------------------------------------------------
    # Phase 11.4 factory
    # ------------------------------------------------------------------

    @classmethod
    def with_agent(cls, agent: Any) -> "ExecutiveController":
        """
        Create a fully-wired controller from a live SmartAgent instance.

        Extracts ModelManager, MemoryManager, KnowledgeManager, and Settings
        from *agent* (any that are missing are silently skipped).

        Usage::

            ctrl = ExecutiveController.with_agent(agent)
            ctx  = ctrl.receive_goal("Build a REST API for task management")
        """
        mm   = getattr(agent, "model_manager",    None)
        mem  = getattr(agent, "memory",            None)
        km   = getattr(agent, "knowledge",         None)
        cfg  = getattr(agent, "settings",          None)
        te   = getattr(agent, "tool_engine",       None)
        eb   = getattr(agent, "events",            None)
        re_  = getattr(agent, "reflection_engine",  None)
        wm   = getattr(agent, "workspace_manager",  None)
        return cls(
            model_manager=mm,
            memory_manager=mem,
            knowledge_manager=km,
            settings=cfg,
            tool_engine=te,
            event_bus=eb,
            reflection_engine=re_,
            workspace_manager=wm,
        )

    # ------------------------------------------------------------------
    # Primary API (unchanged from Phase 2/3)
    # ------------------------------------------------------------------

    def receive_goal(self, goal: str) -> ExecutionContext:
        """Full pipeline: plan + execute.  Returns the completed context."""
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

        Phase 11.4: injects AI services via the orchestrator's
        ``_inject_services`` before each task runs.

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

        # Inject services into the existing context before running
        self._orchestrator._inject_services(self.current_context)

        context = self._scheduler.run(self.current_context)
        self.current_context = context

        # Phase 11.5 — persist results if the run succeeded
        if context.state.value == "completed":
            self._orchestrator._save_to_memory(context)
            self._orchestrator._propose_to_knowledge(context)

        return context

    def cancel(self) -> bool:
        """
        Cancel the current plan.

        Returns ``True`` if there was a non-terminal plan to cancel,
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
    # Phase 11.5 — richer execution summary
    # ------------------------------------------------------------------

    def execution_summary(self) -> str:
        """
        Return a formatted execution summary for the current context.

        Includes per-task confidence scores, timing, and retry counts.
        Returns a help message if no context is available.
        """
        ctx = self.current_context
        if ctx is None:
            return "No execution context.  Run 'plan <goal>' then 'run'."

        lines: list[str] = [
            f"Execution: {ctx.goal}",
            f"  State   : {ctx.state.value}",
            f"  Tasks   : {ctx.completed_count}/{ctx.task_count} completed",
            "",
        ]

        timings     = ctx.metadata.get("task_timing", {})
        confidences = ctx.metadata.get("task_confidence", {})
        retries     = ctx.metadata.get("task_retries", {})

        for i, task in enumerate(ctx.task_graph.all_tasks(), 1):
            icon = "✓" if task.status.value == "completed" else "✗"
            t = timings.get(task.id, 0.0)
            c = confidences.get(task.id)
            r = retries.get(task.id, 0)

            conf_str   = f"  conf={c:.0%}" if c is not None else ""
            retry_str  = f"  retries={r}" if r > 0 else ""
            lines.append(
                f"  {i}. {icon}  {task.title}"
                f"  ({t:.1f}s{conf_str}{retry_str})"
            )

        scores = list(confidences.values())
        if scores:
            avg = sum(scores) / len(scores)
            lines.append(f"\n  Average confidence : {avg:.0%}")

        total = sum(timings.values())
        if total:
            lines.append(f"  Total time         : {total:.1f}s")

        return "\n".join(lines)

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
