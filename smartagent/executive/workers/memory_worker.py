"""
MemoryWorker — Phase 11.4: memory persistence and retrieval specialist.

Reads from and writes to MARK's memory vault. In Phase 11.5 this worker
is also responsible for persisting key execution findings for future recall.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.executive.task import TaskType
from smartagent.executive.workers.base_worker import BaseWorker, WorkerResult
from smartagent.executive.workers.ollama_mixin import OllamaWorkerMixin

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task


class MemoryWorker(OllamaWorkerMixin, BaseWorker):
    """
    Specialist for memory operations — storing and retrieving past results.

    Handles: no specific TaskType alone; invoked explicitly by the Orchestrator
    for Phase 11.5 post-execution persistence.

    Phase 11.4: uses Ollama to extract the most important findings from
    all prior steps and format them for long-term memory storage.
    Also persists the result if MemoryManager is available.
    """

    _system_prompt = """\
You are a memory specialist for MARK, an advanced AI assistant with \
persistent memory.

Your role: extract the most important, durable facts and decisions from \
the team's prior work and format them for long-term memory storage. \
Memory entries should be useful months from now.

Output format:
## Memory Entry: Key Findings

A bulleted list of the 5-10 most important things learned during this task:
- Each bullet is a single, self-contained fact or decision
- Include enough context to understand the bullet without reading the \
original work
- Mark high-confidence findings with [✓] and uncertain ones with [?]

## Memory Entry: Decision Log

List of key decisions made and their rationale:
- Decision: [what was decided]
  Rationale: [why]

## Tags
Comma-separated keywords for retrieval: domain, technologies, patterns used.

Rules:
- Prioritise decisions and findings that are likely to recur in future goals.
- Do NOT include implementation details that would be outdated quickly.
- Write in third person (MARK learned..., The team decided...).\
"""

    _preferred_model = "default"

    @property
    def name(self) -> str:
        return "Memory Worker"

    @property
    def task_types(self) -> list[TaskType]:
        # Memory operations are cross-cutting; invoked explicitly.
        return []

    @property
    def description(self) -> str:
        return "Persists key findings to MARK's memory vault for future recall."

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        """
        Execute with Ollama, then persist the result to MemoryManager.

        The persistence step is best-effort — if MemoryManager is unavailable
        the Ollama output is still returned.
        """
        result = self._execute_with_ollama(task, context)
        self._persist_to_memory(str(result), task, context)
        return result

    def _persist_to_memory(
        self,
        content: str,
        task: "Task",
        context: "ExecutionContext",
    ) -> None:
        """Save the memory entry to the MemoryManager vault (Phase 11.5)."""
        mm = self._get_memory_manager(context)
        if mm is None:
            return
        try:
            tags = [
                "executive",
                "goal",
                context.goal[:40].replace(" ", "-"),
            ]
            mm.remember(
                content=f"# Executive Run: {context.goal}\n\n{content}",
                category="Projects",
                tags=tags,
            )
        except Exception as exc:
            from smartagent.logs.logger import get_logger
            get_logger(__name__).warning(
                "MemoryWorker: could not persist to memory: %s", exc
            )
