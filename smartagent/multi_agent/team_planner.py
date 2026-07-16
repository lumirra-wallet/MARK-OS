"""
team_planner.py — Decomposes a CEO goal into per-team assignments (Milestone 17).

``TeamPlanner`` is rule-based by default — no LLM required.  When a
``model_manager`` is supplied and the ``use_ai`` flag is set, it can ask an
LLM to produce a richer decomposition (gracefully falling back to rules on any
failure).

Rule-based selection
────────────────────
The planner scores each registered team by counting keyword matches in the goal
text.  Teams that exceed a score threshold are included.  When no keywords match
(or only one team would be selected), it falls back to the full default pipeline:
research → engineering → qa → documentation.

Teams are always ordered by dependency: research before engineering, engineering
before qa, qa before documentation.  Custom teams inserted via the registry
are appended after the four defaults.
"""

from __future__ import annotations

from typing import Any, Sequence

from smartagent.logs.logger import get_logger
from smartagent.multi_agent.team import Team, TeamRegistry
from smartagent.multi_agent.team_assignment import MultiAgentPlan, TeamAssignment

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Keyword → team mapping
# ---------------------------------------------------------------------------

_TEAM_KEYWORDS: dict[str, list[str]] = {
    "research": [
        "research", "analyse", "analyze", "investigate", "explore", "study",
        "survey", "review", "compare", "benchmark", "findings", "report",
        "literature", "state of the art", "best practice", "landscape",
    ],
    "engineering": [
        "build", "create", "implement", "develop", "code", "program", "write",
        "design", "architecture", "scaffold", "refactor", "add feature",
        "api", "service", "server", "backend", "frontend", "cli", "library",
        "module", "class", "function", "database", "schema", "endpoint",
    ],
    "qa": [
        "test", "qa", "quality", "validate", "verify", "check", "bug",
        "regression", "coverage", "edge case", "assert", "pytest", "spec",
    ],
    "documentation": [
        "document", "docs", "readme", "changelog", "api reference", "guide",
        "tutorial", "how-to", "write up", "explain", "description", "comment",
        "docstring",
    ],
}

# Default ordered pipeline when goal is general-purpose
_DEFAULT_PIPELINE: list[str] = ["research", "engineering", "qa", "documentation"]

# Score threshold: at least this many keyword hits for a team to be auto-selected
_KEYWORD_THRESHOLD = 1


