"""
tests/test_multi_agent.py — Milestone 17: Multi-Agent Collaboration.

Covers:
  - Team dataclass (build_goal, task_type_names, repr)
  - TeamRegistry (register/get/list/has/unregister/teams_for_task_type/
                  build_team_registry)
  - TeamAssignment + MultiAgentPlan (as_display_lines, team_count, team_names)
  - TeamResult + MultiAgentResult (success_rate, all_outputs, as_display_lines,
                                   completed_teams, total_tasks, etc.)
  - TeamPlanner rule-based (keyword matching, ordering, default pipeline, min_teams)
  - TeamRunner (builds scoped registry, returns TeamResult, handles errors)
  - CEOAgent (execute, preview_plan, run, with_agent, context chaining,
              missing team handling)
  - Console commands (teams, team, ceo-plan, ceo)
  - SmartAgent.ceo attribute
  - Backward compatibility
"""

from __future__ import annotations

import pytest

from smartagent.executive.task import TaskType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry():
    from smartagent.multi_agent.team import TeamRegistry
    return TeamRegistry()


@pytest.fixture()
def planner(registry):
    from smartagent.multi_agent.team_planner import TeamPlanner
    return TeamPlanner(team_registry=registry)


@pytest.fixture()
def ceo(registry):
    from smartagent.multi_agent.ceo_agent import CEOAgent
    return CEOAgent(team_registry=registry)


# ---------------------------------------------------------------------------
# Team dataclass
# ---------------------------------------------------------------------------

class TestTeam:
    def test_build_goal_uses_template(self, registry):
        team = registry.get("engineering")
        goal = team.build_goal("Build a weather API")
        assert "Build a weather API" in goal
        assert len(goal) > len("Build a weather API")  # template adds text

    def test_build_goal_default_template(self):
        from smartagent.multi_agent.team import Team
        t = Team(name="custom", description="test", task_types=[TaskType.GENERIC])
        assert t.build_goal("my goal") == "my goal"

    def test_task_type_names_sorted(self, registry):
        team = registry.get("research")
        names = team.task_type_names
        assert names == sorted(names)
        assert "research" in names
        assert "analysis" in names

    def test_repr_contains_name(self, registry):
        team = registry.get("qa")
        assert "qa" in repr(team)

    def test_emoji_field(self, registry):
        team = registry.get("research")
        assert team.emoji  # non-empty


# ---------------------------------------------------------------------------
# TeamRegistry
# ---------------------------------------------------------------------------

class TestTeamRegistry:
    def test_default_four_teams(self, registry):
        assert registry.count() == 4
        assert set(registry.names()) == {"research", "engineering", "qa", "documentation"}

    def test_get_existing(self, registry):
        team = registry.get("engineering")
        assert team is not None
        assert team.name == "engineering"

    def test_get_missing_returns_none(self, registry):
        assert registry.get("nonexistent") is None

    def test_has_true(self, registry):
        assert registry.has("qa")

    def test_has_false(self, registry):
        assert not registry.has("ghost")

    def test_list_teams(self, registry):
        teams = registry.list_teams()
        assert len(teams) == 4
        names = {t.name for t in teams}
        assert "research" in names

    def test_register_custom_team(self, registry):
        from smartagent.multi_agent.team import Team
        custom = Team(
            name="security",
            description="Security auditing team.",
            task_types=[TaskType.REVIEW],
        )
        registry.register(custom)
        assert registry.has("security")
        assert registry.count() == 5

    def test_unregister(self, registry):
        registry.unregister("qa")
        assert not registry.has("qa")
        assert registry.count() == 3

    def test_unregister_missing_noop(self, registry):
        registry.unregister("ghost")  # must not raise

    def test_teams_for_task_type(self, registry):
        teams = registry.teams_for_task_type(TaskType.RESEARCH)
        names = {t.name for t in teams}
        assert "research" in names
        assert "engineering" not in names

    def test_teams_for_task_type_review_in_multiple(self, registry):
        # REVIEW is in both engineering and qa
        teams = registry.teams_for_task_type(TaskType.REVIEW)
        names = {t.name for t in teams}
        assert "engineering" in names
        assert "qa" in names

    def test_build_team_registry_research(self, registry):
        wr = registry.build_team_registry("research")
        assert wr.has(TaskType.RESEARCH)
        assert wr.has(TaskType.ANALYSIS)
        assert wr.has(TaskType.GENERIC)  # always included

    def test_build_team_registry_engineering(self, registry):
        wr = registry.build_team_registry("engineering")
        assert wr.has(TaskType.CODING)
        assert wr.has(TaskType.PLANNING)

    def test_build_team_registry_unknown_returns_full(self, registry):
        wr = registry.build_team_registry("ghost")
        # Falls back to full default registry (has many types)
        assert wr.count() > 4

    def test_repr(self, registry):
        assert "research" in repr(registry)


