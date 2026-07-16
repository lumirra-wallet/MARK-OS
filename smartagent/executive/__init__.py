"""
smartagent.executive — MARK Executive Framework (Milestone 11, Phase 1)

The Executive package gives MARK an "executive brain": a goal-driven
orchestration layer that decomposes goals into task plans, manages a
dependency-aware task graph, queues tasks for execution, and runs them
through a scheduler.

Architecture:

    User goal
        ↓
    ExecutiveController.receive_goal()
        ↓
    Planner.create_plan()          — rule-based decomposition (Phase 1)
        ↓
    build_task_graph()             — DAG with dependency edges
        ↓
    submit_to_queue()              — ready tasks → TaskQueue
        ↓
    Scheduler.run()                — executes in dependency order
        ↓
    ExecutionContext               — carries results back to caller

Phase 1 establishes the framework.
Phase 2 wires worker agents.
Phase 4 connects workers to the Ollama model.
"""

from smartagent.executive.task import Task, TaskStatus, TaskType
from smartagent.executive.task_graph import TaskGraph
from smartagent.executive.task_queue import TaskQueue
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.execution_context import ExecutionContext
from smartagent.executive.worker_registry import WorkerRegistry
from smartagent.executive.planner import Planner
from smartagent.executive.scheduler import Scheduler
from smartagent.executive.orchestrator import Orchestrator
from smartagent.executive.executive_controller import ExecutiveController

__all__ = [
    "Task",
    "TaskStatus",
    "TaskType",
    "TaskGraph",
    "TaskQueue",
    "ExecutionState",
    "ExecutionContext",
    "WorkerRegistry",
    "Planner",
    "Scheduler",
    "Orchestrator",
    "ExecutiveController",
]
