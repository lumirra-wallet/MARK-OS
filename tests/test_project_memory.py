"""
Tests for Milestone 22: Project Memory.

Coverage:
    ProjectProfile:
      · to_dict / from_dict round-trip
      · to_json / from_json round-trip
      · touch() sets created_at and updated_at
      · as_ai_context() formats correctly
      · as_display_lines() includes all set fields

    ProjectMemory:
      · load() creates a new profile when none exists
      · load() reads an existing profile from disk
      · save() writes a JSON file to disk
      · set() known fields (language, framework, test_runner, etc.)
      · set() special key "tool" appends and deduplicates
      · set() special key "note" appends
      · set() unknown key → stored in preferences
      · get() reads known fields
      · get() reads from preferences
      · get() returns "" for unset fields
      · scan() detects Python from .py files
      · scan() detects pytest from conftest.py
      · scan() detects framework from requirements.txt content
      · scan() handles missing path gracefully
      · list_projects() returns all saved profiles sorted by name
      · delete() removes a profile
      · delete() returns False for non-existent profile
      · inject_into_context() populates metadata dict
      · summary() returns a non-empty string
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from smartagent.project_memory.project_profile import ProjectProfile
from smartagent.project_memory.project_memory import ProjectMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_pm(tmp_path):
    """A ProjectMemory instance backed by a temp directory."""
    return ProjectMemory(base_path=str(tmp_path))


@pytest.fixture
def blank_profile():
    return ProjectProfile(name="test-project", path="/tmp/test-project")


# ---------------------------------------------------------------------------
# ProjectProfile
# ---------------------------------------------------------------------------

class TestProjectProfile:
    def test_to_dict_from_dict_round_trip(self, blank_profile):
        blank_profile.language = "Python"
        blank_profile.framework = "FastAPI"
        blank_profile.test_runner = "pytest"
        d = blank_profile.to_dict()
        restored = ProjectProfile.from_dict(d)
        assert restored.language == "Python"
        assert restored.framework == "FastAPI"
        assert restored.test_runner == "pytest"
        assert restored.name == blank_profile.name

    def test_to_json_from_json_round_trip(self, blank_profile):
        blank_profile.database = "PostgreSQL"
        blank_profile.tools = ["black", "ruff"]
        txt = blank_profile.to_json()
        restored = ProjectProfile.from_json(txt)
        assert restored.database == "PostgreSQL"
        assert restored.tools == ["black", "ruff"]

    def test_touch_sets_timestamps(self, blank_profile):
        assert blank_profile.created_at == ""
        blank_profile.touch()
        assert blank_profile.created_at != ""
        assert blank_profile.updated_at != ""

    def test_touch_keeps_created_at(self, blank_profile):
        blank_profile.touch()
        first = blank_profile.created_at
        blank_profile.touch()
        assert blank_profile.created_at == first  # unchanged

    def test_as_ai_context_contains_fields(self, blank_profile):
        blank_profile.language = "Python"
        blank_profile.framework = "Django"
        blank_profile.test_runner = "pytest"
        blank_profile.database = "PostgreSQL"
        ctx = blank_profile.as_ai_context()
        assert "Python" in ctx
        assert "Django" in ctx
        assert "pytest" in ctx
        assert "PostgreSQL" in ctx

    def test_as_ai_context_includes_preferences(self, blank_profile):
        blank_profile.preferences["prefers_async"] = "true"
        ctx = blank_profile.as_ai_context()
        assert "prefers_async" in ctx

    def test_as_display_lines_populated(self, blank_profile):
        blank_profile.language = "Python"
        blank_profile.framework = "FastAPI"
        lines = blank_profile.as_display_lines()
        assert any("Python" in l for l in lines)
        assert any("FastAPI" in l for l in lines)

    def test_as_display_lines_notes(self, blank_profile):
        blank_profile.notes = ["Uses alembic for migrations."]
        lines = blank_profile.as_display_lines()
        assert any("alembic" in l for l in lines)


# ---------------------------------------------------------------------------
# ProjectMemory — load / save
# ---------------------------------------------------------------------------

class TestProjectMemoryLoadSave:
    def test_load_creates_new_profile(self, tmp_pm, tmp_path):
        profile = tmp_pm.load("new-project", str(tmp_path))
        assert profile.name == "new-project"
        assert profile.language == ""  # nothing detected yet

    def test_save_writes_json_file(self, tmp_pm, tmp_path):
        profile = tmp_pm.load("my-api", str(tmp_path))
        profile.language = "Python"
        tmp_pm.save(profile)
        fpath = os.path.join(str(tmp_pm._base_path), "my-api.json")
        assert os.path.exists(fpath)
        data = json.loads(open(fpath).read())
        assert data["language"] == "Python"

    def test_load_reads_existing_profile(self, tmp_pm, tmp_path):
        profile = tmp_pm.load("persisted", str(tmp_path))
        profile.framework = "FastAPI"
        tmp_pm.save(profile)
        # Load again
        loaded = tmp_pm.load("persisted", str(tmp_path))
        assert loaded.framework == "FastAPI"

    def test_load_updates_path_if_empty(self, tmp_pm, tmp_path):
        # First save with empty path
        profile = tmp_pm.load("path-test")
        profile.language = "Python"
        tmp_pm.save(profile)
        # Reload with a path
        loaded = tmp_pm.load("path-test", str(tmp_path))
        assert loaded.path == str(tmp_path)


# ---------------------------------------------------------------------------
# ProjectMemory — set / get
# ---------------------------------------------------------------------------

class TestProjectMemorySetGet:
    def test_set_known_field_language(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "language", "Python")
        assert blank_profile.language == "Python"

    def test_set_known_field_framework(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "framework", "FastAPI")
        assert blank_profile.framework == "FastAPI"

    def test_set_known_field_test_runner(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "test_runner", "pytest")
        assert blank_profile.test_runner == "pytest"

    def test_set_known_field_package_manager(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "package_manager", "poetry")
        assert blank_profile.package_manager == "poetry"

    def test_set_known_field_database(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "database", "PostgreSQL")
        assert blank_profile.database == "PostgreSQL"

    def test_set_known_field_style_checker(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "style_checker", "black")
        assert blank_profile.style_checker == "black"

    def test_set_tool_appends(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "tool", "black")
        tmp_pm.set(blank_profile, "tool", "ruff")
        assert "black" in blank_profile.tools
        assert "ruff" in blank_profile.tools

    def test_set_tool_no_duplicates(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "tool", "black")
        tmp_pm.set(blank_profile, "tool", "black")
        assert blank_profile.tools.count("black") == 1

    def test_set_note_appends(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "note", "Uses alembic")
        tmp_pm.set(blank_profile, "note", "Async everywhere")
        assert "Uses alembic" in blank_profile.notes
        assert "Async everywhere" in blank_profile.notes

    def test_set_unknown_key_goes_to_preferences(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "prefers_async", "true")
        assert blank_profile.preferences.get("prefers_async") == "true"

    def test_set_hyphenated_key(self, tmp_pm, blank_profile):
        tmp_pm.set(blank_profile, "prefers-async", "true")
        assert blank_profile.preferences.get("prefers_async") == "true"

    def test_get_known_field(self, tmp_pm, blank_profile):
        blank_profile.language = "Go"
        assert tmp_pm.get(blank_profile, "language") == "Go"

    def test_get_preference(self, tmp_pm, blank_profile):
        blank_profile.preferences["debug"] = "verbose"
        assert tmp_pm.get(blank_profile, "debug") == "verbose"

    def test_get_missing_returns_empty(self, tmp_pm, blank_profile):
        assert tmp_pm.get(blank_profile, "nonexistent_key") == ""

    def test_get_tools(self, tmp_pm, blank_profile):
        blank_profile.tools = ["black", "ruff"]
        result = tmp_pm.get(blank_profile, "tools")
        assert "black" in result
        assert "ruff" in result


# ---------------------------------------------------------------------------
# ProjectMemory — scan
# ---------------------------------------------------------------------------

class TestProjectMemoryScan:
    def test_scan_detects_python(self, tmp_pm, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        profile = tmp_pm.load("scan-py", str(tmp_path))
        tmp_pm.scan(profile)
        assert profile.language == "Python"

    def test_scan_detects_pytest_from_conftest(self, tmp_pm, tmp_path):
        (tmp_path / "conftest.py").write_text("import pytest")
        profile = tmp_pm.load("scan-pytest", str(tmp_path))
        tmp_pm.scan(profile)
        assert profile.test_runner == "pytest"

    def test_scan_detects_poetry(self, tmp_pm, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]")
        profile = tmp_pm.load("scan-poetry", str(tmp_path))
        tmp_pm.scan(profile)
        assert profile.package_manager == "poetry"

    def test_scan_detects_fastapi_from_requirements(self, tmp_pm, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
        (tmp_path / "app.py").write_text("from fastapi import FastAPI")
        profile = tmp_pm.load("scan-fastapi", str(tmp_path))
        tmp_pm.scan(profile)
        assert profile.framework == "FastAPI"

    def test_scan_detects_postgres_from_requirements(self, tmp_pm, tmp_path):
        (tmp_path / "requirements.txt").write_text("psycopg2-binary\n")
        profile = tmp_pm.load("scan-pg", str(tmp_path))
        tmp_pm.scan(profile)
        assert "PostgreSQL" in profile.database

    def test_scan_handles_missing_path(self, tmp_pm):
        profile = ProjectProfile(name="missing", path="/does/not/exist")
        result = tmp_pm.scan(profile)
        assert any("path" in r.lower() or "not exist" in r.lower() for r in result)

    def test_scan_returns_detected_list(self, tmp_pm, tmp_path):
        (tmp_path / "main.py").write_text("pass")
        profile = tmp_pm.load("scan-list", str(tmp_path))
        detected = tmp_pm.scan(profile)
        assert isinstance(detected, list)
        assert len(detected) >= 1

    def test_scan_no_signals_returns_no_new_message(self, tmp_pm, tmp_path):
        # Empty directory — nothing to detect
        profile = tmp_pm.load("empty-project", str(tmp_path))
        result = tmp_pm.scan(profile)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# ProjectMemory — list / delete
# ---------------------------------------------------------------------------

class TestProjectMemoryListDelete:
    def test_list_empty(self, tmp_pm):
        assert tmp_pm.list_projects() == []

    def test_list_returns_saved_profiles(self, tmp_pm, tmp_path):
        for name in ["alpha", "beta", "gamma"]:
            p = tmp_pm.load(name, str(tmp_path))
            tmp_pm.save(p)
        projects = tmp_pm.list_projects()
        names = [p.name for p in projects]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names

    def test_list_sorted_by_name(self, tmp_pm, tmp_path):
        for name in ["zz", "aa", "mm"]:
            p = tmp_pm.load(name)
            tmp_pm.save(p)
        projects = tmp_pm.list_projects()
        names = [p.name for p in projects]
        assert names == sorted(names)

    def test_delete_existing(self, tmp_pm, tmp_path):
        p = tmp_pm.load("to-delete")
        tmp_pm.save(p)
        assert tmp_pm.delete("to-delete") is True
        assert tmp_pm.list_projects() == []

    def test_delete_nonexistent(self, tmp_pm):
        assert tmp_pm.delete("does-not-exist") is False


# ---------------------------------------------------------------------------
# ProjectMemory — helpers
# ---------------------------------------------------------------------------

class TestProjectMemoryHelpers:
    def test_inject_into_context(self, tmp_pm, blank_profile):
        blank_profile.language = "Python"
        meta: dict = {}
        tmp_pm.inject_into_context(blank_profile, meta)
        assert "project_profile" in meta
        assert "project_ai_context" in meta
        assert "Python" in meta["project_ai_context"]

    def test_summary_returns_string(self, tmp_pm, blank_profile):
        blank_profile.language = "Python"
        blank_profile.framework = "FastAPI"
        s = tmp_pm.summary(blank_profile)
        assert isinstance(s, str)
        assert len(s) > 0

    def test_ai_context_delegates_to_profile(self, tmp_pm, blank_profile):
        blank_profile.language = "Rust"
        ctx = tmp_pm.ai_context(blank_profile)
        assert "Rust" in ctx
