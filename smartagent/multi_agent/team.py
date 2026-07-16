"""
team.py — Team definitions and TeamRegistry for Milestone 17.

A ``Team`` is a named group of workers identified by the ``TaskType`` values
they specialise in.  The ``TeamRegistry`` holds all known teams and is the
single source of truth for team metadata.

Default teams
─────────────
research      RESEARCH, ANALYSIS, REPORT
engineering   PLANNING, DESIGN, ARCHITECTURE, CODING, IMPLEMENTATION, REVIEW
qa            TESTING, REVIEW
documentation DOCUMENTATION, REPORT

Custom teams can be registered at runtime via ``TeamRegistry.register()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from smartagent.executive.task import TaskType
from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Team:
    """
    A named team that handles a specific category of work.

    Attributes:
        name:          Short slug (lowercase, unique).  Used as a key.
        description:   One-sentence summary of what this team does.
        task_types:    The ``TaskType`` values workers in this team handle.
        goal_template: Python ``str.format`` template for building the
                       team-specific sub-goal from the CEO goal.
                       Receives one kwarg: ``{goal}``.
        lead:          Optional role label for the team lead (display only).
        emoji:         Optional emoji for console display.
    """

    name:          str
    description:   str
    task_types:    list[TaskType]
    goal_template: str = "{goal}"
    lead:          str = ""
    emoji:         str = ""

    def build_goal(self, ceo_goal: str) -> str:
        """Expand *ceo_goal* into this team's specialised sub-goal."""
        return self.goal_template.format(goal=ceo_goal)

    @property
    def task_type_names(self) -> list[str]:
        """Sorted list of task type string values."""
        return sorted(tt.value for tt in self.task_types)

    def __repr__(self) -> str:
        names = ", ".join(self.task_type_names)
        return f"Team({self.name!r}, types=[{names}])"


# ---------------------------------------------------------------------------
# Default team definitions
# ---------------------------------------------------------------------------

_DEFAULT_TEAMS: list[Team] = [
    Team(
        name="research",
        description="Gathers intelligence, analyses the domain, and synthesises findings.",
        task_types=[TaskType.RESEARCH, TaskType.ANALYSIS, TaskType.REPORT],
        goal_template=(
            "Research and analyse the following so the engineering team has "
            "everything they need to proceed: {goal}"
        ),
        lead="Lead Researcher",
        emoji="🔬",
    ),
    Team(
        name="engineering",
        description="Designs and implements the software solution end-to-end.",
        task_types=[
            TaskType.PLANNING,
            TaskType.DESIGN,
            TaskType.ARCHITECTURE,
            TaskType.CODING,
            TaskType.IMPLEMENTATION,
            TaskType.REVIEW,
        ],
        goal_template=(
            "Design, architect, and implement a complete working solution for: {goal}"
        ),
        lead="Tech Lead",
        emoji="⚙️",
    ),
    Team(
        name="qa",
        description="Verifies correctness, quality, edge cases, and reliability.",
        task_types=[TaskType.TESTING, TaskType.REVIEW],
        goal_template=(
            "Thoroughly test and validate the implementation of: {goal}. "
            "Write unit tests, identify edge cases, and produce a quality report."
        ),
        lead="QA Lead",
        emoji="✅",
    ),
    Team(
        name="documentation",
        description="Writes user-facing docs, READMEs, changelogs, and API references.",
        task_types=[TaskType.DOCUMENTATION, TaskType.REPORT],
        goal_template=(
            "Write comprehensive documentation for: {goal}. "
            "Include a README, usage examples, and API reference."
        ),
        lead="Docs Lead",
        emoji="📚",
    ),
]


# ---------------------------------------------------------------------------
# TeamRegistry
# ---------------------------------------------------------------------------

class TeamRegistry:
    """
    Registry of all known ``Team`` objects, keyed by name.

    Instantiated with the four built-in teams.  Custom teams can be added
    at runtime via ``register()``.
    """

    def __init__(self, teams: Sequence[Team] | None = None) -> None:
        self._teams: dict[str, Team] = {}
        for t in (_DEFAULT_TEAMS if teams is None else teams):
            self._teams[t.name] = t
        logger.debug(
            "TeamRegistry: initialised with %d teams: %s",
            len(self._teams), list(self._teams),
        )

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def register(self, team: Team) -> None:
        """Add or replace a team in the registry."""
        self._teams[team.name] = team
        logger.info("TeamRegistry: registered team %r", team.name)

    def unregister(self, name: str) -> None:
        """Remove a team.  No-op if *name* is not registered."""
        self._teams.pop(name, None)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> Team | None:
        """Return the team named *name*, or ``None``."""
        return self._teams.get(name)

    def has(self, name: str) -> bool:
        """Return True if a team named *name* is registered."""
        return name in self._teams

    def list_teams(self) -> list[Team]:
        """All registered teams, in insertion order."""
        return list(self._teams.values())

    def names(self) -> list[str]:
        """List of registered team names."""
        return list(self._teams.keys())

    def count(self) -> int:
        return len(self._teams)

    # ------------------------------------------------------------------
    # Task-type lookup
    # ------------------------------------------------------------------

    def teams_for_task_type(self, task_type: TaskType) -> list[Team]:
        """All teams that include *task_type* in their ``task_types``."""
        return [t for t in self._teams.values() if task_type in t.task_types]

    # ------------------------------------------------------------------
    # Filtered WorkerRegistry
    # ------------------------------------------------------------------

    def build_team_registry(self, name: str):
        """
        Build a ``WorkerRegistry`` restricted to the task types of team *name*.

        Returns the full default registry if *name* is unknown (safe fallback).
        """
        from smartagent.executive.worker_registry import WorkerRegistry, build_default_registry
        team = self.get(name)
        if team is None:
            logger.warning(
                "TeamRegistry.build_team_registry: team %r unknown, using full registry",
                name,
            )
            return build_default_registry()

        full = build_default_registry()
        filtered = WorkerRegistry()
        for tt in team.task_types:
            worker = full.get(tt)
            if worker is not None:
                filtered.register(tt, worker)
        # Always include GENERIC as a safety net
        from smartagent.executive.task import TaskType as TT
        generic = full.get(TT.GENERIC)
        if generic is not None:
            filtered.register(TT.GENERIC, generic)

        logger.debug(
            "TeamRegistry.build_team_registry: %r → %d worker mappings",
            name, filtered.count(),
        )
        return filtered

    def __repr__(self) -> str:
        return f"TeamRegistry(teams={self.names()})"
