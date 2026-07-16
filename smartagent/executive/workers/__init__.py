"""
smartagent.executive.workers — Specialist worker agents (Milestone 11, Phases 4–5).

Each worker handles one or more ``TaskType`` categories and implements::

    execute(task: Task, context: ExecutionContext) -> str | WorkerResult

Phase 4 (11.4): workers are powered by Ollama via ``OllamaWorkerMixin``.
Each worker has a specialist system prompt and streams responses from the
configured model.  Workers gracefully fall back to a stub result when
Ollama is unavailable (e.g. during unit tests).

Phase 5 (11.5): workers read prior task outputs for collaborative refinement,
produce confidence-scored results, and support auto-retry on failure.

Services are injected into ``ExecutionContext.metadata`` by the Orchestrator:
  - ``model_manager``   — ModelManager for AI generation
  - ``memory_manager``  — MemoryManager for context + persistence
  - ``knowledge_manager`` — KnowledgeManager for concept enrichment
  - ``settings``        — Settings for model id resolution

Worker registration is centralised in ``build_default_registry()``
(in ``smartagent.executive.worker_registry``) so the ``WorkerRegistry``
always maps every ``TaskType`` to the right class.
"""

from smartagent.executive.workers.base_worker import BaseWorker, WorkerResult
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin
from smartagent.executive.workers.tool_mixin import WorkerToolMixin
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
    "OllamaWorkerMixin",
    "WorkerToolMixin",
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
