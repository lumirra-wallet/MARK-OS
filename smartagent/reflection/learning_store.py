"""
LearningStore — Milestone 14: persistent analytics for autonomous learning.

Tracks every execution run in a structured record list and provides
aggregated analytics: success rate, average confidence trends, knowledge
growth, worker accuracy, tool reliability.

Persistence strategy:
  - In-memory list during a session.
  - If a ``MemoryManager`` is supplied, each record is also saved to the
    vault under category "LearningAnalytics" for cross-session recall.
  - The ``ConfidenceEngine`` is a sub-component updated after each run.

Access via the console::

    learning   — overview dashboard
    analytics  — detailed table
    history    — list of past executions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from smartagent.logs.logger import get_logger
from smartagent.reflection.confidence_engine import ConfidenceEngine

if TYPE_CHECKING:
    from smartagent.reflection.critic import CriticReport
    from smartagent.reflection.execution_analyzer import ExecutionReport

logger = get_logger(__name__)


@dataclass
class LearningRecord:
    """Analytics record for one completed execution."""

    goal: str
    plan_id: str
    timestamp: str
    state: str
    task_count: int
    completed_count: int
    failed_count: int
    avg_confidence: float
    total_time: float
    tool_calls_count: int
    knowledge_proposals: int = 0
    reflection_done: bool = False
    overall_score: float = 0.0


class LearningStore:
    """
    Accumulates learning records and produces analytics reports.

    Args:
        memory_manager: Optional MemoryManager for cross-session persistence.
    """

    def __init__(self, memory_manager: Any | None = None) -> None:
        self._memory_manager = memory_manager
        self._records: list[LearningRecord] = []
        self._confidence_engine = ConfidenceEngine()
        self._knowledge_proposals_total: int = 0

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_execution(
        self,
        report: "ExecutionReport",
        critic_report: "CriticReport | None" = None,
        knowledge_proposals: int = 0,
        reflection_done: bool = False,
    ) -> LearningRecord:
        """Add a new ``LearningRecord`` from *report*."""
        score = critic_report.overall_score if critic_report else report.success_rate

        rec = LearningRecord(
            goal=report.goal,
            plan_id=report.plan_id,
            timestamp=report.timestamp,
            state=report.state,
            task_count=report.task_count,
            completed_count=report.completed_count,
            failed_count=report.failed_count,
            avg_confidence=report.avg_confidence,
            total_time=report.total_time,
            tool_calls_count=len(report.tool_call_records),
            knowledge_proposals=knowledge_proposals,
            reflection_done=reflection_done,
            overall_score=score,
        )
        self._records.append(rec)
        self._knowledge_proposals_total += knowledge_proposals

        # Update confidence engine
        self._confidence_engine.update_from_report(report, critic_report)

        # Persist to memory if available
        self._persist_record(rec)
        return rec

    def _persist_record(self, rec: LearningRecord) -> None:
        if self._memory_manager is None:
            return
        try:
            content = (
                f"# Learning Record: {rec.goal[:60]}\n"
                f"- State: {rec.state}\n"
                f"- Tasks: {rec.completed_count}/{rec.task_count}\n"
                f"- Avg confidence: {rec.avg_confidence:.0%}\n"
                f"- Score: {rec.overall_score:.0%}\n"
                f"- Tool calls: {rec.tool_calls_count}\n"
                f"- Time: {rec.total_time:.1f}s\n"
            )
            self._memory_manager.remember(
                content=content,
                category="LearningAnalytics",
                tags=["learning", "analytics", "executive"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LearningStore: could not persist record: %s", exc)

    # ------------------------------------------------------------------
    # Analytics queries
    # ------------------------------------------------------------------

    def execution_history(self) -> list[LearningRecord]:
        """All records in chronological order."""
        return list(self._records)

    def success_rate(self) -> float:
        """Fraction of executions that completed successfully."""
        if not self._records:
            return 0.0
        return sum(1 for r in self._records if r.state == "completed") / len(self._records)

    def average_confidence(self) -> float:
        """Mean confidence across all recorded runs."""
        if not self._records:
            return 0.0
        return sum(r.avg_confidence for r in self._records) / len(self._records)

    def knowledge_proposals_count(self) -> int:
        return self._knowledge_proposals_total

    def worker_stats(self) -> dict[str, dict]:
        return self._confidence_engine.worker_stats()

    def tool_stats(self) -> dict[str, dict]:
        return self._confidence_engine.tool_stats()

    def top_worker(self) -> str | None:
        return self._confidence_engine.top_worker()

    def most_unreliable_tool(self) -> str | None:
        return self._confidence_engine.most_unreliable_tool()

    def confidence_trend(self) -> str:
        """Describe whether confidence is improving, stable, or declining."""
        if len(self._records) < 3:
            return "insufficient data"
        recent = [r.avg_confidence for r in self._records[-5:]]
        delta = recent[-1] - recent[0]
        if delta > 0.05:
            return f"improving (+{delta:.0%})"
        if delta < -0.05:
            return f"declining ({delta:.0%})"
        return "stable"

    # ------------------------------------------------------------------
    # Formatted reports
    # ------------------------------------------------------------------

    def analytics_summary(self) -> str:
        """Dashboard overview for the ``analytics`` console command."""
        n = len(self._records)
        if n == 0:
            return "No executions recorded yet.  Run 'plan <goal>  run' to start learning."

        lines = [
            "╔══ MARK Learning Analytics ══════════════════════╗",
            f"  Executions        : {n}",
            f"  Success Rate      : {self.success_rate():.0%}",
            f"  Avg Confidence    : {self.average_confidence():.0%}",
            f"  Knowledge Proposals: {self._knowledge_proposals_total}",
            f"  Confidence Trend  : {self.confidence_trend()}",
        ]

        top = self.top_worker()
        if top:
            stats = self._confidence_engine.worker_stats().get(top, {})
            lines.append(
                f"  Best Worker       : {top} ({stats.get('avg_confidence', 0):.0%} conf)"
            )

        bad_tool = self.most_unreliable_tool()
        if bad_tool:
            rate = self._confidence_engine.reliability(bad_tool)
            lines.append(
                f"  Most Unreliable Tool: {bad_tool} ({rate:.0%} success)"
            )

        lines.append("╚════════════════════════════════════════════════╝")
        return "\n".join(lines)

    def format_history_table(self, limit: int = 10) -> str:
        """Table of recent executions for the ``history`` console command."""
        records = self._records[-limit:]
        if not records:
            return "No execution history yet."

        lines = [
            f"{'#':<4} {'State':<12} {'Tasks':>6} {'Conf':>6} {'Score':>6}  Goal",
            "-" * 72,
        ]
        for i, rec in enumerate(reversed(records), 1):
            goal_short = rec.goal[:40] + ("…" if len(rec.goal) > 40 else "")
            lines.append(
                f"{i:<4} {rec.state:<12} "
                f"{rec.completed_count}/{rec.task_count:>3}  "
                f"{rec.avg_confidence:>5.0%}  "
                f"{rec.overall_score:>5.0%}  {goal_short}"
            )
        return "\n".join(lines)

    def format_worker_analytics(self) -> str:
        """Detailed worker stats table for the ``analytics`` command."""
        return self._confidence_engine.summary_table()

    def self_evaluation(self) -> str:
        """
        MARK's structured self-assessment — answers the questions from the spec:
          What did I learn? Best worker? Failing tools? Missing knowledge?
        """
        n = len(self._records)
        if n == 0:
            return "I have not completed any executions yet — nothing to evaluate."

        top = self.top_worker()
        bad_tool = self.most_unreliable_tool()
        trend = self.confidence_trend()

        lines = [
            "## MARK Self-Evaluation",
            "",
            f"I have completed {n} execution(s) with a {self.success_rate():.0%} success rate.",
            f"My average output confidence is {self.average_confidence():.0%} and {trend}.",
            "",
        ]

        if top:
            lines.append(f"**Best performing worker**: {top}")
        if bad_tool:
            lines.append(f"**Most unreliable tool**: {bad_tool}")
        if self._knowledge_proposals_total > 0:
            lines.append(
                f"**Knowledge growth**: {self._knowledge_proposals_total} concepts proposed."
            )

        # Recent learning from last execution
        if self._records:
            last = self._records[-1]
            lines += [
                "",
                f"**Most recent execution**: '{last.goal[:50]}'",
                f"  → {last.state} | confidence: {last.avg_confidence:.0%} | "
                f"score: {last.overall_score:.0%}",
            ]

        return "\n".join(lines)
