"""
ExecutionAnalyzer — Milestone 14.

Converts a completed ``ExecutionContext`` into a structured ``ExecutionReport``
that the rest of the reflection pipeline can work with uniformly, without
needing direct access to the context internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext


@dataclass
class TaskRecord:
    """One task's performance record."""

    task_id: str
    title: str
    task_type: str
    result_preview: str           # first 300 chars of result
    error: str
    confidence: float
    timing: float
    completed: bool
    retry_count: int = 0


@dataclass
class ExecutionReport:
    """
    Structured summary of one execution run.

    This is the canonical input format for ``Critic``, ``ConfidenceEngine``,
    and ``LearningStore`` — they never read ``ExecutionContext`` directly.
    """

    goal: str
    plan_id: str
    state: str                    # "completed" | "failed" | "cancelled"
    timestamp: str
    task_count: int
    completed_count: int
    failed_count: int
    avg_confidence: float
    total_time: float             # sum of task timings
    success_rate: float           # completed / task_count
    task_records: list[TaskRecord] = field(default_factory=list)
    tool_call_records: list[dict] = field(default_factory=list)
    worker_names_used: list[str] = field(default_factory=list)
    tool_ids_used: list[str] = field(default_factory=list)


class ExecutionAnalyzer:
    """Converts an ``ExecutionContext`` into an ``ExecutionReport``."""

    def analyze(self, context: "ExecutionContext") -> ExecutionReport:
        """
        Build an ``ExecutionReport`` from a (possibly partial) context.

        Safe to call on failed or cancelled contexts.
        """
        timings     = context.metadata.get("task_timing", {})
        confidences = context.metadata.get("task_confidence", {})
        retries     = context.metadata.get("task_retries", {})
        tool_calls  = context.metadata.get("tool_calls", [])

        task_records: list[TaskRecord] = []
        worker_names: list[str] = []
        tool_ids: list[str] = []

        for task in context.task_graph.all_tasks():
            preview = ""
            if task.result:
                preview = task.result[:300]
                if len(task.result) > 300:
                    preview += "…"

            rec = TaskRecord(
                task_id=task.id,
                title=task.title,
                task_type=task.task_type.value,
                result_preview=preview,
                error=task.error or "",
                confidence=confidences.get(task.id, 0.0),
                timing=timings.get(task.id, 0.0),
                completed=task.status.value == "completed",
                retry_count=retries.get(task.id, 0),
            )
            task_records.append(rec)

        for tc in tool_calls:
            tool_id = tc.get("tool", "")
            if tool_id and tool_id not in tool_ids:
                tool_ids.append(tool_id)

        confidences_list = [r.confidence for r in task_records if r.completed]
        avg_conf = (
            sum(confidences_list) / len(confidences_list)
            if confidences_list else 0.0
        )
        total_time = sum(timings.values())
        task_count = context.task_count
        completed  = context.completed_count
        failed     = context.failed_count
        success_rate = completed / task_count if task_count > 0 else 0.0

        return ExecutionReport(
            goal=context.goal,
            plan_id=context.plan_id,
            state=context.state.value,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            task_count=task_count,
            completed_count=completed,
            failed_count=failed,
            avg_confidence=round(avg_conf, 3),
            total_time=round(total_time, 3),
            success_rate=round(success_rate, 3),
            task_records=task_records,
            tool_call_records=tool_calls,
            worker_names_used=worker_names,
            tool_ids_used=tool_ids,
        )
