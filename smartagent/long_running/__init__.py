"""
Long Running Execution — Milestone 23.

MARK can now work autonomously on a goal for an extended period, returning
a structured completion report instead of a single synchronous response.

Usage::

    from smartagent.long_running import LongRunningEngine

    engine = LongRunningEngine.with_agent(agent)
    result = engine.run("Build a SaaS backend with FastAPI")
    print("\\n".join(result.as_display_lines()))
"""

from smartagent.long_running.long_running_engine import LongRunningEngine
from smartagent.long_running.completion_report import CompletionReport, PhaseResult

__all__ = ["LongRunningEngine", "CompletionReport", "PhaseResult"]