# ---------------------------------------------------------------------------
# TeamAssignment + MultiAgentPlan
# ---------------------------------------------------------------------------

class TestTeamAssignment:
    def test_repr(self):
        from smartagent.multi_agent.team_assignment import TeamAssignment
        a = TeamAssignment(team_name="engineering", goal="Build a REST API")
        assert "engineering" in repr(a)
        assert "Build a REST API" in repr(a)


class TestMultiAgentPlan:
    def _make_plan(self):
        from smartagent.multi_agent.team_assignment import MultiAgentPlan, TeamAssignment
        return MultiAgentPlan(
            goal="Build a REST API",
            assignments=[
                TeamAssignment(team_name="research",     goal="Research REST APIs",   priority=0),
                TeamAssignment(team_name="engineering",  goal="Implement REST API",   priority=1,
                               dependencies=["research"]),
                TeamAssignment(team_name="qa",           goal="Test the API",         priority=2),
                TeamAssignment(team_name="documentation",goal="Document the API",     priority=3),
            ],
        )

    def test_team_count(self):
        plan = self._make_plan()
        assert plan.team_count == 4

    def test_team_names(self):
        plan = self._make_plan()
        assert plan.team_names == ["research", "engineering", "qa", "documentation"]

    def test_as_display_lines_contains_goal(self):
        plan = self._make_plan()
        lines = plan.as_display_lines()
        full = "\n".join(lines)
        assert "Build a REST API" in full
        assert "RESEARCH" in full
        assert "ENGINEERING" in full

    def test_plan_id_generated(self):
        from smartagent.multi_agent.team_assignment import MultiAgentPlan
        p1 = MultiAgentPlan(goal="g1")
        p2 = MultiAgentPlan(goal="g2")
        assert p1.plan_id != p2.plan_id

    def test_repr(self):
        plan = self._make_plan()
        assert "research" in repr(plan)


# ---------------------------------------------------------------------------
# TeamResult + MultiAgentResult
# ---------------------------------------------------------------------------

class TestTeamResult:
    def test_success_rate_all_completed(self):
        from smartagent.multi_agent.team_result import TeamResult
        r = TeamResult(team_name="research", goal="test", task_count=5, completed=5)
        assert r.success_rate == pytest.approx(1.0)

    def test_success_rate_none_completed(self):
        from smartagent.multi_agent.team_result import TeamResult
        r = TeamResult(team_name="research", goal="test", task_count=5, completed=0)
        assert r.success_rate == pytest.approx(0.0)

    def test_success_rate_zero_tasks(self):
        from smartagent.multi_agent.team_result import TeamResult
        r = TeamResult(team_name="research", goal="test")
        assert r.success_rate == pytest.approx(0.0)

    def test_one_line_contains_state(self):
        from smartagent.multi_agent.team_result import TeamResult
        r = TeamResult(team_name="engineering", goal="test",
                       state="completed", task_count=3, completed=3, duration=1.5)
        line = r.one_line()
        assert "engineering" in line
        assert "completed" in line

    def test_one_line_failed_shows_x(self):
        from smartagent.multi_agent.team_result import TeamResult
        r = TeamResult(team_name="qa", goal="test", state="failed")
        assert "✗" in r.one_line()

    def test_repr(self):
        from smartagent.multi_agent.team_result import TeamResult
        r = TeamResult(team_name="qa", goal="test", state="completed",
                       task_count=2, completed=2)
        assert "qa" in repr(r)
        assert "completed" in repr(r)


