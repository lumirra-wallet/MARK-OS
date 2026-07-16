"""
Critic — Milestone 14.

Evaluates an ``ExecutionReport`` and produces a ``CriticReport`` describing:
  - What succeeded and why
  - What failed and why
  - Missing knowledge / tools
  - Suggestions for a better plan
  - Per-worker prompt improvement hints

When a ``ModelManager`` is available the Critic uses the LLM for richer
analysis.  When not available (e.g. during tests) it falls back to
heuristic evaluation based on confidence scores and error messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.reflection.execution_analyzer import ExecutionReport

logger = get_logger(__name__)


@dataclass
class CriticReport:
    """
    Structured evaluation produced by ``Critic.evaluate()``.

    All list fields are non-empty strings suitable for direct display.
    ``prompt_hints`` maps ``worker_name → one-sentence improvement hint``.
    ``overall_score`` is 0.0 (poor) – 1.0 (excellent).
    """

    what_succeeded: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    missing_knowledge: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    plan_suggestions: list[str] = field(default_factory=list)
    prompt_hints: dict[str, str] = field(default_factory=dict)
    overall_score: float = 0.0
    summary: str = ""


class Critic:
    """
    Evaluates an ``ExecutionReport`` and produces a ``CriticReport``.

    Args:
        model_manager: Optional LLM access for richer evaluation.
            When ``None``, uses heuristic analysis only.
    """

    # Threshold below which a confidence score is considered low-quality
    _LOW_CONFIDENCE = 0.45
    # Threshold above which a result is considered high-quality
    _HIGH_CONFIDENCE = 0.70

    def __init__(self, model_manager: Any | None = None) -> None:
        self._model_manager = model_manager

    def evaluate(self, report: "ExecutionReport") -> CriticReport:
        """
        Evaluate *report* and return a ``CriticReport``.

        Uses heuristic analysis always (fast, deterministic, no LLM required).
        If a ``ModelManager`` is available, the heuristic report is enriched
        with LLM-generated prompt hints.
        """
        critic = self._heuristic_evaluate(report)
        if self._model_manager is not None:
            self._enrich_with_llm(report, critic)
        return critic

    # ------------------------------------------------------------------
    # Heuristic evaluation (no LLM required)
    # ------------------------------------------------------------------

    def _heuristic_evaluate(self, report: "ExecutionReport") -> CriticReport:
        succeeded: list[str] = []
        failed: list[str] = []
        missing_knowledge: list[str] = []
        missing_tools: list[str] = []
        plan_suggestions: list[str] = []
        prompt_hints: dict[str, str] = {}

        for rec in report.task_records:
            if rec.completed and rec.confidence >= self._HIGH_CONFIDENCE:
                succeeded.append(
                    f"{rec.task_type} task '{rec.title}' — confidence {rec.confidence:.0%}"
                )
            elif rec.completed and rec.confidence < self._LOW_CONFIDENCE:
                failed.append(
                    f"{rec.task_type} task '{rec.title}' completed with low confidence "
                    f"({rec.confidence:.0%}) — result may be shallow"
                )
                prompt_hints[rec.task_type] = (
                    f"Add more specific instructions and output requirements to "
                    f"produce deeper {rec.task_type} analysis."
                )
            elif not rec.completed:
                failed.append(
                    f"{rec.task_type} task '{rec.title}' failed: {rec.error or 'unknown error'}"
                )
                if rec.error:
                    if "tool" in rec.error.lower():
                        missing_tools.append(
                            f"A tool was needed but unavailable during '{rec.title}'"
                        )
                    elif "knowledge" in rec.error.lower() or "context" in rec.error.lower():
                        missing_knowledge.append(
                            f"Domain knowledge was missing for '{rec.title}'"
                        )

        # Plan-level suggestions
        if report.task_count <= 3 and report.success_rate < 1.0:
            plan_suggestions.append(
                "Consider adding more intermediate tasks to break down the goal further."
            )
        if report.failed_count > 0:
            plan_suggestions.append(
                "Add fallback tasks or alternative paths for failed task types."
            )
        if report.avg_confidence < self._LOW_CONFIDENCE:
            plan_suggestions.append(
                "Consider adding a dedicated Research task at the start to provide richer context."
            )
        if len(report.tool_call_records) == 0 and report.task_count > 3:
            missing_tools.append(
                "No tools were invoked — injecting tool_engine could improve result quality."
            )

        # Missing knowledge detection from low-confidence results
        if report.avg_confidence < self._LOW_CONFIDENCE:
            missing_knowledge.append(
                f"Overall confidence is low ({report.avg_confidence:.0%}) — "
                "the agent may lack domain-specific knowledge for this goal."
            )

        overall = self._score(report, succeeded, failed)

        summary = (
            f"Execution '{report.goal[:60]}' — {report.state}. "
            f"Score: {overall:.0%}. "
            f"{len(succeeded)} strong results, {len(failed)} weaknesses. "
            f"Avg confidence: {report.avg_confidence:.0%}."
        )

        return CriticReport(
            what_succeeded=succeeded or ["All tasks completed without errors."],
            what_failed=failed or ["No significant failures detected."],
            missing_knowledge=missing_knowledge,
            missing_tools=missing_tools,
            plan_suggestions=plan_suggestions,
            prompt_hints=prompt_hints,
            overall_score=overall,
            summary=summary,
        )

    def _score(self, report, succeeded, failed) -> float:
        """Compute a composite 0.0–1.0 quality score."""
        rate_score = report.success_rate
        conf_score = report.avg_confidence
        fail_penalty = min(0.5, len(failed) * 0.1)
        return max(0.0, min(1.0, (rate_score * 0.5 + conf_score * 0.5) - fail_penalty))

    # ------------------------------------------------------------------
    # LLM enrichment (best-effort, non-blocking)
    # ------------------------------------------------------------------

    def _enrich_with_llm(self, report: "ExecutionReport", critic: CriticReport) -> None:
        """
        Use the LLM to generate richer prompt improvement hints.

        Best-effort: any exception is logged and the critic is returned as-is.
        """
        try:
            task_summary = "\n".join(
                f"- [{r.task_type}] {r.title}: "
                f"{'✓' if r.completed else '✗'} "
                f"confidence={r.confidence:.0%}"
                for r in report.task_records
            )
            prompt = (
                f"Review this AI agent execution and suggest one-sentence "
                f"improvements for each task type's system prompt.\n\n"
                f"Goal: {report.goal}\n\n"
                f"Tasks:\n{task_summary}\n\n"
                f"For each task type that underperformed (confidence < 50%), "
                f"output exactly:\n"
                f"[task_type]: <one-sentence improvement>\n\n"
                f"If all tasks performed well, output: ALL_GOOD"
            )
            messages = [
                {"role": "system", "content": "You are a performance coach for AI agents. Be concise."},
                {"role": "user", "content": prompt},
            ]
            tokens = list(self._model_manager.chat_stream(messages))
            text = "".join(tokens).strip()

            if text and text != "ALL_GOOD":
                for line in text.splitlines():
                    if ":" in line and line.startswith("["):
                        bracket_end = line.find("]")
                        if bracket_end > 0:
                            worker_type = line[1:bracket_end].strip()
                            hint = line[bracket_end + 2:].strip()
                            if hint and worker_type not in critic.prompt_hints:
                                critic.prompt_hints[worker_type] = hint

        except Exception as exc:  # noqa: BLE001
            logger.debug("Critic: LLM enrichment skipped: %s", exc)
