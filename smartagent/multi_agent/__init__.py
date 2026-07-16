"""
smartagent.multi_agent — Milestone 17: Multi-Agent Collaboration.

Provides a hierarchical multi-agent architecture where a ``CEOAgent``
decomposes a high-level goal into team assignments, each team runs its own
``Orchestrator`` scoped to its specialist workers, and results are chained
sequentially so later teams build on earlier teams' output.

Architecture::

    CEOAgent
      └─ TeamPlanner → MultiAgentPlan
      └─ TeamRunner (research)      → TeamResult
      └─ TeamRunner (engineering)   → TeamResult  ← receives research output
      └─ TeamRunner (qa)            → TeamResult  ← receives engineering output
      └─ TeamRunner (documentation) → TeamResult  ← receives qa output
      └─ MultiAgentResult

Default teams
─────────────
research      RESEARCH, ANALYSIS, REPORT
engineering   PLANNING, DESIGN, ARCHITECTURE, CODING, IMPLEMENTATION, REVIEW
qa            TESTING, REVIEW
documentation DOCUMENTATION, REPORT

Quick start::

    from smartagent.multi_agent import CEOAgent

    ceo = CEOAgent.with_agent(agent)
    result = ceo.execute("Build a FastAPI weather service")
    for line in result.as_display_lines():
        print(line)
"""

from smartagent.multi_agent.ceo_agent import CEOAgent
from smartagent.multi_agent.team import Team, TeamRegistry
from smartagent.multi_agent.team_assignment import MultiAgentPlan, TeamAssignment
from smartagent.multi_agent.team_planner import TeamPlanner
from smartagent.multi_agent.team_result import MultiAgentResult, TeamResult
from smartagent.multi_agent.team_runner import TeamRunner

__all__ = [
    "CEOAgent",
    "MultiAgentPlan",
    "MultiAgentResult",
    "Team",
    "TeamAssignment",
    "TeamPlanner",
    "TeamRegistry",
    "TeamResult",
    "TeamRunner",
]