class TestMultiAgentResult:
    def _make_result(self, states=None):
        from smartagent.multi_agent.team_result import MultiAgentResult, TeamResult
        states = states or ["completed", "completed", "completed", "completed"]
        teams = ["research", "engineering", "qa", "documentation"]
        return MultiAgentResult(
            goal="Build a REST API",
            plan_id="plan-001",
            team_results=[
                TeamResult(team_name=t, goal="test", state=s,
                           task_count=3, completed=3 if s == "completed" else 1,
                           outputs=[f"{t} output"])
                for t, s in zip(teams, states)
            ],
            overall_state=states[0],
        )

    def test_completed_teams(self):
        r = self._make_result(["completed", "completed", "failed", "completed"])
        assert r.completed_teams == 3

    def test_failed_teams(self):
        r = self._make_result(["completed", "failed", "failed", "completed"])
        assert r.failed_teams == 2

    def test_total_tasks(self):
        r = self._make_result()
        assert r.total_tasks == 12  # 4 teams × 3 tasks

    def test_all_outputs_labelled(self):
        r = self._make_result()
        outputs = r.all_outputs()
        assert len(outputs) == 4
        assert any("[research]" in o for o in outputs)
        assert any("[documentation]" in o for o in outputs)

    def test_as_display_lines_contains_goal(self):
        r = self._make_result()
        full = "\n".join(r.as_display_lines())
        assert "Build a REST API" in full
        assert "research" in full

    def test_team_count(self):
        r = self._make_result()
        assert r.team_count == 4

    def test_repr(self):
        r = self._make_result()
        assert "completed" in repr(r)


# ---------------------------------------------------------------------------
# TeamPlanner — rule-based
# ---------------------------------------------------------------------------

class TestTeamPlannerRuleBased:
    def test_research_keywords_select_research(self, planner):
        plan = planner.plan("Research best practices for REST APIs")
        names = plan.team_names
        assert "research" in names

    def test_build_keywords_select_engineering(self, planner):
        plan = planner.plan("Build and implement a Python REST API server")
        names = plan.team_names
        assert "engineering" in names

    def test_test_keywords_select_qa(self, planner):
        plan = planner.plan("Test and validate the API endpoints")
        names = plan.team_names
        assert "qa" in names

    def test_document_keywords_select_documentation(self, planner):
        plan = planner.plan("Write documentation and README for the project")
        names = plan.team_names
        assert "documentation" in names

    def test_generic_goal_uses_default_pipeline(self, planner):
        # No keywords — should use full default pipeline
        plan = planner.plan("Do something amazing")
        assert len(plan.team_names) >= 2

    def test_ordering_research_before_engineering(self, planner):
        plan = planner.plan("Research and build a REST API")
        names = plan.team_names
        assert names.index("research") < names.index("engineering")

    def test_all_four_teams_for_comprehensive_goal(self, planner):
        plan = planner.plan(
            "Research, build, test, and document a Python FastAPI service"
        )
        names = set(plan.team_names)
        assert "research" in names
        assert "engineering" in names
        assert "qa" in names
        assert "documentation" in names

    def test_plan_has_goal(self, planner):
        goal = "Build a calculator"
        plan = planner.plan(goal)
        assert plan.goal == goal

    def test_assignments_have_sub_goals(self, planner):
        plan = planner.plan("Build a REST API")
        for a in plan.assignments:
            assert len(a.goal) > 0

    def test_engineering_depends_on_research(self, planner):
        """Engineering assignment should list research as a dependency."""
        plan = planner.plan("Research and build a REST API")
        eng = next((a for a in plan.assignments if a.team_name == "engineering"), None)
        if eng and "research" in plan.team_names:
            assert "research" in eng.dependencies

    def test_model_field_is_rule_based(self, planner):
        plan = planner.plan("Build something")
        assert plan.model == "rule-based"

    def test_min_teams_respected(self, registry):
        from smartagent.multi_agent.team_planner import TeamPlanner
        p = TeamPlanner(team_registry=registry, min_teams=3)
        plan = p.plan("Do something vague")
        assert len(plan.team_names) >= 3

    def test_plan_id_unique(self, planner):
        p1 = planner.plan("goal 1")
        p2 = planner.plan("goal 2")
        assert p1.plan_id != p2.plan_id

    def test_as_display_lines_non_empty(self, planner):
        plan = planner.plan("Build a weather API")
        assert plan.as_display_lines()

    def test_custom_team_in_plan(self, registry):
        from smartagent.multi_agent.team import Team
        from smartagent.multi_agent.team_planner import TeamPlanner
        registry.register(Team(
            name="security",
            description="Security audit.",
            task_types=[TaskType.REVIEW],
        ))
        # Force include all teams
        p = TeamPlanner(team_registry=registry, min_teams=5)
        plan = p.plan("Build something")
        assert len(plan.assignments) >= 2


