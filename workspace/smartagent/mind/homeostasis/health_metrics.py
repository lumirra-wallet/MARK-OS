"""
HealthMetrics — the data behind Milestone 6, Part 8 (Homeostasis Engine).

A snapshot of everything the milestone brief asks MARK to continuously
monitor, plus a single deterministic scoring function so "health score" is
always a transparent function of these fields, never a magic number.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HealthMetrics:
    """
    One point-in-time health snapshot.

    Attributes:
        memory_usage: Fraction of some memory budget in use, 0.0-1.0
            (the caller decides what "budget" means — e.g. working-memory
            item count / capacity).
        running_modules: Count of currently active subsystems/processes.
        errors: Count of errors observed since the last reset.
        queue_length: Items currently waiting in the attention/task queue.
        task_load: Fraction of task capacity currently in use, 0.0-1.0.
        response_latency_ms: Most recent response latency, in milliseconds.
        model_availability: Whether a model provider is currently reachable/loaded.
        tool_availability: Fraction of registered tools that are enabled, 0.0-1.0.
        skill_availability: Fraction of registered skills that are available, 0.0-1.0.
    """

    memory_usage: float = 0.0
    running_modules: int = 0
    errors: int = 0
    queue_length: int = 0
    task_load: float = 0.0
    response_latency_ms: float = 0.0
    model_availability: bool = True
    tool_availability: float = 1.0
    skill_availability: float = 1.0

    def score(self) -> float:
        """
        Compute an overall health score in [0.0, 1.0].

        Deliberately simple and transparent: start at 1.0 and subtract
        weighted penalties for each unhealthy signal, clamped at 0.0. Not a
        learned model — a caller can always read the individual fields to
        see exactly why the score is what it is.
        """
        score = 1.0
        score -= 0.3 * self.memory_usage
        score -= 0.3 * self.task_load
        score -= min(0.3, 0.05 * self.errors)
        score -= min(0.2, 0.02 * self.queue_length)
        score -= 0.0 if self.response_latency_ms < 2000 else min(0.2, self.response_latency_ms / 20000)
        score -= 0.0 if self.model_availability else 0.2
        score -= 0.2 * (1.0 - self.tool_availability)
        score -= 0.2 * (1.0 - self.skill_availability)
        return max(0.0, min(1.0, score))
