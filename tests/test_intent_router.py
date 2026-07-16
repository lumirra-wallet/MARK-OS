"""
Tests for smartagent.ui.commands.intent_router — v2.0 intent classification.

Verifies that:
- Engineering tasks are classified as "engineer"
- Conversational input is classified as "chat"
- The fallback handler routes correctly
- The performance_cmd signature fix works
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from smartagent.ui.commands.intent_router import (
    classify_intent,
    intent_aware_fallback,
)


# ---------------------------------------------------------------------------
# classify_intent — engineering tasks
# ---------------------------------------------------------------------------

class TestEngineeringClassification:
    """All of these should return 'engineer'."""

    def test_create_landing_page(self):
        assert classify_intent("create a landing page") == "engineer"

    def test_build_fastapi(self):
        assert classify_intent("build a FastAPI REST API") == "engineer"

    def test_create_hello_py(self):
        assert classify_intent("create hello.py") == "engineer"

    def test_add_login_authentication(self):
        assert classify_intent("add login authentication") == "engineer"

    def test_fix_failing_tests(self):
        assert classify_intent("fix failing tests") == "engineer"

    def test_refactor_the_project(self):
        assert classify_intent("refactor the project") == "engineer"

    def test_write_python_script(self):
        assert classify_intent("write a Python script") == "engineer"

    def test_build_api(self):
        assert classify_intent("build an API") == "engineer"

    def test_create_website(self):
        assert classify_intent("create a website") == "engineer"

    def test_add_feature(self):
        assert classify_intent("add a new feature") == "engineer"

    def test_generate_tests(self):
        assert classify_intent("generate tests for the auth module") == "engineer"

    def test_fix_bug(self):
        assert classify_intent("fix the bug in the login form") == "engineer"

    def test_implement_auth(self):
        assert classify_intent("implement JWT authentication") == "engineer"

    def test_create_file_with_ext(self):
        assert classify_intent("create main.ts") == "engineer"

    def test_write_js_file(self):
        assert classify_intent("write a JavaScript module") == "engineer"

    def test_build_rest_api(self):
        assert classify_intent("build a REST API with FastAPI") == "engineer"

    def test_make_dashboard(self):
        assert classify_intent("make a dashboard") == "engineer"

    def test_develop_backend(self):
        assert classify_intent("develop the backend service") == "engineer"

    def test_setup_database(self):
        assert classify_intent("setup a database") == "engineer"

    def test_configure_auth(self):
        assert classify_intent("configure authentication middleware") == "engineer"

    def test_deploy_app(self):
        assert classify_intent("deploy the application") == "engineer"

    def test_create_app(self):
        assert classify_intent("create a Python app") == "engineer"

    def test_update_model(self):
        assert classify_intent("update the user model") == "engineer"

    def test_write_tests(self):
        assert classify_intent("write tests for the API") == "engineer"

    def test_create_html_file(self):
        assert classify_intent("create index.html") == "engineer"

    def test_generate_class(self):
        assert classify_intent("generate a class for user management") == "engineer"

    def test_refactor_code(self):
        assert classify_intent("refactor the authentication code") == "engineer"

    def test_edit_config(self):
        assert classify_intent("edit the config file") == "engineer"

    def test_implement_feature(self):
        assert classify_intent("implement the payment feature") == "engineer"

    def test_build_cli(self):
        assert classify_intent("build a CLI tool") == "engineer"

    def test_create_docker(self):
        assert classify_intent("create a Dockerfile") == "engineer"

    def test_migrate_database(self):
        assert classify_intent("migrate the database") == "engineer"

    def test_add_endpoint(self):
        assert classify_intent("add a new endpoint for user registration") == "engineer"

    def test_fix_tests(self):
        assert classify_intent("fix the failing unit tests") == "engineer"

    def test_update_schema(self):
        assert classify_intent("update the database schema") == "engineer"

    def test_build_saas(self):
        assert classify_intent("build a SaaS platform") == "engineer"

    def test_remove_bug(self):
        assert classify_intent("remove the bug in the payment module") == "engineer"

    def test_extend_api(self):
        assert classify_intent("extend the API with pagination") == "engineer"

    def test_create_microservice(self):
        assert classify_intent("create a microservice for notifications") == "engineer"

    def test_install_package(self):
        assert classify_intent("install the requests package") == "engineer"


# ---------------------------------------------------------------------------
# classify_intent — chat / conversational
# ---------------------------------------------------------------------------

class TestChatClassification:
    """All of these should return 'chat'."""

    def test_what_is_rest_api(self):
        assert classify_intent("what is a REST API?") == "chat"

    def test_how_does_python_work(self):
        assert classify_intent("how does Python work") == "chat"

    def test_explain_authentication(self):
        assert classify_intent("explain authentication") == "chat"

    def test_what_are_microservices(self):
        assert classify_intent("what are microservices") == "chat"

    def test_why_use_docker(self):
        assert classify_intent("why use Docker") == "chat"

    def test_who_invented_python(self):
        assert classify_intent("who invented Python") == "chat"

    def test_when_was_python_released(self):
        assert classify_intent("when was Python released") == "chat"

    def test_describe_jwt(self):
        assert classify_intent("describe JWT tokens") == "chat"

    def test_tell_me_about_graphql(self):
        assert classify_intent("tell me about GraphQL") == "chat"

    def test_what_does_flask_do(self):
        assert classify_intent("what does Flask do") == "chat"

    def test_can_you_explain_oauth(self):
        assert classify_intent("can you explain OAuth") == "chat"

    def test_how_to_learn_python(self):
        assert classify_intent("how to learn Python") == "chat"

    def test_question_mark(self):
        assert classify_intent("is FastAPI better than Flask?") == "chat"

    def test_compare_frameworks(self):
        assert classify_intent("compare Django and Flask") == "chat"

    def test_what_is_graphql(self):
        assert classify_intent("what is GraphQL") == "chat"

    def test_how_does_jwt_work(self):
        assert classify_intent("how does JWT authentication work") == "chat"

    def test_summarize_docker(self):
        assert classify_intent("summarize what Docker does") == "chat"

    def test_list_python_frameworks(self):
        assert classify_intent("list popular Python frameworks") == "chat"

    def test_empty_string(self):
        assert classify_intent("") == "chat"

    def test_whitespace(self):
        assert classify_intent("   ") == "chat"

    def test_what_is_with_code(self):
        # "what" starter trumps engineering nouns
        assert classify_intent("what is the best way to build an API") == "chat"

    def test_explain_how_to_fix(self):
        # "explain" phrase pattern catches this
        assert classify_intent("explain how to fix this bug") == "chat"

    def test_help_me_understand(self):
        # "help" is a chat starter
        assert classify_intent("help me understand authentication") == "chat"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_returns_string(self):
        result = classify_intent("create a REST API")
        assert isinstance(result, str)
        assert result in ("engineer", "chat")

    def test_case_insensitive_verb(self):
        assert classify_intent("CREATE a Python script") == "engineer"

    def test_case_insensitive_noun(self):
        assert classify_intent("build a REST API") == "engineer"

    def test_single_word_unknown(self):
        # A single unrecognized word defaults to chat
        result = classify_intent("xyzzy")
        assert result == "chat"

    def test_verb_alone_no_noun_is_chat(self):
        # verb without an artifact noun or file extension → chat
        result = classify_intent("create")
        assert result == "chat"


# ---------------------------------------------------------------------------
# intent_aware_fallback routing
# ---------------------------------------------------------------------------

class TestIntentAwareFallback:
    def _agent(self):
        agent = MagicMock()
        agent.model_manager.active_model_id = "llama3:8b"
        return agent

    def test_engineering_input_calls_handle_engineer(self):
        """Engineering input should route to handle_engineer, not the model."""
        agent = self._agent()
        with patch(
            "smartagent.ui.commands.intent_router.classify_intent",
            return_value="engineer",
        ), patch(
            "smartagent.ui.commands.engineer_cmd.handle_engineer",
            return_value="Engineer result",
        ) as mock_eng:
            result = intent_aware_fallback(agent, "create hello.py")
        mock_eng.assert_called_once()
        assert result == "Engineer result"

    def test_chat_input_calls_fallback_chat(self):
        """Chat input should route to fallback_chat, not the engineer."""
        agent = self._agent()
        with patch(
            "smartagent.ui.commands.intent_router.classify_intent",
            return_value="chat",
        ), patch(
            "smartagent.ui.commands.models.fallback_chat",
            return_value="Chat response",
        ) as mock_chat:
            result = intent_aware_fallback(agent, "what is Python?")
        mock_chat.assert_called_once_with(agent, "what is Python?")
        assert result == "Chat response"

    def test_engineer_routing_passes_raw_as_args(self):
        """The full raw input is split into args for handle_engineer."""
        agent = self._agent()
        captured_args = []
        def fake_engineer(a, args):
            captured_args.extend(args)
            return "ok"

        with patch(
            "smartagent.ui.commands.intent_router.classify_intent",
            return_value="engineer",
        ), patch(
            "smartagent.ui.commands.engineer_cmd.handle_engineer",
            side_effect=fake_engineer,
        ):
            intent_aware_fallback(agent, "create hello.py")

        assert captured_args == ["create", "hello.py"]

    def test_returns_string(self):
        agent = self._agent()
        with patch(
            "smartagent.ui.commands.intent_router.classify_intent",
            return_value="chat",
        ), patch(
            "smartagent.ui.commands.models.fallback_chat",
            return_value="response",
        ):
            result = intent_aware_fallback(agent, "hello")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Console integration — fallback is registered as intent_aware_fallback
# ---------------------------------------------------------------------------

class TestConsoleIntegration:
    def test_console_uses_intent_router_as_fallback(self):
        """Console should register intent_aware_fallback, not fallback_chat."""
        from smartagent.brain.agent import SmartAgent
        from smartagent.ui.console import Console
        from unittest.mock import MagicMock

        agent = MagicMock(spec=SmartAgent)
        agent.settings = MagicMock()
        agent.settings.get = MagicMock(return_value=None)
        agent.model_manager = MagicMock()
        agent.model_manager.active_model_id = None
        agent.executive = MagicMock()
        agent.mind = MagicMock()
        agent.memory = MagicMock()
        agent.tools = MagicMock()
        agent.skills = MagicMock()
        agent.goals = MagicMock()
        agent.events = MagicMock()

        console = Console(agent)
        # The fallback should be the intent_aware_fallback function
        assert console.router._fallback is not None
        assert console.router._fallback.__name__ == "intent_aware_fallback"


# ---------------------------------------------------------------------------
# performance_cmd signature fix
# ---------------------------------------------------------------------------

class TestPerformanceCmdSignature:
    """Verify handle_performance(agent, args) signature is correct."""

    def test_no_args_does_not_crash(self):
        from smartagent.ui.commands.performance_cmd import handle_performance
        agent = MagicMock()
        agent.executive = None
        result = handle_performance(agent, [])
        assert isinstance(result, str)

    def test_cache_subcommand(self):
        from smartagent.ui.commands.performance_cmd import handle_performance
        agent = MagicMock()
        result = handle_performance(agent, ["cache"])
        assert isinstance(result, str)

    def test_clear_subcommand(self):
        from smartagent.ui.commands.performance_cmd import handle_performance
        agent = MagicMock()
        result = handle_performance(agent, ["clear"])
        assert isinstance(result, str)

    def test_command_router_calls_correctly(self):
        """CommandRouter calls handler(agent, args) — verify handle_performance matches."""
        from smartagent.ui.commands.performance_cmd import handle_performance
        import inspect
        sig = inspect.signature(handle_performance)
        params = list(sig.parameters.keys())
        assert params[0] == "agent"
        assert params[1] == "args"
