"""
KnowledgeWorker — Phase 11.4: Ollama-powered knowledge retrieval and analysis.

Queries MARK's knowledge graph for relevant concepts and enriches task
context with structured knowledge. Falls back gracefully when the knowledge
engine is unavailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class KnowledgeWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for knowledge retrieval, concept analysis, and context enrichment.

    Handles: ANALYSIS tasks.

    Phase 11.4: queries KnowledgeManager for relevant concepts and uses
    Ollama to produce structured analysis enriched with prior knowledge.
    """

    _system_prompt = """\
You are a knowledge analyst for MARK, an advanced AI assistant with a \
structured knowledge graph.

Your role: analyse the goal and task from a knowledge perspective. Surface \
relevant concepts, identify relationships, flag knowledge gaps, and produce \
a structured analysis that enriches the team's understanding.

Output format:
## Domain Analysis
Which knowledge domains does this goal touch? (e.g. distributed systems, \
NLP, data modelling)

## Key Concepts
Bullet list: concept name — one-line definition — why it matters here.

## Concept Relationships
How the key concepts relate to each other (use arrows: A → B means A \
depends on or informs B).

## Knowledge Gaps
What the team does not yet know that could affect the outcome.

## Analysis Conclusion
One paragraph: what the knowledge analysis reveals about how to approach \
this goal.

Rules:
- Prefer depth over breadth: 5 well-understood concepts > 15 surface-level ones.
- If MARK's knowledge base provides context, incorporate it explicitly.
- Flag uncertainties rather than asserting false confidence.\
"""

    _preferred_model = "default"

    @property
    def name(self) -> str:
        return "Knowledge Worker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.ANALYSIS]

    @property
    def description(self) -> str:
        return "Retrieves relevant knowledge concepts and enriches task context."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        return self._execute_with_ollama(task, context)