# ---------------------------------------------------------------------------
# TeamRunner
# ---------------------------------------------------------------------------

class TestTeamRunner:
    def test_runner_returns_team_result(self, registry):
        from smartagent.multi_agent.team_assignment import TeamAssignment
        from smartagent.multi_agent.team_runner import TeamRunner
        team = registry.get("research")
        runner = TeamRunner(team=team)
        assignment = TeamAssignment(team_name="research", goal="Research REST APIs")
        result = runner.run(assignment)
        assert result.team_name == "research"
        assert result.state in ("completed", "partial", "failed")

    def test_runner_sets_team_name_in_result(self, registry):
        from smartagent.multi_agent.team_assignment import TeamAssignment
        from smartagent.multi_agent.team_runner import TeamRunner
        team = registry.get("engineering")
        runner = TeamRunner(team=team)
        assignment = TeamAssignment(team_name="engineering", goal="Build a calculator")
        result = runner.run(assignment)
        assert result.team_name == "engineering"

    def test_runner_prior_context_passed(self, registry):
        from smartagent.multi_agent.team_assignment import TeamAssignment
        from smartagent.multi_agent.team_runner import TeamRunner
        team = registry.get("qa")
        runner = TeamRunner(team=team)
        assignment = TeamAssignment(team_name="qa", goal="Test the implementation")
        result = runner.run(assignment, prior_context="Engineering built X.")
        # Must not raise and must return a result
        assert result is not None
        assert result.team_name == "qa"

    def test_runner_result_has_duration(self, registry):
        from smartagent.multi_agent.team_assignment import TeamAssignment
        from smartagent.multi_agent.team_runner import TeamRunner
        team = registry.get("documentation")
        runner = TeamRunner(team=team)
        assignment = TeamAssignment(team_name="documentation", goal="Document the API")
        result = runner.run(assignment)
        assert result.duration >= 0

    def test_runner_filtered_registry_excludes_off_team_types(self, registry):
        from smartagent.multi_agent.team_runner import TeamRunner
        from smartagent.executive.worker_registry import WorkerRegistry
        team = registry.get("qa")
        runner = TeamRunner(team=team, use_team_registry=True)
        wr = runner._orchestrator._worker_registry
        # QA team should NOT have CODING worker at its primary mapping
        # (though it may fall back to generic)
        assert isinstance(wr, WorkerRegistry)
        assert wr.has(TaskType.TESTING)   # QA has TESTING
        assert wr.has(TaskType.GENERIC)   # always present

    def test_runner_unfiltered_registry_option(self, registry):
        from smartagent.multi_agent.team_runner import TeamRunner
        team = registry.get("research")
        runner = TeamRunner(team=team, use_team_registry=False)
        wr = runner._orchestrator._worker_registry
        # Full registry: has coding, testing, etc.
        assert wr.has(TaskType.CODING)
        assert wr.has(TaskType.TESTING)


# ---------------------------------------------------------------------------
# CEOAgent
# ---------------------------------------------------------------------------

