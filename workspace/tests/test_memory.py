"""
Tests for `MemoryManager` (Memory v1: persistent Markdown vault).

Every test points `MemoryManager` at an isolated temporary vault (via
pytest's `tmp_path`) so tests never read/write the project's real `vault/`
directory and stay independent of each other.
"""

from smartagent.memory.memory_manager import MemoryManager


def _manager(tmp_path):
    return MemoryManager(vault_path=str(tmp_path / "vault"))


def test_remember_writes_a_markdown_file(tmp_path):
    memory = _manager(tmp_path)
    entry = memory.remember("The user's favorite color is blue.", category="Personal")

    md_path = tmp_path / "vault" / "Personal" / f"{entry.id}.md"
    assert md_path.exists()

    text = md_path.read_text(encoding="utf-8")
    assert "The user's favorite color is blue." in text
    assert f"id: {entry.id}" in text
    assert "category: Personal" in text


def test_remember_generates_metadata(tmp_path):
    memory = _manager(tmp_path)
    entry = memory.remember("Ship the invoice by Friday.", category="Business", tags=["billing", "urgent"])

    assert entry.id  # unique id was generated
    assert entry.category == "Business"
    assert entry.tags == ["billing", "urgent"]
    assert entry.created_at and entry.updated_at


def test_recall_returns_entry_by_id(tmp_path):
    memory = _manager(tmp_path)
    entry = memory.remember("Remember to water the plants.")

    recalled = memory.recall(entry.id)
    assert recalled is not None
    assert recalled.content == "Remember to water the plants."


def test_recall_missing_id_returns_none(tmp_path):
    memory = _manager(tmp_path)
    assert memory.recall("does-not-exist") is None


def test_search_finds_matching_content(tmp_path):
    memory = _manager(tmp_path)
    memory.remember("The user's favorite color is blue.", category="Personal")
    memory.remember("The project deadline is next month.", category="Projects")

    results = memory.search("favorite color")
    assert len(results) == 1
    assert "blue" in results[0].content


def test_search_matches_tags_and_respects_limit(tmp_path):
    memory = _manager(tmp_path)
    for i in range(10):
        memory.remember(f"fact {i}", tags=["trivia"])

    results = memory.search("trivia", limit=3)
    assert len(results) == 3


def test_search_can_scope_to_a_category(tmp_path):
    memory = _manager(tmp_path)
    memory.remember("Personal note about hobbies.", category="Personal")
    memory.remember("Business note about invoices.", category="Business")

    results = memory.search("note", category="Business")
    assert len(results) == 1
    assert results[0].category == "Business"


def test_update_changes_content_and_bumps_timestamp(tmp_path):
    memory = _manager(tmp_path)
    entry = memory.remember("Old content.")

    updated = memory.update(entry.id, content="New content.", tags=["revised"])
    assert updated is not None
    assert updated.content == "New content."
    assert updated.tags == ["revised"]
    assert updated.updated_at >= entry.created_at

    # The change must be persisted to disk, not just held in memory.
    reloaded = memory.recall(entry.id)
    assert reloaded.content == "New content."


def test_update_missing_id_returns_none(tmp_path):
    memory = _manager(tmp_path)
    assert memory.update("does-not-exist", content="anything") is None


def test_delete_removes_the_memory(tmp_path):
    memory = _manager(tmp_path)
    entry = memory.remember("Temporary note.")

    assert memory.delete(entry.id) is True
    assert memory.recall(entry.id) is None


def test_delete_missing_id_returns_false(tmp_path):
    memory = _manager(tmp_path)
    assert memory.delete("does-not-exist") is False


def test_list_categories_includes_default_vault_structure(tmp_path):
    memory = _manager(tmp_path)
    categories = memory.list_categories()

    for expected in ["Personal", "Business", "Projects", "Knowledge", "Research", "Journal", "Archive"]:
        assert expected in categories


def test_clear_removes_all_entries(tmp_path):
    memory = _manager(tmp_path)
    memory.remember("something")
    memory.clear()
    assert memory.search("something") == []


def test_persistence_after_restart(tmp_path):
    """
    A new `MemoryManager` pointed at the same vault path must see memories
    written by a previous instance — this is the core guarantee that makes
    the vault "persistent" rather than the old in-memory placeholder.
    """
    vault_path = str(tmp_path / "vault")

    first = MemoryManager(vault_path=vault_path)
    entry = first.remember("The user's favorite color is blue.", category="Personal", tags=["preference"])
    del first  # simulate the process ending

    second = MemoryManager(vault_path=vault_path)
    recalled = second.recall(entry.id)
    assert recalled is not None
    assert recalled.content == "The user's favorite color is blue."
    assert recalled.tags == ["preference"]

    results = second.search("favorite color")
    assert len(results) == 1
    assert results[0].id == entry.id
