"""
Orchestrator — Phase 11.4/11.5 upgrade.

Phase 11.4: accepts optional AI services (ModelManager, MemoryManager,
KnowledgeManager, Settings) and injects them into ExecutionContext.metadata
before running, so all workers can access them without modifying their
public interface.

Phase 11.5: after execution completes successfully, saves a summary to
MemoryManager and proposes a knowledge concept to KnowledgeManager.

All Phase 2/3 behaviour is unchanged: the public API, dependency ordering,
and context lifecycle are identical.
"""

from __future__ import annotations

from typing import Any, Optional

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
        planner:          Decomposes goals into task lists.
        scheduler:        Executes tasks in dependency order.
        worker_registry:  Maps task types to worker classes.
        model_manager:    (Phase 11.4) ModelManager for AI-powered workers.
        memory_manager:   (Phase 11.4) MemoryManager for context enrichment
                          and Phase 11.5 result persistence.
        knowledge_manager:(Phase 11.4) KnowledgeManager for knowledge context
                          and Phase 11.5 concept proposal.
        settings:         (Phase 11.4) Settings for model id resolution.
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
        reflection_engine: Any | None = None,
        workspace_manager: Any | None = None,
    ) -> None:
        self._planner = planner or Planner()
        self._worker_registry = worker_registry or build_default_registry()

        if scheduler is not None:
            self._scheduler = scheduler
        elif use_parallel:
            from smartagent.executive.parallel_scheduler import ParallelScheduler
            _w = max_workers
            if settings is not None:
                _w = getattr(settings, "max_parallel_workers", max_workers)
            self._scheduler = ParallelScheduler(
                worker_registry=self._worker_registry,
                max_workers=_w,
            )
        else:
            self._scheduler = Scheduler(worker_registry=self._worker_registry)

        # Phase 11.4 services — injected into ExecutionContext.metadata
        self._model_manager = model_manager
        self._memory_manager = memory_manager
        self._knowledge_manager = knowledge_manager
        self._settings = settings
        # Phase 12 services
        self._tool_engine = tool_engine
        self._event_bus = event_bus
        # Milestone 14 — reflection engine (optional)
        self._reflection_engine = reflection_engine
        # Milestone 15 — workspace manager (optional)
        self._workspace_manager = workspace_manager

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def execute_goal(self, goal: str) -> ExecutionContext:
        """
        Run the full pipeline for *goal* and return the completed context.

        Phase 11.4: injects AI services into the context before execution.
        Phase 11.5: saves results to memory/knowledge after completion.

        Steps:
            1. Create a plan (list of tasks) from the goal.
            2. Build a validated TaskGraph.
            3. Seed the TaskQueue with initially-ready tasks.
            4. Inject AI services into ExecutionContext.metadata.
            5. Run the Scheduler until all tasks complete or fail.
            6. Persist results to Memory and Knowledge (11.5).
        """
        context = ExecutionContext(goal=goal)
        context.transition_to(ExecutionState.PLANNING)
        logger.info("Orchestrator: planning goal=%r", goal)

        tasks = self._planner.create_plan(goal)
        logger.info("Orchestrator: plan has %d tasks", len(tasks))

        graph = self.build_task_graph(tasks)
        context.task_graph = graph
        context.task_queue = self.submit_to_queue(graph)
        context.transition_to(ExecutionState.READY)

        # Phase 11.4 — inject services so workers can use them
        self._inject_services(context)

        result = self._scheduler.run(context)

        # Phase 11.5 — persist results after successful execution
        if result.state == ExecutionState.COMPLETED:
            self._save_to_memory(result)
            self._propose_to_knowledge(result)
            # Milestone 14 — reflection and autonomous learning
            self._run_reflection(result)
            # Milestone 15 — record execution in the active workspace
            self._save_to_workspace(result)

        return result

    # ------------------------------------------------------------------
    # Sub-steps (used standalone by ExecutiveController for display)
    # ------------------------------------------------------------------

    def build_task_graph(self, tasks: list[Task]) -> TaskGraph:
        """
        Arrange *tasks* into a validated ``TaskGraph``.

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
        Create a ``TaskQueue`` seeded with the initially-ready tasks.
        """
        queue = TaskQueue()
        for task in graph.all_tasks():
            if task.status == TaskStatus.PENDING and not task.dependencies:
                task.mark_ready()
                queue.enqueue(task)
        logger.debug("Orchestrator: queue seeded with %d tasks", queue.size())
        return queue

    def preview_plan(self, goal: str) -> ExecutionContext:
        """
        Build and return a context in READY state WITHOUT executing it.

        Used by the ``plan`` console command.
        """
        context = ExecutionContext(goal=goal)
        context.transition_to(ExecutionState.PLANNING)
        tasks = self._planner.create_plan(goal)
        graph = self.build_task_graph(tasks)
        context.task_graph = graph
        context.task_queue = self.submit_to_queue(graph)
        context.transition_to(ExecutionState.READY)
        logger.info(
            "Orchestrator: preview plan built (%d tasks) for goal=%r",
            len(tasks), goal,
        )
        return context

    # ------------------------------------------------------------------
    # Phase 11.4 — service injection
    # ------------------------------------------------------------------

    def _inject_services(self, context: ExecutionContext) -> None:
        """
        Inject AI service references into context.metadata so workers can
        access them without the context needing new typed fields.
        """
        if self._model_manager is not None:
            context.metadata["model_manager"] = self._model_manager
        if self._memory_manager is not None:
            context.metadata["memory_manager"] = self._memory_manager
        if self._knowledge_manager is not None:
            context.metadata["knowledge_manager"] = self._knowledge_manager
        if self._settings is not None:
            context.metadata["settings"] = self._settings
        # Phase 12 — tool access
        if self._tool_engine is not None:
            context.metadata["tool_engine"] = self._tool_engine
        if self._event_bus is not None:
            context.metadata["event_bus"] = self._event_bus
        # Milestone 15: workspace injection — overrides global memory/knowledge
        # with workspace-scoped instances when a workspace is active.
        if self._workspace_manager is not None:
            ws = self._workspace_manager.active
            if ws is not None:
                context.metadata["workspace"] = ws
                scoped_mem = self._workspace_manager.active_memory()
                if scoped_mem is not None:
                    context.metadata["memory_manager"] = scoped_mem
                scoped_km = self._workspace_manager.active_knowledge()
                if scoped_km is not None:
                    context.metadata["knowledge_manager"] = scoped_km

        injected = [
            k for k in ("model_manager", "memory_manager", "knowledge_manager",
                        "settings", "tool_engine", "event_bus", "workspace")
            if context.metadata.get(k) is not None
        ]
        logger.info("Orchestrator: injected services: %s", injected)

    # ------------------------------------------------------------------
    # Phase 11.5 — result persistence
    # ------------------------------------------------------------------

    def _save_to_memory(self, context: ExecutionContext) -> None:
        """
        Persist an execution summary to MemoryManager after a successful run.

        Best-effort: errors are logged but never bubble up to the caller.
        """
        if self._memory_manager is None:
            return
        try:
            summary = self._build_result_summary(context)
            tags = [
                "executive",
                "goal-execution",
                context.goal[:30].strip().replace(" ", "-"),
            ]
            self._memory_manager.remember(
                content=summary,
                category="Projects",
                tags=tags,
            )
            logger.info("Orchestrator: execution results saved to memory")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Orchestrator: could not save to memory: %s", exc)

    def _propose_to_knowledge(self, context: ExecutionContext) -> None:
        """
        Propose a knowledge concept summarising what was learned during execution.

        Best-effort: errors are logged but never bubble up to the caller.
        """
        if self._knowledge_manager is None:
            return
        try:
            summary = self._build_result_summary(context)
            self._knowledge_manager.propose_concept(
                title=context.goal[:80],
                description=summary[:1000],
                category="Projects",
                tags=["executive", "goal-execution"],
            )
            logger.info("Orchestrator: proposed knowledge concept for goal")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Orchestrator: could not propose knowledge concept: %s", exc
            )

    def _run_reflection(self, context: ExecutionContext) -> None:
        """
        Milestone 14: run post-execution reflection using the ReflectionEngine.

        Best-effort: any failure is logged and never surfaces to callers.
        """
        reflection_engine = getattr(self, "_reflection_engine", None)
        if reflection_engine is None:
            return
        try:
            result = reflection_engine.reflect(context)
            context.metadata["last_reflection"] = result
            logger.info(
                "Orchestrator: reflection complete  score=%.0f%%  "
                "memory=%d  knowledge=%d  prompts=%d",
                result.critic.overall_score * 100,
                result.memory_entries_added,
                result.knowledge_proposals_added,
                result.prompt_versions_added,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Orchestrator: reflection failed: %s", exc)

    # ------------------------------------------------------------------
    # Milestone 15 — workspace persistence
    # ------------------------------------------------------------------

    def _save_to_workspace(self, context: ExecutionContext) -> None:
        """
        Record execution history in the active workspace.

        Writes a JSON history record, updates run_count and last_run_at,
        and appends reflection lessons to LESSONS.md.  Best-effort: any
        failure is logged and never surfaces to callers.
        """
        if self._workspace_manager is None:
            return
        ws = self._workspace_manager.active
        if ws is None:
            return
        try:
            reflection_result = context.metadata.get("last_reflection")
            self._workspace_manager.record_execution(
                context=context,
                reflection_result=reflection_result,
            )
            logger.info(
                "Orchestrator: execution recorded in workspace %r (run #%d)",
                ws.name, ws.run_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Orchestrator: could not save to workspace: %s", exc)

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def _build_result_summary(self, context: ExecutionContext) -> str:
        """
        Build a rich execution summary for memory/knowledge persistence.

        Includes: goal, state, task count, per-task results, confidence scores,
        and timing.
        """
        lines: list[str] = [
            f"# Executive Execution: {context.goal}",
            f"State: {context.state.value}  "
            f"Tasks: {context.completed_count}/{context.task_count}  "
            f"Plan: {context.plan_id[:8]}",
            "",
        ]

        timings = context.metadata.get("task_timing", {})
        confidences = context.metadata.get("task_confidence", {})

        for i, task in enumerate(context.task_graph.all_tasks(), 1):
            icon = "✓" if task.status.value == "completed" else "✗"
            t = timings.get(task.id, 0.0)
            c = confidences.get(task.id)
            conf_str = f" conf={c:.0%}" if c is not None else ""
            lines.append(
                f"{i}. {icon} [{task.task_type.value}] {task.title}"
                f"  ({t:.1f}s{conf_str})"
            )
            if task.result:
                # Include first 300 chars of each result in the memory entry
                preview = task.result[:300]
                if len(task.result) > 300:
                    preview += "\n…[truncated]"
                lines.append(f"   {preview}")
            if task.error:
                lines.append(f"   ERROR: {task.error}")
            lines.append("")

        avg = self._average_confidence(context)
        if avg is not None:
            lines.append(f"Average confidence: {avg:.0%}")

        total_time = sum(timings.values())
        lines.append(f"Total execution time: {total_time:.1f}s")

        return "\n".join(lines)

    def _average_confidence(self, context: ExecutionContext) -> float | None:
        """Return the mean confidence score across all tasks, or None."""
        scores = list(context.metadata.get("task_confidence", {}).values())
        return sum(scores) / len(scores) if scores else None