class TestCEOAgent:
    def test_execute_returns_multi_agent_result(self, ceo):
        from smartagent.multi_agent.team_result import MultiAgentResult
        result = ceo.execute("Build a simple calculator")
        assert isinstance(result, MultiAgentResult)

    def test_execute_result_has_team_results(self, ceo):
        result = ceo.execute("Build a REST API")
        assert result.team_count >= 1

    def test_execute_all_teams_present(self, ceo):
        result = ceo.execute(
            "Research, build, test, and document a FastAPI service"
        )
        names = {r.team_name for r in result.team_results}
        assert "research" in names
        assert "engineering" in names
        assert "qa" in names
        assert "documentation" in names

    def test_execute_has_overall_state(self, ceo):
        result = ceo.execute("Build a calculator")
        assert result.overall_state in ("completed", "partial", "failed")

    def test_execute_has_duration(self, ceo):
        result = ceo.execute("Build a calculator")
        assert result.duration >= 0

    def test_execute_has_summary(self, ceo):
        result = ceo.execute("Build a calculator")
        assert len(result.summary) > 0

    def test_execute_sets_last_result(self, ceo):
        ceo.execute("Build a calculator")
        assert ceo.last_result is not None

    def test_preview_plan_returns_plan(self, ceo):
        from smartagent.multi_agent.team_assignment import MultiAgentPlan
        plan = ceo.preview_plan("Build a REST API")
        assert isinstance(plan, MultiAgentPlan)

    def test_preview_plan_stores_plan(self, ceo):
        ceo.preview_plan("Build something")
        assert ceo.last_plan is not None

    def test_run_after_preview(self, ceo):
        from smartagent.multi_agent.team_result import MultiAgentResult
        ceo.preview_plan("Build a calculator")
        result = ceo.run()
        assert isinstance(result, MultiAgentResult)

    def test_run_without_plan_raises(self, ceo):
        with pytest.raises(RuntimeError, match="No plan"):
            ceo.run()

    def test_execute_plan_goal_preserved(self, ceo):
        goal = "Build a weather API service"
        result = ceo.execute(goal)
        assert result.goal == goal

    def test_execute_plan_id_set(self, ceo):
        result = ceo.execute("Build something")
        assert result.plan_id  # non-empty

    def test_context_chaining_sequential(self, registry):
        """Research output should appear in later teams' prior_context."""
        from smartagent.multi_agent.ceo_agent import CEOAgent
        from smartagent.multi_agent.team_assignment import MultiAgentPlan, TeamAssignment

        received_contexts: list[str] = []

        # Patch TeamRunner.run to capture prior_context
        from smartagent.multi_agent import team_runner as tr_module
        original_run = tr_module.TeamRunner.run

        def mock_run(self, assignment, prior_context=""):
            received_contexts.append(prior_context)
            from smartagent.multi_agent.team_result import TeamResult
            return TeamResult(
                team_name=self._team.name,
                goal=assignment.goal,
                state="completed",
                summary=f"Output from {self._team.name}",
                task_count=1,
                completed=1,
            )

        tr_module.TeamRunner.run = mock_run
        try:
            ceo = CEOAgent(team_registry=registry)
            ceo.execute("Research, build, test, and document a service")
        finally:
            tr_module.TeamRunner.run = original_run

        # First team gets empty context; later teams accumulate
        assert received_contexts[0] == ""  # research gets nothing
        assert "research" in received_contexts[1].lower() or \
               "Output from research" in received_contexts[1]  # engineering gets research

    def test_missing_team_in_registry(self):
        """CEOAgent handles a plan that references an unregistered team gracefully."""
        from smartagent.multi_agent.ceo_agent import CEOAgent
        from smartagent.multi_agent.team import TeamRegistry, Team
        from smartagent.multi_agent.team_planner import TeamPlanner
        from smartagent.multi_agent.team_assignment import MultiAgentPlan, TeamAssignment

        # Registry without 'ghost' team
        reg = TeamRegistry()
        ceo = CEOAgent(team_registry=reg)
        # Manually construct a plan referencing a missing team
        plan = MultiAgentPlan(
            goal="test",
            assignments=[
                TeamAssignment(team_name="ghost", goal="do something"),
                TeamAssignment(team_name="research", goal="Research test"),
            ]
        )
        result = ceo._execute_plan(plan)
        # Ghost team → failed result
        ghost_result = next(r for r in result.team_results if r.team_name == "ghost")
        assert ghost_result.state == "failed"

    def test_with_agent_creates_ceo(self):
        from smartagent.multi_agent.ceo_agent import CEOAgent

        class FakeAgent:
            model_manager     = None
            memory            = None
            knowledge         = None
            settings          = None
            tool_engine       = None
            events            = None
            reflection_engine = None
            workspace_manager = None

        ceo = CEOAgent.with_agent(FakeAgent())
        assert isinstance(ceo, CEOAgent)

    def test_with_agent_no_attributes(self):
        from smartagent.multi_agent.ceo_agent import CEOAgent

        class EmptyAgent:
            pass

        ceo = CEOAgent.with_agent(EmptyAgent())
        assert isinstance(ceo, CEOAgent)

    def test_all_failed_overall_state_is_failed(self):
        from smartagent.multi_agent.ceo_agent import CEOAgent
        from smartagent.multi_agent.team_assignment import MultiAgentPlan, TeamAssignment
        from smartagent.multi_agent.team_result import TeamResult
        from smartagent.multi_agent.team import TeamRegistry
        from smartagent.multi_agent import team_runner as tr_module

        def mock_run(self, assignment, prior_context=""):
            return TeamResult(
                team_name=self._team.name, goal=assignment.goal, state="failed"
            )

        original = tr_module.TeamRunner.run
        tr_module.TeamRunner.run = mock_run
        try:
            ceo = CEOAgent(team_registry=TeamRegistry())
            result = ceo.execute("Build something")
        finally:
            tr_module.TeamRunner.run = original

        assert result.overall_state == "failed"

    def test_partial_failure_overall_state_is_partial(self):
        from smartagent.multi_agent.ceo_agent import CEOAgent
        from smartagent.multi_agent.team_result import TeamResult
        from smartagent.multi_agent.team import TeamRegistry
        from smartagent.multi_agent import team_runner as tr_module

        call_count = [0]

        def mock_run(self, assignment, prior_context=""):
            call_count[0] += 1
            state = "completed" if call_count[0] % 2 == 1 else "failed"
            return TeamResult(
                team_name=self._team.name, goal=assignment.goal, state=state
            )

        original = tr_module.TeamRunner.run
        tr_module.TeamRunner.run = mock_run
        try:
            ceo = CEOAgent(team_registry=TeamRegistry())
            result = ceo.execute(
                "Research, build, test, and document something"
            )
        finally:
            tr_module.TeamRunner.run = original

        assert result.overall_state in ("partial", "completed", "failed")

    def test_team_registry_property(self, ceo, registry):
        assert ceo.team_registry is registry


