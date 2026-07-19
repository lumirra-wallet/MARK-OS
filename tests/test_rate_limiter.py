"""Tests for smartagent.server.rate_limiter — Phase 6 (cost & safety control)."""

from __future__ import annotations

from unittest.mock import patch

from smartagent.server.rate_limiter import RateLimiter, get_run_rate_limiter


class TestRateLimiter:
    def test_allows_up_to_the_configured_max(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        assert rl.allow("ws") is True
        assert rl.allow("ws") is True
        assert rl.allow("ws") is True

    def test_blocks_once_max_is_reached(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            rl.allow("ws")
        assert rl.allow("ws") is False

    def test_different_keys_have_independent_limits(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        assert rl.allow("workspace-a") is True
        assert rl.allow("workspace-b") is True  # independent budget
        assert rl.allow("workspace-a") is False

    def test_window_expiry_allows_requests_again(self):
        rl = RateLimiter(max_requests=1, window_seconds=10)
        t = [1000.0]
        with patch("time.monotonic", side_effect=lambda: t[0]):
            assert rl.allow("ws") is True
            assert rl.allow("ws") is False
            t[0] += 11  # past the window
            assert rl.allow("ws") is True

    def test_reset_single_key(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("ws")
        assert rl.allow("ws") is False
        rl.reset("ws")
        assert rl.allow("ws") is True

    def test_reset_all(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("a")
        rl.allow("b")
        rl.reset()
        assert rl.allow("a") is True
        assert rl.allow("b") is True


class TestRunRateLimiterSingleton:
    def test_returns_same_instance(self):
        assert get_run_rate_limiter() is get_run_rate_limiter()
