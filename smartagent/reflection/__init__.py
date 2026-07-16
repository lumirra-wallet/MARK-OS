"""
smartagent.reflection — Milestone 14: Autonomous Learning & Self-Improvement.

After every completed execution MARK reviews its own performance, identifies
gaps, proposes knowledge concepts, and progressively improves its own worker
prompts.

Modules:
    execution_analyzer  — converts an ExecutionContext into a structured report
    critic              — heuristic + LLM evaluation of what worked / what didn't
    confidence_engine   — tracks per-worker and per-tool accuracy over time
    improvement_planner — turns critic output into concrete improvement actions
    prompt_registry     — versioned storage for evolving worker system prompts
    learning_store      — persists execution analytics and learning metrics
    reflection_engine   — orchestrates all of the above post-execution

All modules are best-effort: failures are logged and never surface to callers.
"""

from smartagent.reflection.execution_analyzer import ExecutionAnalyzer, ExecutionReport
from smartagent.reflection.critic import Critic, CriticReport
from smartagent.reflection.confidence_engine import ConfidenceEngine
from smartagent.reflection.improvement_planner import ImprovementPlanner, ImprovementPlan
from smartagent.reflection.prompt_registry import PromptRegistry, PromptVersion
from smartagent.reflection.learning_store import LearningStore, LearningRecord
from smartagent.reflection.reflection_engine import ReflectionEngine, ReflectionResult

__all__ = [
    "ExecutionAnalyzer",
    "ExecutionReport",
    "Critic",
    "CriticReport",
    "ConfidenceEngine",
    "ImprovementPlanner",
    "ImprovementPlan",
    "PromptRegistry",
    "PromptVersion",
    "LearningStore",
    "LearningRecord",
    "ReflectionEngine",
    "ReflectionResult",
]
