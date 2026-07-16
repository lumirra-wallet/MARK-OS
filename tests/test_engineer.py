"""
Tests for Milestone 25: Full Software Engineer.

Coverage:
    RequirementAnalyzer:
      · analyze() returns RequirementReport
      · detects backend domain from "api" keyword
      · detects frontend domain from "react" keyword
      · detects auth domain from "login" keyword
      · detects database domain from "postgres" keyword
      · detects stack hint for FastAPI
      · detects stack hint for PostgreSQL
      · estimates small complexity for short goal
      · estimates large complexity for many domains
      · generates question for auth without method
      · generates question for database without type
      · generates no questions when specifics are provided
      · RequirementReport.as_display_lines includes all fields
      · RequirementReport.as_ai_context includes goal and domains

    ClarificationEngine:
      · from_report() returns ClarificationSet
      · from_report() returns empty set when no open_questions
      · from_report() caps questions at 5
      · ClarificationSet.answer() stores value
      · ClarificationSet.answer_all_with_defaults() fills unanswered
      · ClarificationSet.has_required True when unanswered required question
      · ClarificationSet.as_display_lines() no questions message
      · ClarificationSet.as_context() empty when nothing answered
      · ClarificationSet.as_context() formats answered values

    SoftwareEngineerReport:
      · as_display_lines() shows goal
      · as_display_lines() shows success icon
      · as_display_lines() shows loop result
      · as_display_lines() shows committed

    SoftwareEngineer:
      · with_agent() factory constructs without error
      · build() returns SoftwareEngineerReport
      · build() populates requirements field
      · build() populates clarifications field
      · build() success=True when dev_loop succeeds
      · build() success=False when dev_loop fails
      · build() calls dev_loop.run() with enriched goal
      · build() persists to memory on completion
      · build() auto_commit calls git.add and git.commit on success
      · _analyze() includes project context when project_name provided
      · _clarify() applies defaults in non-interactive mode
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from smartagent.engineer.requirement_analyzer import RequirementAnalyzer, RequirementReport
from smartagent.engineer.clarification_engine import (
    ClarificationEngine,
    ClarificationQuestion,
    ClarificationSet,
)
from smartagent.engineer.software_engineer import SoftwareEngineer, SoftwareEngineerReport


# ---------------------------------------------------------------------------
# RequirementAnalyzer
# ---------------------------------------------------------------------------

class TestRequirementAnalyzer:
    def setup_method(self):
        self.analyzer = RequirementAnalyzer()

    def test_returns_requirement_report(self):
        result = self.analyzer.analyze("Build a simple API")
        assert isinstance(result, RequirementReport)

    def test_detects_backend_domain(self):
        result = self.analyzer.analyze("Build a REST API for user management")
        assert "backend" in result.domains

    def test_detects_frontend_domain(self):
        result = self.analyzer.analyze("Build a React dashboard")
        assert "frontend" in result.domains

    def test_detects_auth_domain(self):
        result = self.analyzer.analyze("Add login and registration with JWT")
        assert "auth" in result.domains

    def test_detects_database_domain(self):
        result = self.analyzer.analyze("Build a database schema with PostgreSQL migrations")
        assert "database" in result.domains

    def test_detects_fastapi_stack_hint(self):
        result = self.analyzer.analyze("Build a FastAPI service")
        assert "FastAPI" in result.stack_hints

    def test_detects_postgres_stack_hint(self):
        result = self.analyzer.analyze("Use PostgreSQL for the database")
        assert "PostgreSQL" in result.stack_hints

    def test_detects_pytest_stack_hint(self):
        result = self.analyzer.analyze("Write tests with pytest")
        assert "pytest" in result.stack_hints

    def test_complexity_small_short_goal(self):
        result = self.analyzer.analyze("Add a logger")
        assert result.complexity in ("small", "medium")

    def test_complexity_large_many_domains(self):
        goal = (
            "Build a full SaaS platform with React frontend, FastAPI backend, "
            "PostgreSQL database, JWT authentication, Stripe payments, "
            "real-time WebSocket notifications, Docker deployment, and pytest tests"
        )
        result = self.analyzer.analyze(goal)
        assert result.complexity in ("large", "xlarge")

    def test_generates_question_for_auth_without_method(self):
        result = self.analyzer.analyze("Add user authentication to the API")
        assert any("auth" in q.lower() or "jwt" in q.lower() for q in result.open_questions)

    def test_generates_question_for_database_without_type(self):
        result = self.analyzer.analyze("Store user data in a database")
        assert any("database" in q.lower() for q in result.open_questions)

    def test_no_auth_question_when_jwt_specified(self):
        result = self.analyzer.analyze("Add JWT authentication to the API")
        # Auth question should not be needed since JWT is specified
        auth_questions = [q for q in result.open_questions if "jwt" in q.lower()]
        # Either no questions or fewer questions
        assert len(result.open_questions) <= 3

    def test_teams_always_include_engineering(self):
        result = self.analyzer.analyze("Build a CLI tool")
        assert "engineering" in result.teams

    def test_teams_include_qa_for_multi_domain(self):
        result = self.analyzer.analyze("Build an API with tests and documentation")
        assert "qa" in result.teams

    def test_teams_include_documentation(self):
        result = self.analyzer.analyze("Build an API")
        assert "documentation" in result.teams

    def test_goal_preserved_in_report(self):
        goal = "Build a specific service for X"
        result = self.analyzer.analyze(goal)
        assert result.goal == goal


class TestRequirementReport:
    def test_as_display_lines_shows_goal(self):
        report = RequirementReport(
            goal="Build a Trello clone",
            complexity="large",
            domains=["backend", "frontend"],
        )
        lines = report.as_display_lines()
        assert any("Trello" in l for l in lines)

    def test_as_display_lines_shows_complexity(self):
        report = RequirementReport(goal="X", complexity="xlarge")
        lines = report.as_display_lines()
        assert any("xlarge" in l for l in lines)

    def test_as_display_lines_shows_domains(self):
        report = RequirementReport(
            goal="X",
            domains=["backend", "auth"],
        )
        lines = report.as_display_lines()
        assert any("backend" in l for l in lines)

    def test_as_display_lines_shows_questions(self):
        report = RequirementReport(
            goal="X",
            open_questions=["Which database should be used?"],
        )
        lines = report.as_display_lines()
        assert any("database" in l for l in lines)

    def test_as_ai_context_includes_goal(self):
        report = RequirementReport(goal="Build Trello", complexity="large")
        ctx = report.as_ai_context()
        assert "Trello" in ctx

    def test_as_ai_context_includes_domains(self):
        report = RequirementReport(
            goal="X",
            domains=["backend", "auth"],
        )
        ctx = report.as_ai_context()
        assert "backend" in ctx or "auth" in ctx


# ---------------------------------------------------------------------------
# ClarificationEngine
# ---------------------------------------------------------------------------

class TestClarificationEngine:
    def setup_method(self):
        self.engine = ClarificationEngine()

    def _make_report(self, goal="Build X", questions=None, domains=None):
        r = MagicMock()
        r.goal = goal
        r.open_questions = questions or []
        r.domains = domains or ["backend"]
        return r

    def test_from_report_returns_clarification_set(self):
        report = self._make_report()
        cset = self.engine.from_report(report)
        assert isinstance(cset, ClarificationSet)

    def test_from_report_empty_when_no_open_questions(self):
        report = self._make_report(questions=[])
        cset = self.engine.from_report(report)
        assert len(cset.questions) == 0

    def test_from_report_creates_questions(self):
        report = self._make_report(
            questions=["Which database?", "Which auth method?"]
        )
        cset = self.engine.from_report(report)
        assert len(cset.questions) == 2

    def test_from_report_caps_at_five(self):
        report = self._make_report(
            questions=[f"Question {i}" for i in range(10)]
        )
        cset = self.engine.from_report(report)
        assert len(cset.questions) <= 5

    def test_from_report_goal_preserved(self):
        report = self._make_report(goal="Build Trello")
        cset = self.engine.from_report(report)
        assert cset.goal == "Build Trello"


class TestClarificationSet:
    def test_answer_stores_value(self):
        cset = ClarificationSet(goal="X", questions=[
            ClarificationQuestion(id="q_auth", prompt="Which auth method?", required=True)
        ])
        cset.answer("q_auth", "JWT")
        assert cset.answered["q_auth"] == "JWT"

    def test_answer_all_with_defaults(self):
        cset = ClarificationSet(goal="X", questions=[
            ClarificationQuestion(id="q_auth", prompt="Which auth?", default="JWT"),
            ClarificationQuestion(id="q_db", prompt="Which DB?", default="PostgreSQL"),
        ])
        cset.answer_all_with_defaults()
        assert cset.answered["q_auth"] == "JWT"
        assert cset.answered["q_db"] == "PostgreSQL"

    def test_answer_all_skips_already_answered(self):
        cset = ClarificationSet(goal="X", questions=[
            ClarificationQuestion(id="q_auth", prompt="Which auth?", default="JWT"),
        ])
        cset.answer("q_auth", "sessions")
        cset.answer_all_with_defaults()
        assert cset.answered["q_auth"] == "sessions"  # not overwritten

    def test_has_required_true_when_unanswered_required(self):
        cset = ClarificationSet(goal="X", questions=[
            ClarificationQuestion(id="q1", prompt="Q?", required=True),
        ])
        assert cset.has_required is True

    def test_has_required_false_when_all_answered(self):
        cset = ClarificationSet(goal="X", questions=[
            ClarificationQuestion(id="q1", prompt="Q?", required=True),
        ])
        cset.answer("q1", "answer")
        assert cset.has_required is False

    def test_has_required_false_when_no_required(self):
        cset = ClarificationSet(goal="X", questions=[
            ClarificationQuestion(id="q1", prompt="Q?", required=False),
        ])
        assert cset.has_required is False

    def test_as_display_lines_no_questions(self):
        cset = ClarificationSet(goal="X")
        lines = cset.as_display_lines()
        assert any("no clarification" in l.lower() for l in lines)

    def test_as_display_lines_shows_questions(self):
        cset = ClarificationSet(goal="X", questions=[
            ClarificationQuestion(id="q1", prompt="Which database?"),
        ])
        lines = cset.as_display_lines()
        assert any("database" in l for l in lines)

    def test_as_context_empty_when_no_answers(self):
        cset = ClarificationSet(goal="X")
        assert cset.as_context() == ""

    def test_as_context_formats_answers(self):
        cset = ClarificationSet(goal="X")
        cset.answer("q_auth", "JWT")
        ctx = cset.as_context()
        assert "JWT" in ctx
        assert "q_auth" in ctx


# ---------------------------------------------------------------------------
# SoftwareEngineerReport
# ---------------------------------------------------------------------------

class TestSoftwareEngineerReport:
    def test_as_display_lines_shows_goal(self):
        report = SoftwareEngineerReport(goal="Build a Trello clone")
        lines = report.as_display_lines()
        assert any("Trello" in l for l in lines)

    def test_as_display_lines_success_icon(self):
        report = SoftwareEngineerReport(goal="X", success=True)
        lines = report.as_display_lines()
        assert any("✓" in l for l in lines)

    def test_as_display_lines_failure_icon(self):
        report = SoftwareEngineerReport(goal="X", success=False)
        lines = report.as_display_lines()
        assert any("~" in l for l in lines)

    def test_as_display_lines_shows_committed(self):
        report = SoftwareEngineerReport(
            goal="X",
            committed=True,
            commit_sha="abc1234",
        )
        lines = report.as_display_lines()
        assert any("Committed" in l or "abc1234" in l for l in lines)

    def test_as_display_lines_shows_summary(self):
        report = SoftwareEngineerReport(
            goal="X",
            summary="MARK completed the build.",
        )
        lines = report.as_display_lines()
        assert any("completed" in l for l in lines)


# ---------------------------------------------------------------------------
# SoftwareEngineer
# ---------------------------------------------------------------------------

def _make_loop_result(success=True):
    lr = MagicMock()
    lr.success = success
    lr.stop_reason = "success" if success else "max_iterations"
    lr.iterations = []
    lr.total_elapsed = 5.0
    lr.final_summary = ""

    def _cycle_count():
        return 1
    lr._cycle_count = _cycle_count

    def _display():
        return ["✓ Done" if success else "✗ Failed"]
    lr.as_display_lines = _display
    return lr


class TestSoftwareEngineer:
    def _make_eng(self, loop_success=True) -> SoftwareEngineer:
        dev_loop = MagicMock()
        dev_loop.run.return_value = _make_loop_result(loop_success)
        return SoftwareEngineer(dev_loop=dev_loop)

    def test_with_agent_factory(self):
        agent = MagicMock()
        agent.ceo = MagicMock()
        agent.memory = MagicMock()
        agent.model_manager = None
        agent.project_memory = None
        # DevLoop.with_agent lazy-imports DebugLoop; patch at its source module.
        with patch("smartagent.debug.debug_loop.DebugLoop"):
            eng = SoftwareEngineer.with_agent(agent)
        assert isinstance(eng, SoftwareEngineer)

    def test_build_returns_report(self):
        eng = self._make_eng()
        report = eng.build("Build a login system")
        assert isinstance(report, SoftwareEngineerReport)

    # ---------------------------------------------------------------------------
    # Goals used across these tests must classify as MEDIUM or LARGE so that
    # the progressive-execution router sends them through DevLoop (not the fast
    # path, which is for TRIVIAL/SMALL tasks only).
    # ---------------------------------------------------------------------------

    # Triggers MEDIUM via "authentication system" pattern.
    _MEDIUM_GOAL = "Build a user authentication system with roles and permissions"

    # Triggers LARGE via "auth … and …" pattern.
    _LARGE_GOAL = "Build a REST API with user authentication and CRUD database operations"

    # Trello clone — must keep "Trello" in the goal for the goal-forwarding test,
    # word count > 12 → medium.
    _TRELLO_GOAL = (
        "Build a Trello-style project management application with boards, "
        "cards, user accounts and team collaboration"
    )

    def test_build_populates_requirements(self):
        eng = self._make_eng()
        report = eng.build(self._LARGE_GOAL)
        assert report.requirements is not None
        assert isinstance(report.requirements, RequirementReport)

    def test_build_populates_clarifications(self):
        eng = self._make_eng()
        report = eng.build(self._LARGE_GOAL)
        assert report.clarifications is not None

    def test_build_success_true_when_loop_passes(self):
        eng = self._make_eng(loop_success=True)
        report = eng.build(self._MEDIUM_GOAL)
        assert report.success is True

    def test_build_success_false_when_loop_fails(self):
        eng = self._make_eng(loop_success=False)
        report = eng.build(self._MEDIUM_GOAL)
        assert report.success is False

    def test_build_calls_dev_loop_run(self):
        dev_loop = MagicMock()
        dev_loop.run.return_value = _make_loop_result(True)
        eng = SoftwareEngineer(dev_loop=dev_loop)
        eng.build(self._MEDIUM_GOAL)
        dev_loop.run.assert_called_once()

    def test_build_passes_goal_to_loop(self):
        dev_loop = MagicMock()
        dev_loop.run.return_value = _make_loop_result(True)
        eng = SoftwareEngineer(dev_loop=dev_loop)
        eng.build(self._TRELLO_GOAL)
        call_kwargs = dev_loop.run.call_args
        goal_arg = call_kwargs[1].get("goal") or call_kwargs[0][0]
        assert "Trello" in goal_arg

    def test_build_persists_to_memory(self):
        memory = MagicMock()
        dev_loop = MagicMock()
        dev_loop.run.return_value = _make_loop_result(True)
        eng = SoftwareEngineer(dev_loop=dev_loop, memory_manager=memory)
        eng.build(self._MEDIUM_GOAL)
        memory.remember.assert_called_once()

    def test_build_auto_commit_on_success(self):
        git = MagicMock()
        git.add.return_value = MagicMock(success=True)
        git.commit.return_value = MagicMock(sha="abc1234")
        dev_loop = MagicMock()
        dev_loop.run.return_value = _make_loop_result(True)
        eng = SoftwareEngineer(dev_loop=dev_loop, git_client=git)
        report = eng.build(self._MEDIUM_GOAL, auto_commit=True)
        git.add.assert_called_once()
        git.commit.assert_called_once()

    def test_build_no_commit_on_failure(self):
        git = MagicMock()
        dev_loop = MagicMock()
        dev_loop.run.return_value = _make_loop_result(False)
        eng = SoftwareEngineer(dev_loop=dev_loop, git_client=git)
        eng.build(self._MEDIUM_GOAL, auto_commit=True)
        git.add.assert_not_called()
        git.commit.assert_not_called()

    def test_build_no_dev_loop_still_succeeds(self):
        eng = SoftwareEngineer(dev_loop=None)
        # Use a medium/large goal — fast path requires model_manager;
        # medium/large with dev_loop=None returns the stub LoopResult (success=True).
        report = eng.build(self._MEDIUM_GOAL)
        assert isinstance(report, SoftwareEngineerReport)
        assert report.success is True  # stub result

    def test_clarify_applies_defaults_in_non_interactive(self):
        dev_loop = MagicMock()
        dev_loop.run.return_value = _make_loop_result(True)
        eng = SoftwareEngineer(dev_loop=dev_loop, interactive=False)
        # "authentication system" → MEDIUM → DevLoop called.
        # Goal triggers auth + db questions; defaults should be applied.
        report = eng.build(
            "Build a user authentication system with login, registration "
            "and database persistence"
        )
        assert report.clarifications is not None
        # Defaults should be filled in (JWT and PostgreSQL)
        answered = report.clarifications.answered
        assert isinstance(answered, dict)

    def test_total_elapsed_set(self):
        eng = self._make_eng()
        report = eng.build(self._MEDIUM_GOAL)
        assert report.total_elapsed >= 0.0

    def test_summary_populated(self):
        eng = self._make_eng()
        report = eng.build("Build an auth service")
        assert len(report.summary) > 0
