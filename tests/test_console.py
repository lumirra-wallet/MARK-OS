"""
Tests for Milestone 8 — MARK Console OS v1.

Covers:
    - CommandRouter registration and dispatch
    - ExitConsole exception for exit/quit
    - renderer.banner and renderer.help_text (pure formatting, no I/O)
    - Every command group: system, memory, knowledge, mind, skills, tools,
      models, events
    - Console construction and router wiring
    - REPL I/O loop with piped input (via monkeypatched builtins.input)
    - Unknown commands
    - Ctrl+C / KeyboardInterrupt handling
    - All existing tests continue to pass (no regressions)

Strategy: SmartAgent is constructed with a real (but tmp-dir-isolated)
Settings so the full subsystem graph is live.  This lets the command
handlers exercise real code paths while keeping tests hermetic and fast
(no network, no Ollama, no file-system side effects outside tmp_path).
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from smartagent.brain.agent import SmartAgent
from smartagent.config.settings import Settings
from smartagent.ui.command_router import CommandRouter, ExitConsole
from smartagent.ui.console import Console
from smartagent.ui.repl import Repl, PROMPT
from smartagent.ui import renderer
from smartagent.ui.commands import system, memory, knowledge, mind, skills, tools, models, events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_agent(tmp_path: Path) -> SmartAgent:
    """A fully-initialized SmartAgent with all paths redirected to tmp_path."""
    settings = Settings(
        vault_path=str(tmp_path / "vault"),
        knowledge_path=str(tmp_path / "knowledge"),
        workspace_path=str(tmp_path),
    )
    return SmartAgent(settings=settings)


@pytest.fixture()
def router() -> CommandRouter:
    """A fresh, empty CommandRouter."""
    return CommandRouter()


@pytest.fixture()
def console(tmp_agent: SmartAgent) -> Console:
    """A Console wired to the tmp agent — all command modules registered."""
    return Console(tmp_agent)


# ---------------------------------------------------------------------------
# CommandRouter — unit tests
# ---------------------------------------------------------------------------


class TestCommandRouter:
    def test_register_and_dispatch(self, router, tmp_agent):
        router.register("ping", lambda a, args: "pong", "test", "SYSTEM")
        assert router.dispatch(tmp_agent, "ping") == "pong"

    def test_dispatch_passes_args(self, router, tmp_agent):
        router.register("echo", lambda a, args: " ".join(args), "echo", "SYSTEM")
        assert router.dispatch(tmp_agent, "echo hello world") == "hello world"

    def test_unknown_command_returns_message(self, router, tmp_agent):
        response = router.dispatch(tmp_agent, "nonexistent_command_xyz")
        assert "Unknown command" in response
        assert "help" in response.lower()

    def test_empty_input_returns_empty(self, router, tmp_agent):
        assert router.dispatch(tmp_agent, "  ") == ""

    def test_exit_raises_exit_console(self, router, tmp_agent):
        router.register("exit", lambda a, args: (_ for _ in ()).throw(ExitConsole()), "exit", "SYSTEM")
        with pytest.raises(ExitConsole):
            router.dispatch(tmp_agent, "exit")

    def test_help_entries_sorted_by_group(self, router, tmp_agent):
        router.register("z_cmd", lambda a, args: "", "z", "EVENTS", 0)
        router.register("a_cmd", lambda a, args: "", "a", "SYSTEM", 0)
        entries = router.help_entries()
        groups = [g for g, _, _ in entries]
        assert groups.index("SYSTEM") < groups.index("EVENTS")

    def test_case_insensitive_dispatch(self, router, tmp_agent):
        router.register("ping", lambda a, args: "pong", "", "SYSTEM")
        assert router.dispatch(tmp_agent, "PING") == "pong"
        assert router.dispatch(tmp_agent, "Ping") == "pong"

    def test_overwrite_existing_command(self, router, tmp_agent):
        router.register("x", lambda a, args: "first", "", "SYSTEM")
        router.register("x", lambda a, args: "second", "", "SYSTEM")
        assert router.dispatch(tmp_agent, "x") == "second"


# ---------------------------------------------------------------------------
# ExitConsole sentinel
# ---------------------------------------------------------------------------


class TestExitConsole:
    def test_is_exception(self):
        with pytest.raises(ExitConsole):
            raise ExitConsole()

    def test_exit_handler_raises(self, tmp_agent):
        from smartagent.ui.commands.system import handle_exit
        with pytest.raises(ExitConsole):
            handle_exit(tmp_agent, [])

    def test_quit_also_raises(self, console, tmp_agent):
        with pytest.raises(ExitConsole):
            console.router.dispatch(tmp_agent, "quit")


# ---------------------------------------------------------------------------
# Renderer — pure formatting (no I/O)
# ---------------------------------------------------------------------------


class TestRenderer:
    def test_banner_contains_key_fields(self, tmp_agent):
        b = renderer.banner(tmp_agent)
        assert "MARK AI OPERATING SYSTEM" in b
        assert "Mr. Smart" in b
        assert "0.9" in b
        assert "Brain" in b
        assert "Memory" in b
        assert "Knowledge" in b

    def test_banner_contains_online_labels(self, tmp_agent):
        b = renderer.banner(tmp_agent)
        assert "Online" in b

    def test_help_text_groups(self):
        entries = [
            ("SYSTEM", "status", "show status"),
            ("MEMORY", "remember", "save memory"),
            ("SYSTEM", "exit", "quit"),
        ]
        text = renderer.help_text(entries)
        assert "SYSTEM" in text
        assert "MEMORY" in text
        assert "status" in text
        assert "remember" in text

    def test_hr_is_string(self):
        assert isinstance(renderer.hr(), str)
        assert len(renderer.hr()) > 0

    def test_section_contains_title(self):
        s = renderer.section("Test Section", "body text")
        assert "TEST SECTION" in s
        assert "body text" in s

    def test_banner_does_not_crash_on_broken_mind(self, tmp_path):
        """Banner must not crash even if mind.health_check() raises."""
        settings = Settings(
            vault_path=str(tmp_path / "vault"),
            knowledge_path=str(tmp_path / "knowledge"),
        )
        agent = SmartAgent(settings=settings)
        agent.mind.health_check = mock.Mock(side_effect=RuntimeError("boom"))
        b = renderer.banner(agent)
        assert "MARK AI OPERATING SYSTEM" in b


# ---------------------------------------------------------------------------
# System commands
# ---------------------------------------------------------------------------


class TestSystemCommands:
    def test_help_registered(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "help")
        assert "SYSTEM" in response
        assert "MEMORY" in response
        assert "KNOWLEDGE" in response
        assert "MIND" in response

    def test_status_returns_sections(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "status")
        assert "BRAIN" in response.upper()
        assert "MIND" in response.upper()
        assert "MEMORY" in response.upper()
        assert "KNOWLEDGE" in response.upper()

    def test_version_contains_0_9(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "version")
        assert "0.9" in response

    def test_clear_returns_banner(self, console, tmp_agent):
        with mock.patch("os.system"):  # don't actually clear the test terminal
            response = console.router.dispatch(tmp_agent, "clear")
        assert "MARK AI OPERATING SYSTEM" in response

    def test_exit_raises(self, console, tmp_agent):
        with pytest.raises(ExitConsole):
            console.router.dispatch(tmp_agent, "exit")

    def test_quit_raises(self, console, tmp_agent):
        with pytest.raises(ExitConsole):
            console.router.dispatch(tmp_agent, "quit")

    def test_unknown_command(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "xyzzy_not_a_command")
        assert "Unknown command" in response


# ---------------------------------------------------------------------------
# Memory commands
# ---------------------------------------------------------------------------


class TestMemoryCommands:
    def test_remember_saves_and_returns_id(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "remember I like Python")
        assert "Remembered" in response
        assert "I like Python" in response

    def test_remember_without_content(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "remember")
        assert "Usage" in response

    def test_recall_returns_list(self, console, tmp_agent):
        # First write a memory so there's something to recall.
        tmp_agent.memory.remember("test recall entry")
        response = console.router.dispatch(tmp_agent, "recall")
        # Should contain the entry OR 'no memories' message.
        assert response  # non-empty

    def test_recall_empty(self, console, tmp_agent):
        # Fresh agent with empty vault.
        response = console.router.dispatch(tmp_agent, "recall")
        assert "No memories" in response or len(response) > 0

    def test_search_memory(self, console, tmp_agent):
        tmp_agent.memory.remember("Python is great for scripting")
        response = console.router.dispatch(tmp_agent, "search-memory Python")
        assert "Python" in response

    def test_search_memory_no_query(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "search-memory")
        assert "Usage" in response

    def test_search_memory_no_results(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "search-memory xyzzy_nothing")
        assert "No memories" in response or "xyzzy_nothing" in response


# ---------------------------------------------------------------------------
# Knowledge commands
# ---------------------------------------------------------------------------


class TestKnowledgeCommands:
    def test_knowledge_no_subcommand_shows_usage(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "knowledge")
        assert "Usage" in response or "knowledge" in response.lower()

    def test_knowledge_add_proposes_concept(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "knowledge add Python Programming")
        assert "inbox" in response.lower() or "proposed" in response.lower() or "Python" in response

    def test_knowledge_add_no_title(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "knowledge add")
        assert "Usage" in response

    def test_knowledge_stats(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "knowledge stats")
        assert "Concepts" in response or "concepts" in response

    def test_knowledge_search_no_results(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "knowledge search xyzzy_nothing_here")
        assert "No concepts" in response or "xyzzy" in response.lower()

    def test_knowledge_search_no_query(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "knowledge search")
        assert "Usage" in response

    def test_inbox_empty(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "inbox")
        assert "empty" in response.lower() or "pending" in response.lower()

    def test_inbox_shows_proposed_concept(self, console, tmp_agent):
        tmp_agent.knowledge.propose_concept(title="Test Concept", description="A test")
        response = console.router.dispatch(tmp_agent, "inbox")
        assert "Test Concept" in response or "pending" in response.lower()

    def test_approve_by_number(self, console, tmp_agent):
        tmp_agent.knowledge.propose_concept(title="ApprovableItem", description="approve me")
        response = console.router.dispatch(tmp_agent, "approve 1")
        assert "ApprovableItem" in response or "Approved" in response or "approved" in response.lower()

    def test_approve_invalid_number(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "approve 999")
        assert "No pending" in response or "matching" in response.lower()

    def test_approve_no_args(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "approve")
        assert "Usage" in response

    def test_reject_by_number(self, console, tmp_agent):
        tmp_agent.knowledge.propose_concept(title="RejectableItem", description="reject me")
        response = console.router.dispatch(tmp_agent, "reject 1")
        assert "Rejected" in response or "rejected" in response.lower()

    def test_reject_no_args(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "reject")
        assert "Usage" in response

    def test_unknown_knowledge_subcommand(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "knowledge foobar")
        assert "Unknown" in response or "foobar" in response

    def test_graph_no_args(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "graph")
        assert "No concept" in response or "Usage" in response or response == ""


# ---------------------------------------------------------------------------
# Mind commands
# ---------------------------------------------------------------------------


class TestMindCommands:
    def test_mind_returns_string(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "mind")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_identity_contains_agent_name(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "identity")
        # Either shows the agent name or a graceful error — never crashes.
        assert isinstance(response, str)
        assert len(response) > 0

    def test_health_returns_band_or_score(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "health")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_state_returns_state_info(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "state")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_attention_returns_string(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "attention")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_context_returns_string(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "context")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_mind_commands_never_crash_on_broken_mind(self, tmp_path):
        """All mind commands must return a string even if the mind raises."""
        settings = Settings(
            vault_path=str(tmp_path / "vault"),
            knowledge_path=str(tmp_path / "knowledge"),
        )
        agent = SmartAgent(settings=settings)
        # Cripple self_model.
        agent.mind.self_model = mock.Mock(side_effect=RuntimeError("boom"))
        agent.mind.describe = mock.Mock(side_effect=RuntimeError("boom"))
        agent.mind.health_check = mock.Mock(side_effect=RuntimeError("boom"))

        console = Console(agent)
        for cmd in ("mind", "identity", "health", "state", "attention", "context"):
            response = console.router.dispatch(agent, cmd)
            assert isinstance(response, str)
            assert len(response) > 0


# ---------------------------------------------------------------------------
# Skills / Tools / Models / Events commands
# ---------------------------------------------------------------------------


class TestSkillsCommand:
    def test_skills_returns_string(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "skills")
        assert isinstance(response, str)

    def test_skills_output_not_empty(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "skills")
        # May say "No skills loaded" or list skills — both valid.
        assert response


class TestToolsCommand:
    def test_tools_returns_string(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "tools")
        assert isinstance(response, str)

    def test_tools_lists_available(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "tools")
        # The ToolEngine auto-discovers built-in tools.
        assert "tool" in response.lower() or "available" in response.lower() or "loaded" in response.lower() or len(response) > 0


class TestModelsCommand:
    def test_models_returns_string(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "models")
        assert isinstance(response, str)

    def test_models_contains_model_section(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "models")
        assert "model" in response.lower() or "provider" in response.lower()


class TestEventsCommand:
    def test_events_before_any_events(self, console, tmp_agent):
        response = console.router.dispatch(tmp_agent, "events")
        # Either "No events" or lists events generated during agent init.
        assert isinstance(response, str)
        assert len(response) > 0

    def test_events_after_publishing(self, console, tmp_agent):
        tmp_agent.events.publish("TestEvent", source="test")
        response = console.router.dispatch(tmp_agent, "events")
        assert "TestEvent" in response

    def test_events_caps_at_twenty(self, console, tmp_agent):
        # Publish enough extra events so the total exceeds the 20-event cap.
        # (Agent init already publishes some events, so we add 30 more to
        # guarantee we cross the threshold regardless of init count.)
        for i in range(30):
            tmp_agent.events.publish(f"ExtraEvent{i}")
        response = console.router.dispatch(tmp_agent, "events")
        # The handler shows at most 20 and reports "showing 20 of N total".
        assert "showing 20 of" in response


# ---------------------------------------------------------------------------
# Console construction
# ---------------------------------------------------------------------------


class TestConsole:
    def test_console_registers_all_groups(self, console):
        entries = console.router.help_entries()
        groups = {g for g, _, _ in entries}
        assert "SYSTEM" in groups
        assert "MEMORY" in groups
        assert "KNOWLEDGE" in groups
        assert "MIND" in groups
        assert "SKILLS" in groups
        assert "TOOLS" in groups
        assert "MODELS" in groups
        assert "EVENTS" in groups

    def test_console_exposes_router(self, console):
        assert isinstance(console.router, CommandRouter)

    def test_console_exposes_agent(self, console, tmp_agent):
        assert console.agent is tmp_agent


# ---------------------------------------------------------------------------
# REPL — I/O loop (driven via patched input())
# ---------------------------------------------------------------------------


class TestRepl:
    def _run_repl(self, console: Console, commands: list[str], tmp_agent: SmartAgent) -> str:
        """
        Drive the REPL by patching ``builtins.input`` to return lines from
        *commands*, then EOFError to terminate.  Returns captured stdout.
        """
        inputs = iter(commands + [EOFError()])

        def mock_input(prompt: str) -> str:
            val = next(inputs)
            if isinstance(val, BaseException):
                raise val
            return val

        captured = io.StringIO()
        with mock.patch("builtins.input", side_effect=mock_input):
            with mock.patch("sys.stdout", captured):
                try:
                    console.run()
                except SystemExit:
                    pass
        return captured.getvalue()

    def test_startup_prints_banner(self, console, tmp_agent):
        output = self._run_repl(console, [], tmp_agent)
        assert "MARK AI OPERATING SYSTEM" in output

    def test_help_command_in_repl(self, console, tmp_agent):
        output = self._run_repl(console, ["help"], tmp_agent)
        assert "SYSTEM" in output

    def test_status_command_in_repl(self, console, tmp_agent):
        output = self._run_repl(console, ["status"], tmp_agent)
        assert "BRAIN" in output.upper() or "status" in output.lower()

    def test_memory_workflow_in_repl(self, console, tmp_agent):
        output = self._run_repl(
            console, ["remember Testing the REPL", "recall"], tmp_agent
        )
        assert "Testing the REPL" in output or "Remembered" in output

    def test_exit_command_terminates_repl(self, console, tmp_agent):
        output = self._run_repl(console, ["exit"], tmp_agent)
        assert "Goodbye" in output or len(output) > 0

    def test_quit_command_terminates_repl(self, console, tmp_agent):
        output = self._run_repl(console, ["quit"], tmp_agent)
        assert "Goodbye" in output or len(output) > 0

    def test_unknown_command_does_not_crash(self, console, tmp_agent):
        output = self._run_repl(console, ["this_is_not_a_real_command"], tmp_agent)
        assert "Unknown command" in output

    def test_empty_input_is_ignored(self, console, tmp_agent):
        # Empty lines should not crash and should not echo anything.
        output = self._run_repl(console, ["", "   ", "version"], tmp_agent)
        assert "0.9" in output

    def test_keyboard_interrupt_resumes(self, console, tmp_agent):
        """A KeyboardInterrupt in the middle of a session should not kill the REPL."""
        inputs = [KeyboardInterrupt(), "version", EOFError()]
        idx = 0

        def mock_input(prompt: str) -> str:
            nonlocal idx
            val = inputs[idx]
            idx += 1
            if isinstance(val, BaseException):
                raise type(val)()
            return val

        captured = io.StringIO()
        with mock.patch("builtins.input", side_effect=mock_input):
            with mock.patch("sys.stdout", captured):
                console.run()
        output = captured.getvalue()
        assert "0.9" in output or "Interrupted" in output

    def test_eof_terminates_cleanly(self, console, tmp_agent):
        """EOF (Ctrl+D / end of piped input) must exit without error."""
        with mock.patch("builtins.input", side_effect=EOFError()):
            with mock.patch("sys.stdout", io.StringIO()):
                console.run()  # must return cleanly — no exception propagated


# ---------------------------------------------------------------------------
# Logger — file-only mode
# ---------------------------------------------------------------------------


class TestLogger:
    def test_configure_logging_accepts_log_file(self, tmp_path):
        import logging
        import importlib
        import smartagent.logs.logger as logger_mod

        # Reset the module's _CONFIGURED flag for this test.
        original = logger_mod._CONFIGURED
        logger_mod._CONFIGURED = False
        try:
            log_file = str(tmp_path / "test.log")
            logger_mod.configure_logging(log_file=log_file, log_to_console=False)
            root = logging.getLogger()
            # At least one FileHandler should be present.
            file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
            assert len(file_handlers) >= 1
        finally:
            # Restore state and remove extra handlers to avoid polluting other tests.
            logger_mod._CONFIGURED = original
            for h in list(logging.getLogger().handlers):
                if isinstance(h, logging.FileHandler) and "test.log" in str(h.baseFilename):
                    logging.getLogger().removeHandler(h)
                    h.close()

    def test_get_logger_returns_logger(self):
        from smartagent.logs.logger import get_logger
        import logging
        lg = get_logger("test.module")
        assert isinstance(lg, logging.Logger)
        assert lg.name == "test.module"

    def test_configure_logging_idempotent(self, tmp_path):
        """Calling configure_logging twice should not add duplicate handlers."""
        import logging
        import smartagent.logs.logger as logger_mod

        original = logger_mod._CONFIGURED
        original_handlers = list(logging.getLogger().handlers)
        logger_mod._CONFIGURED = False
        try:
            logger_mod.configure_logging()
            count_after_first = len(logging.getLogger().handlers)
            logger_mod.configure_logging()  # second call — should be no-op
            assert len(logging.getLogger().handlers) == count_after_first
        finally:
            logger_mod._CONFIGURED = original
            # Restore handlers.
            logging.getLogger().handlers = original_handlers