class TeamPlanner:
    """
    Decomposes a high-level CEO goal into a ``MultiAgentPlan``.

    Args:
        team_registry:  Source of available teams.  Defaults to the standard
                        four-team registry.
        model_manager:  Optional — used for AI-assisted decomposition when
                        ``use_ai=True``.
        use_ai:         If True and *model_manager* is available, try asking an
                        LLM for a richer plan (falls back to rule-based on error).
        min_teams:      Minimum number of teams to include even if keywords don't
                        fire.  Defaults to 2.
    """

    def __init__(
        self,
        team_registry: TeamRegistry | None = None,
        model_manager: Any | None = None,
        use_ai: bool = False,
        min_teams: int = 2,
    ) -> None:
        self._team_registry = team_registry or TeamRegistry()
        self._model_manager = model_manager
        self._use_ai = use_ai
        self._min_teams = min_teams

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(self, goal: str) -> MultiAgentPlan:
        """
        Build a ``MultiAgentPlan`` for *goal*.

        Tries AI decomposition first if enabled; falls back to rule-based.
        """
        if self._use_ai and self._model_manager is not None:
            try:
                return self._plan_with_ai(goal)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "TeamPlanner: AI decomposition failed (%s), using rule-based.", exc
                )
        return self._plan_rule_based(goal)

    # ------------------------------------------------------------------
    # Rule-based decomposition (no LLM)
    # ------------------------------------------------------------------

    def _plan_rule_based(self, goal: str) -> MultiAgentPlan:
        goal_lower = goal.lower()
        scores = self._score_teams(goal_lower)
        selected = [
            name for name, score in scores.items() if score >= _KEYWORD_THRESHOLD
        ]
        # Fall back to default pipeline if too few teams were selected
        if len(selected) < self._min_teams:
            selected = _DEFAULT_PIPELINE[:]

        # Keep only teams that are registered; preserve default order
        ordered = self._order_teams(selected)
        assignments = self._build_assignments(goal, ordered)
        plan = MultiAgentPlan(goal=goal, assignments=assignments, model="rule-based")
        logger.info(
            "TeamPlanner.rule_based: goal=%r → teams=%s",
            goal[:60], [a.team_name for a in assignments],
        )
        return plan

    def _score_teams(self, goal_lower: str) -> dict[str, int]:
        """Count keyword hits per team."""
        scores: dict[str, int] = {n: 0 for n in self._team_registry.names()}
        for team_name, keywords in _TEAM_KEYWORDS.items():
            if team_name not in scores:
                continue
            scores[team_name] = sum(1 for kw in keywords if kw in goal_lower)
        return scores

    def _order_teams(self, selected: Sequence[str]) -> list[str]:
        """
        Return *selected* teams in canonical execution order.

        Default pipeline order is preserved for the four built-in teams;
        custom teams are appended alphabetically at the end.
        """
        canonical = [n for n in _DEFAULT_PIPELINE if n in selected]
        custom    = sorted(n for n in selected if n not in _DEFAULT_PIPELINE
                           and self._team_registry.has(n))
        return canonical + custom

    def _build_assignments(self, goal: str, ordered_names: list[str]) -> list[TeamAssignment]:
        """Build one TeamAssignment per team name, with dependency chaining."""
        assignments: list[TeamAssignment] = []
        prev_names: list[str] = []
        for i, name in enumerate(ordered_names):
            team = self._team_registry.get(name)
            if team is None:
                logger.warning("TeamPlanner: team %r not in registry — skipping", name)
                continue
            sub_goal = team.build_goal(goal)
            assignment = TeamAssignment(
                team_name=name,
                goal=sub_goal,
                priority=i,
                dependencies=prev_names[:],  # each team depends on all prior
            )
            assignments.append(assignment)
            prev_names.append(name)
        return assignments

    # ------------------------------------------------------------------
    # AI-assisted decomposition (optional)
    # ------------------------------------------------------------------

    def _plan_with_ai(self, goal: str) -> MultiAgentPlan:
        """
        Ask the model_manager for a structured decomposition.

        Expects the model to return one JSON object per line with keys:
          ``team``, ``goal``, ``context`` (optional).
        Falls back to rule-based if the response cannot be parsed.
        """
        import json

        team_names = ", ".join(self._team_registry.names())
        prompt = (
            f"You are a CEO agent.  Decompose the following goal into sub-goals "
            f"for a team of specialist AI agents.  Available teams: {team_names}.\n"
            f"Goal: {goal}\n\n"
            f"Reply with one JSON object per line, each with keys: "
            f"\"team\" (string), \"goal\" (string), \"context\" (optional string).\n"
            f"Include only the teams that are genuinely needed.  "
            f"Order teams so that later ones can build on earlier ones."
        )
        response = self._model_manager.chat(prompt)
        text = getattr(response, "message", str(response))
        assignments: list[TeamAssignment] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj  = json.loads(line)
                name = obj.get("team", "").lower()
                if not self._team_registry.has(name):
                    continue
                assignments.append(TeamAssignment(
                    team_name=name,
                    goal=obj.get("goal", goal),
                    context=obj.get("context", ""),
                    priority=len(assignments),
                ))
            except (json.JSONDecodeError, TypeError):
                continue

        if not assignments:
            raise ValueError("AI returned no parseable team assignments")

        plan = MultiAgentPlan(goal=goal, assignments=assignments, model="ai")
        logger.info(
            "TeamPlanner.ai: goal=%r → teams=%s",
            goal[:60], [a.team_name for a in assignments],
        )
        return plan
