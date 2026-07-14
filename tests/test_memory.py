"""
Tests for `MemoryManager`.

These currently assert against the in-memory placeholder implementation
and will need updating once persistent/semantic backends are added.
"""

from smartagent.memory.memory_manager import MemoryManager


def test_remember_and_recall_returns_stored_entry():
    memory = MemoryManager()
    memory.remember("The user's favorite color is blue.")
    results = memory.recall("favorite color")
    assert len(results) == 1
    assert results[0]["content"] == "The user's favorite color is blue."


def test_recall_respects_limit():
    memory = MemoryManager()
    for i in range(10):
        memory.remember(f"fact {i}")
    results = memory.recall("fact", limit=3)
    assert len(results) == 3


def test_clear_removes_all_entries():
    memory = MemoryManager()
    memory.remember("something")
    memory.clear()
    assert memory.recall("something") == []
