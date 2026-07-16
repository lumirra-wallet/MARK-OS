"""
ConfidenceEngine — Milestone 14.

Tracks per-worker and per-tool performance across multiple execution runs.
Maintains a running weighted average so recent results have more influence
than old ones.

Stored as a plain dict in memory and persisted to MemoryManager when available.

Usage::

    engine = ConfidenceEngine()
    engine.update_from_report(report, critic)
    print(engine.worker_stats())       # {'Research Worker': {'runs': 5, ...}}
    print(engine.top_worker())         # 'Coding Worker'
    print(engine.reliability('file_read'))  # 0.87
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.reflection.critic import CriticReport
    from smartagent.reflection.execution_analyzer import ExecutionReport

logger = get_logger(__name__)

# Weight for the most recent run in the exponential moving average
_EMA_ALPHA = 0.3


@dataclass
class EntityStats:
    """Running statistics for one worker or tool."""

    entity: str
    entity_type: str          # "worker" | "tool"
    runs: int = 0
    successes: int = 0
    avg_confidence: float = 0.0
    success_rate: float = 0.0
    last_updated: str = ""

    def update(self, confidence: float, success: bool) -> None:
        """Update with a new observation using exponential moving average."""
        self.runs += 1
        if success:
            self.successes += 1

        self.success_rate = self.successes / self.runs
        # EMA for confidence
        if self.runs == 1:
            self.avg_confidence = confidence
        else:
            self.avg_confidence = (
                _EMA_ALPHA * confidence + (1 - _EMA_ALPHA) * self.avg_confidence
            )
        self.avg_confidence = round(self.avg_confidence, 3)
        self.success_rate = round(self.success_rate, 3)
        self.last_updated = datetime.now(timezone.utc).isoformat(timespec="seconds")


class ConfidenceEngine:
    """
    Tracks confidence and success rates for workers and tools across runs.
    """

    def __init__(self) -> None:
        self._workers: dict[str, EntityStats] = {}
        self._tools: dict[str, EntityStats] = {}

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def update_from_report(
        self,
        report: "ExecutionReport",
        critic: "CriticReport | None" = None,
    ) -> None:
        """Ingest all task and tool records from *report*."""
        for rec in report.task_records:
            worker_key = rec.task_type  # use task_type as worker proxy
            self._update_worker(worker_key, rec.confidence, rec.completed)

        for tc in report.tool_call_records:
            tool_id = tc.get("tool", "")
            success = tc.get("success", False)
            if tool_id:
                self._update_tool(tool_id, success)

    def _update_worker(self, name: str, confidence: float, success: bool) -> None:
        if name not in self._workers:
            self._workers[name] = EntityStats(entity=name, entity_type="worker")
        self._workers[name].update(confidence, success)

    def _update_tool(self, tool_id: str, success: bool) -> None:
        if tool_id not in self._tools:
            self._tools[tool_id] = EntityStats(entity=tool_id, entity_type="tool")
        # For tools, success IS confidence (binary)
        self._tools[tool_id].update(1.0 if success else 0.0, success)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def worker_stats(self) -> dict[str, dict]:
        return {
            name: {
                "runs": s.runs,
                "avg_confidence": s.avg_confidence,
                "success_rate": s.success_rate,
                "last_updated": s.last_updated,
            }
            for name, s in self._workers.items()
        }

    def tool_stats(self) -> dict[str, dict]:
        return {
            tid: {
                "calls": s.runs,
                "success_rate": s.success_rate,
                "last_updated": s.last_updated,
            }
            for tid, s in self._tools.items()
        }

    def top_worker(self) -> str | None:
        """Return the name of the best-performing worker, or None if no data."""
        if not self._workers:
            return None
        return max(
            self._workers,
            key=lambda n: self._workers[n].avg_confidence,
        )

    def worst_worker(self) -> str | None:
        """Return the name of the lowest-performing worker, or None."""
        if not self._workers:
            return None
        return min(
            self._workers,
            key=lambda n: self._workers[n].avg_confidence,
        )

    def reliability(self, tool_id: str) -> float:
        """Return the success rate for *tool_id* (0.0 if unknown)."""
        return self._tools[tool_id].success_rate if tool_id in self._tools else 0.0

    def most_unreliable_tool(self) -> str | None:
        """Return the tool with the lowest success rate, or None."""
        if not self._tools:
            return None
        return min(self._tools, key=lambda t: self._tools[t].success_rate)

    def summary_table(self) -> str:
        """Format all stats as a human-readable table."""
        lines: list[str] = []

        if self._workers:
            lines.append("Worker Performance")
            lines.append("-" * 52)
            lines.append(f"{'Worker':<22} {'Runs':>5} {'Avg Conf':>9} {'Success':>8}")
            lines.append("-" * 52)
            for name, s in sorted(self._workers.items()):
                lines.append(
                    f"{name:<22} {s.runs:>5} {s.avg_confidence:>8.0%} {s.success_rate:>7.0%}"
                )

        if self._tools:
            lines.append("")
            lines.append("Tool Reliability")
            lines.append("-" * 40)
            lines.append(f"{'Tool':<22} {'Calls':>6} {'Success':>8}")
            lines.append("-" * 40)
            for tid, s in sorted(self._tools.items()):
                lines.append(f"{tid:<22} {s.runs:>6} {s.success_rate:>7.0%}")

        return "\n".join(lines) if lines else "No performance data recorded yet."

    def serialize(self) -> dict:
        return {
            "workers": {n: vars(s) for n, s in self._workers.items()},
            "tools": {t: vars(s) for t, s in self._tools.items()},
        }

    def load(self, data: dict) -> None:
        for name, d in data.get("workers", {}).items():
            s = EntityStats(**d)
            self._workers[name] = s
        for tid, d in data.get("tools", {}).items():
            s = EntityStats(**d)
            self._tools[tid] = s
