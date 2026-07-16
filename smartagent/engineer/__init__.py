"""
Full Software Engineer — Milestone 25.

MARK becomes a professional coding agent: it analyzes requirements, asks
only the necessary clarifications, divides into teams, writes code, runs
tests, fixes bugs, documents the project, commits changes, and summarizes
the results.

Usage::

    from smartagent.engineer import SoftwareEngineer

    eng = SoftwareEngineer.with_agent(agent)
    report = eng.build("Build me a Trello clone")
    print("\\n".join(report.as_display_lines()))
"""

from smartagent.engineer.software_engineer import SoftwareEngineer
from smartagent.engineer.requirement_analyzer import RequirementAnalyzer, RequirementReport
from smartagent.engineer.clarification_engine import ClarificationEngine, ClarificationSet

__all__ = [
    "SoftwareEngineer",
    "RequirementAnalyzer", "RequirementReport",
    "ClarificationEngine", "ClarificationSet",
]
