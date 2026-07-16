"""
Project Memory — Milestone 22.

MARK remembers every project it works in: its frameworks, tools, test runners,
preferences, and notes.  Every future task in that project benefits from this
context automatically.

Public API::

    from smartagent.project_memory import ProjectMemory, ProjectProfile

    pm = ProjectMemory()
    profile = pm.load("my-fastapi-service", "/path/to/repo")
    pm.set(profile, "framework", "FastAPI")
    pm.set(profile, "test_runner", "pytest")
    print(pm.summary(profile))
"""

from smartagent.project_memory.project_memory import ProjectMemory
from smartagent.project_memory.project_profile import ProjectProfile

__all__ = ["ProjectMemory", "ProjectProfile"]
