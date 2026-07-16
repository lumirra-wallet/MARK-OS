"""Tests for smartagent.ui.commands.performance_cmd — v2.0 Phase 12."""

import pytest
from unittest.mock import MagicMock, patch

from smartagent.ui.commands.performance_cmd import (
    handle_performance,
    register,
    _show_cache_stats,
    _clear_cache,
)
from smartagent.ui.command_router import CommandRouter


def _agent(ctx=None):
    agent = MagicMock()
    agent.executive.last_context = ctx
    return agent


class TestHandlePerformance:
    def test_no_context_returns_message(self):
        agent = _agent(ctx=None)
        result = handle_performance([], agent)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_cache_subcommand(self):
        result = handle_performance(["cache"], _agent())
        assert isinstance(result, str)

    def test_clear_subcommand(self):
        result = handle_performance(["clear"], _agent())
        assert isinstance(result, str)

    def test_unknown_subcommand(self):
        result = handle_performance(["unknown"], _agent())
        assert "Unknown" in result or "unknown" in result.lower()

    def test_returns_string_always(self):
        for args in [[], ["cache"], ["clear"], ["bad"]]:
            result = handle_performance(args, _agent())
            assert isinstance(result, str)


class TestShowCacheStats:
    def test_returns_string(self):
        result = _show_cache_stats(None)
        assert isinstance(result, str)

    def test_contains_cache_info(self):
        result = _show_cache_stats(None)
        # Should mention cache or stats
        assert any(word in result.lower() for word in ["cache", "hit", "entr"])


class TestClearCache:
    def test_clears_and_returns_message(self):
        from smartagent.performance.worker_cache import get_global_cache
        cache = get_global_cache()
        cache.put("k", "v")
        result = _clear_cache(None)
        assert isinstance(result, str)
        assert len(cache) == 0

    def test_returns_string_even_if_empty(self):
        result = _clear_cache(None)
        assert isinstance(result, str)


class TestRegister:
    def test_registers_performance(self):
        router = CommandRouter()
        register(router)
        assert router.has_command("performance")
