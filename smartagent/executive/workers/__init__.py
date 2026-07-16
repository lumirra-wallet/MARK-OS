"""
smartagent.executive.workers — Specialist worker agents (Milestone 11, Phase 2).

Each worker handles one or more ``TaskType`` categories and implements::

    execute(task: Task, context: ExecutionContext) -> str

Phase 2: workers are stubs — they return a formatted "Completed" string
and record their output in the ``ExecutionContext``.

Phase 4: each worker gains a system prompt and calls
``ModelManager.generate_stream()`` / ``chat_stream()`` via the agent's
``model_manager``, turning the stub into a real AI-powered specialist.

Worker registration is centralised in ``build_default_registry()``
(in ``smartagent.executive.worker_registry``) so the ``WorkerRegistry``
always maps every ``TaskType`` to the right class.
"""

from smartagent.executive.workers.base_worker import BaseWorker, WorkerResult
from smartagent.executive.workers.research_worker import ResearchWorker
from smartagent.executive.workers.planning_worker import PlanningWorker
from smartagent.executive.workers.design_worker import DesignWorker
from smartagent.executive.workers.coding_worker import CodingWorker
from smartagent.executive.workers.testing_worker import TestingWorker
from smartagent.executive.workers.review_worker import ReviewWorker
from smartagent.executive.workers.documentation_worker import DocumentationWorker
from smartagent.executive.workers.report_worker import ReportWorker
from smartagent.executive.workers.memory_worker import MemoryWorker
from smartagent.executive.workers.knowledge_worker import KnowledgeWorker

__all__ = [
    "BaseWorker",
    "WorkerResult",
    "ResearchWorker",
    "PlanningWorker",
    "DesignWorker",
    "CodingWorker",
    "TestingWorker",
    "ReviewWorker",
    "DocumentationWorker",
    "ReportWorker",
    "MemoryWorker",
    "KnowledgeWorker",
]
