"""
Tests for smartagent.server.conversation_store — B3 (Awareness fix).

Covers: workspace_id() stability, append_turn()/get_history()/recent_turns()
round-tripping through a fake in-memory StorageProvider, trimming to
_MAX_TURNS, and the workspace-analysis cache's TTL behavior.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from smartagent.server import conversation_store


class _FakeStorage:
    """Minimal in-memory stand-in for StorageProvider — enough for get/set."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, object]] = {}

    def get(self, namespace: str, key: str):
        return self._data.get(namespace, {}).get(key)

    def get_or_default(self, namespace: str, key: str, default):
        val = self.get(namespace, key)
        return val if val is not None else default

    def set(self, namespace: str, key: str, value) -> None:
        self._data.setdefault(namespace, {})[key] = value


@pytest.fixture
def fake_storage():
    store = _FakeStorage()
    with patch("smartagent.server.conversation_store.get_storage", return_value=store):
        yield store


class TestWorkspaceId:
    def test_stable_for_same_path(self):
        assert conversation_store.workspace_id("/a/b") == conversation_store.workspace_id("/a/b")

    def test_differs_for_different_paths(self):
        assert conversation_store.workspace_id("/a/b") != conversation_store.workspace_id("/a/c")

    def test_is_short_hex_string(self):
        wid = conversation_store.workspace_id("/some/path")
        assert len(wid) == 16
        int(wid, 16)  # raises if not valid hex


class TestHistoryRoundTrip:
    def test_empty_history_for_new_workspace(self, fake_storage):
        assert conversation_store.get_history("/tmp/ws") == []

    def test_append_then_get(self, fake_storage):
        conversation_store.append_turn("/tmp/ws", "user", "hi")
        conversation_store.append_turn("/tmp/ws", "assistant", "hello")
        history = conversation_store.get_history("/tmp/ws")
        assert history == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_different_workspaces_are_isolated(self, fake_storage):
        conversation_store.append_turn("/tmp/a", "user", "goal A")
        conversation_store.append_turn("/tmp/b", "user", "goal B")
        assert conversation_store.get_history("/tmp/a") == [{"role": "user", "content": "goal A"}]
        assert conversation_store.get_history("/tmp/b") == [{"role": "user", "content": "goal B"}]

    def test_trims_to_max_turns(self, fake_storage):
        for i in range(conversation_store._MAX_TURNS + 10):
            conversation_store.append_turn("/tmp/ws", "user", f"turn {i}")
        history = conversation_store.get_history("/tmp/ws")
        assert len(history) == conversation_store._MAX_TURNS
        # Oldest turns dropped, newest kept
        assert history[-1]["content"] == f"turn {conversation_store._MAX_TURNS + 9}"

    def test_recent_turns_respects_limit(self, fake_storage):
        for i in range(20):
            conversation_store.append_turn("/tmp/ws", "user", f"turn {i}")
        recent = conversation_store.recent_turns("/tmp/ws", limit=3)
        assert len(recent) == 3
        assert recent[-1]["content"] == "turn 19"

    def test_recent_turns_zero_limit_returns_empty(self, fake_storage):
        conversation_store.append_turn("/tmp/ws", "user", "hi")
        assert conversation_store.recent_turns("/tmp/ws", limit=0) == []


class TestWorkspaceContextCache:
    def setup_method(self):
        conversation_store._workspace_cache.clear()

    def test_uncached_returns_none(self):
        assert conversation_store.get_cached_workspace_context("/tmp/never-cached") is None

    def test_cached_value_is_returned(self):
        conversation_store.cache_workspace_context("/tmp/ws", {"project_type": "Python"})
        assert conversation_store.get_cached_workspace_context("/tmp/ws") == {"project_type": "Python"}

    def test_expired_entry_returns_none(self):
        conversation_store.cache_workspace_context("/tmp/ws", {"project_type": "Python"})
        with patch("smartagent.server.conversation_store.time.monotonic", return_value=1e12):
            assert conversation_store.get_cached_workspace_context("/tmp/ws") is None
