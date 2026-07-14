"""PlanningSkill — tracks and reports goals via `GoalManager`."""

from __future__ import annotations

from smartagent.planning.goal_manager import Goal
from smartagent.skills.base_skill import BaseSkill, SkillCategory, SkillContext

_ADD_PREFIXES = ("add goal:", "new goal:", "set goal:")
_LIST_KEYWORDS = ("goal", "roadmap", "task list", "to-do", "todo")


class PlanningSkill(BaseSkill):
    """Adds a goal, or reports currently tracked goals, using `SkillContext.goals`."""

    @property
    def name(self) -> str:
        return "planning_skill"

    @property
    def description(self) -> str:
        return "Adds a new goal or lists currently tracked goals."

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def author(self) -> str:
        return "SmartAgent Core Team"

    @property
    def required_modules(self) -> tuple[str, ...]:
        return ("planning",)

    @property
    def category(self) -> SkillCategory:
        return SkillCategory.PLANNING

    @property
    def confidence(self) -> float:
        return 0.7

    def validate(self, message: str) -> bool:
        text = message.lower()
        return any(text.startswith(prefix) for prefix in _ADD_PREFIXES) or any(
            keyword in text for keyword in _LIST_KEYWORDS
        )

    def execute(self, message: str, context: SkillContext) -> str:
        text = message.strip()
        lowered = text.lower()
        for prefix in _ADD_PREFIXES:
            if lowered.startswith(prefix):
                goal_name = text[len(prefix):].strip()
                if not goal_name:
                    return "Tell me what the goal should be, e.g. 'add goal: launch the website'."
                context.goals.add_goal(Goal(name=goal_name))
                return f"Added goal: {goal_name}"

        goals = context.goals.list_goals()
        if not goals:
            return "No goals are currently tracked."
        listed = "; ".join(f"{goal.name} ({goal.status})" for goal in goals)
        return f"Current goals: {listed}"