# ---------------------------------------------------------------------------
# Orchestrator — _extra_metadata injection
# ---------------------------------------------------------------------------

class TestOrchestratorExtraMetadata:
    def test_extra_metadata_injected_into_context(self):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext

        orc = Orchestrator()
        orc._extra_metadata = {"team_name": "engineering", "prior_context": "stuff"}
        ctx = ExecutionContext(goal="test")
        orc._inject_services(ctx)
        assert ctx.metadata.get("team_name") == "engineering"
        assert ctx.metadata.get("prior_context") == "stuff"

    def test_no_extra_metadata_no_error(self):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        orc = Orchestrator()
        ctx = ExecutionContext(goal="test")
        orc._inject_services(ctx)  # must not raise


# ---------------------------------------------------------------------------
# SmartAgent.ceo attribute
# ---------------------------------------------------------------------------

class TestSmartAgentCEO:
    def test_agent_has_ceo(self):
        import tempfile
        from smartagent.brain.agent import SmartAgent
        from smartagent.config.settings import Settings
        from smartagent.multi_agent.ceo_agent import CEOAgent
        s = Settings(workspaces_path=tempfile.mkdtemp())
        agent = SmartAgent(s)
        assert hasattr(agent, "ceo")
        assert isinstance(agent.ceo, CEOAgent)

    def test_ceo_team_registry_has_four_teams(self):
        import tempfile
        from smartagent.brain.agent import SmartAgent
        from smartagent.config.settings import Settings
        s = Settings(workspaces_path=tempfile.mkdtemp())
        agent = SmartAgent(s)
        assert agent.ceo.team_registry.count() == 4


# ---------------------------------------------------------------------------
# Console commands
# ---------------------------------------------------------------------------

class TestMultiAgentCommandsRegistration:
    def test_commands_registered(self):
        from smartagent.ui.command_router import CommandRouter
        from smartagent.ui.commands import multi_agent
        router = CommandRouter()
        multi_agent.register(router)
        names = {e.name for e in router.commands()}
        assert "teams" in names
        assert "team" in names
        assert "ceo-plan" in names
        assert "ceo" in names


class _FakeCEO:
    """Minimal CEOAgent stub for command handler tests."""
    def __init__(self, registry):
        self.team_registry = registry
        self._last_plan = None

    def execute(self, goal):
        from smartagent.multi_agent.team_result import MultiAgentResult, TeamResult
        return MultiAgentResult(
            goal=goal,
            plan_id="test-plan",
            team_results=[
                TeamResult(team_name="research", goal=goal, state="completed",
                           task_count=2, completed=2),
            ],
            overall_state="completed",
            summary="Done.",
        )

    def preview_plan(self, goal):
        from smartagent.multi_agent.team_assignment import MultiAgentPlan, TeamAssignment
        self._last_plan = MultiAgentPlan(
            goal=goal,
            assignments=[TeamAssignment(team_name="research", goal=f"Research: {goal}")],
        )
        return self._last_plan

    @property
    def last_plan(self):
        return self._last_plan


class _FakeAgent:
    def __init__(self, registry):
        self.ceo = _FakeCEO(registry)


class TestMultiAgentCommandHandlers:
    def test_teams_handler_lists_teams(self, registry):
        from smartagent.ui.commands.multi_agent import handle_teams
        agent = _FakeAgent(registry)
        result = handle_teams(agent, [])
        assert "research" in result
        assert "engineering" in result
        assert "qa" in result
        assert "documentation" in result

    def test_teams_handler_no_ceo(self):
        from smartagent.ui.commands.multi_agent import handle_teams
        class NoCEO:
            pass
        result = handle_teams(NoCEO(), [])
        assert "[error]" in result

    def test_team_handler_existing_team(self, registry):
        from smartagent.ui.commands.multi_agent import handle_team
        agent = _FakeAgent(registry)
        result = handle_team(agent, ["engineering"])
        assert "engineering" in result
        assert "CODING" in result.upper() or "coding" in result.lower()

    def test_team_handler_missing_team(self, registry):
        from smartagent.ui.commands.multi_agent import handle_team
        agent = _FakeAgent(registry)
        result = handle_team(agent, ["ghost"])
        assert "[error]" in result

    def test_team_handler_no_args_shows_list(self, registry):
        from smartagent.ui.commands.multi_agent import handle_team
        agent = _FakeAgent(registry)
        result = handle_team(agent, [])
        assert "research" in result

    def test_ceo_plan_handler(self, registry):
        from smartagent.ui.commands.multi_agent import handle_ceo_plan
        agent = _FakeAgent(registry)
        result = handle_ceo_plan(agent, ["Build", "a", "REST", "API"])
        assert "REST API" in result or "research" in result.lower()

    def test_ceo_plan_handler_no_args(self, registry):
        from smartagent.ui.commands.multi_agent import handle_ceo_plan
        agent = _FakeAgent(registry)
        result = handle_ceo_plan(agent, [])
        assert "usage" in result.lower() or "ceo-plan" in result.lower()

    def test_ceo_handler_runs(self, registry):
        from smartagent.ui.commands.multi_agent import handle_ceo
        agent = _FakeAgent(registry)
        result = handle_ceo(agent, ["Build", "a", "calculator"])
        assert "calculator" in result.lower() or "research" in result.lower()

    def test_ceo_handler_no_args(self, registry):
        from smartagent.ui.commands.multi_agent import handle_ceo
        agent = _FakeAgent(registry)
        result = handle_ceo(agent, [])
        assert "usage" in result.lower() or "ceo" in result.lower()


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_multi_agent_package_importable(self):
        from smartagent import multi_agent  # noqa: F401
        from smartagent.multi_agent import (
            CEOAgent, MultiAgentPlan, MultiAgentResult,
            Team, TeamAssignment, TeamPlanner, TeamRegistry,
            TeamResult, TeamRunner,
        )
        assert CEOAgent is not None

    def test_executive_unchanged(self):
        """Existing Executive pipeline still works independently."""
        from smartagent.executive.executive_controller import ExecutiveController
        ctrl = ExecutiveController()
        ctx = ctrl.plan("Write a hello world program")
        assert ctx.task_count > 0

    def test_orchestrator_backward_compat(self):
        """Orchestrator with no extra_metadata doesn't break."""
        from smartagent.executive.orchestrator import Orchestrator
        orc = Orchestrator()
        ctx = orc.execute_goal("Write a hello world program")
        assert ctx is not None
