"""
Tests for Milestone 4 — Tool Engine v1.

Covers:
    - New Permission enum additions (5 tool-specific permissions)
    - ToolCategory / ToolStatus / ToolMetadata shape
    - BaseTool contract (via minimal concrete dummy)
    - PathValidator (workspace sandboxing, protected-source guard)
    - SafetyError
    - ToolRegistry (all operations: register, unregister, find, list, reload,
      enable, disable, health_check, statistics, get [legacy], list_available)
    - ToolLoader (discover_tool_classes — finds all 15 built-ins, handles bad pkg)
    - ToolEngine (run, permission denial, unknown tool, disabled tool,
      invalid params, load_tools, list_available, health_check, events)
    - All 15 built-in tools (validate + execute happy/sad paths)
    - Integration via SmartAgent (tools in SkillContext, tools_handler reporting)

Design decisions preserved:
    - No databases, no AI model calls, no internet access.
    - All filesystem tool tests use an isolated tmp_path so the real vault/
      and project source are never touched.
    - Permission grants are explicit and minimal in each test — no global grants.
"""

from __future__ import annotations

import hashlib
import uuid as uuid_module
from pathlib import Path
from typing import Any

import pytest

from smartagent.brain.action_result import ActionResult
from smartagent.brain.agent import SmartAgent
from smartagent.brain.events import EventBus, Events
from smartagent.config.settings import Settings
from smartagent.skills.permissions import Permission, PermissionManager
from smartagent.tools.base_tool import BaseTool, ToolCategory, ToolContext, ToolMetadata, ToolStatus
from smartagent.tools.builtin.filesystem.copy_file_tool import CopyFileTool
from smartagent.tools.builtin.filesystem.delete_file_tool import DeleteFileTool
from smartagent.tools.builtin.filesystem.directory_create_tool import DirectoryCreateTool
from smartagent.tools.builtin.filesystem.directory_list_tool import DirectoryListTool
from smartagent.tools.builtin.filesystem.file_read_tool import FileReadTool
from smartagent.tools.builtin.filesystem.file_write_tool import FileWriteTool
from smartagent.tools.builtin.filesystem.move_file_tool import MoveFileTool
from smartagent.tools.builtin.filesystem.search_files_tool import SearchFilesTool
from smartagent.tools.builtin.system.date_time_tool import DateTimeTool
from smartagent.tools.builtin.system.environment_tool import EnvironmentTool
from smartagent.tools.builtin.system.system_info_tool import SystemInfoTool
from smartagent.tools.builtin.text.open_text_file_tool import OpenTextFileTool
from smartagent.tools.builtin.text.read_markdown_tool import ReadMarkdownTool
from smartagent.tools.builtin.utilities.hash_tool import HashTool
from smartagent.tools.builtin.utilities.uuid_tool import UUIDTool
from smartagent.tools.safety import PathValidator, SafetyError
from smartagent.tools.tool_engine import ToolEngine
from smartagent.tools.tool_loader import discover_tool_classes
from smartagent.tools.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(tmp_path: Path) -> Settings:
    s = Settings.load()
    s.vault_path = str(tmp_path / "vault")
    s.workspace_path = str(tmp_path)
    return s


def _agent(tmp_path: Path) -> SmartAgent:
    return SmartAgent(settings=_settings(tmp_path))


def _tool_context(tmp_path: Path) -> ToolContext:
    """Minimal ToolContext for unit-testing individual tools."""
    return ToolContext(
        settings=_settings(tmp_path),
        workspace_path=str(tmp_path),
        events=EventBus(),
    )


def _all_perms() -> PermissionManager:
    """PermissionManager with every permission granted — for integration tests."""
    return PermissionManager(granted=list(Permission))


def _engine(tmp_path: Path, *, grant: list[Permission] | None = None) -> ToolEngine:
    """Build a ToolEngine with specified granted permissions (default: none)."""
    perms = PermissionManager(granted=grant or [])
    return ToolEngine(permissions=perms)


def _engine_loaded(tmp_path: Path, *, grant: list[Permission] | None = None) -> ToolEngine:
    """Build a ToolEngine with all built-in tools loaded."""
    engine = _engine(tmp_path, grant=grant)
    engine.load_tools()
    return engine


# ---------------------------------------------------------------------------
# Minimal concrete BaseTool for unit testing BaseTool / ToolRegistry / Engine
# ---------------------------------------------------------------------------

class _DummyTool(BaseTool):
    """Concrete BaseTool that always succeeds — used for infrastructure tests."""

    @property
    def id(self) -> str:
        return "dummy_tool"

    @property
    def name(self) -> str:
        return "Dummy Tool"

    @property
    def description(self) -> str:
        return "Does nothing; used only for tests."

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def author(self) -> str:
        return "Test Suite"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.UTILITIES

    def validate(self, params: dict[str, Any]) -> bool:
        return True

    def execute(self, params: dict[str, Any], context: ToolContext) -> ActionResult:
        return ActionResult(success=True, message="dummy ok", source=self.id)


class _PermissionedTool(_DummyTool):
    """A dummy tool that requires READ_FILES permission."""

    @property
    def id(self) -> str:
        return "permissioned_tool"

    @property
    def permissions(self) -> tuple[Permission, ...]:
        return (Permission.READ_FILES,)


class _ValidatedTool(_DummyTool):
    """A dummy tool whose validate() requires a 'key' param."""

    @property
    def id(self) -> str:
        return "validated_tool"

    def validate(self, params: dict[str, Any]) -> bool:
        return bool(params.get("key"))


# ---------------------------------------------------------------------------
# 1. New Permission enum values (Milestone 4 additions)
# ---------------------------------------------------------------------------

class TestMilestone4Permissions:
    def test_read_files_value(self):
        assert Permission.READ_FILES.value == "read_files"

    def test_write_files_value(self):
        assert Permission.WRITE_FILES.value == "write_files"

    def test_delete_files_value(self):
        assert Permission.DELETE_FILES.value == "delete_files"

    def test_create_directories_value(self):
        assert Permission.CREATE_DIRECTORIES.value == "create_directories"

    def test_read_system_info_value(self):
        assert Permission.READ_SYSTEM_INFO.value == "read_system_info"

    def test_new_permissions_grantable(self):
        pm = PermissionManager()
        pm.grant(Permission.READ_FILES)
        pm.grant(Permission.WRITE_FILES)
        pm.grant(Permission.DELETE_FILES)
        pm.grant(Permission.CREATE_DIRECTORIES)
        pm.grant(Permission.READ_SYSTEM_INFO)
        assert pm.is_granted(Permission.READ_FILES)
        assert pm.is_granted(Permission.WRITE_FILES)
        assert pm.is_granted(Permission.READ_SYSTEM_INFO)


# ---------------------------------------------------------------------------
# 2. ToolCategory / ToolStatus / ToolMetadata
# ---------------------------------------------------------------------------

class TestToolCategory:
    def test_all_categories_are_strings(self):
        for cat in ToolCategory:
            assert isinstance(cat.value, str)

    def test_expected_categories_exist(self):
        values = {c.value for c in ToolCategory}
        assert {"filesystem", "system", "utilities", "text", "future"}.issubset(values)


class TestToolStatus:
    def test_enabled_value(self):
        assert ToolStatus.ENABLED.value == "enabled"

    def test_disabled_value(self):
        assert ToolStatus.DISABLED.value == "disabled"


class TestToolMetadata:
    def test_metadata_is_frozen(self):
        tool = _DummyTool()
        meta = tool.metadata()
        assert isinstance(meta, ToolMetadata)
        with pytest.raises((AttributeError, TypeError)):
            meta.id = "changed"  # type: ignore[misc]

    def test_metadata_fields_match_tool(self):
        tool = _DummyTool()
        meta = tool.metadata()
        assert meta.id == tool.id
        assert meta.name == tool.name
        assert meta.version == tool.version
        assert meta.author == tool.author
        assert meta.category == tool.category


# ---------------------------------------------------------------------------
# 3. BaseTool
# ---------------------------------------------------------------------------

class TestBaseTool:
    def test_default_permissions_empty(self):
        assert _DummyTool().permissions == ()

    def test_default_required_os_empty(self):
        assert _DummyTool().required_os == ()

    def test_default_required_dependencies_empty(self):
        assert _DummyTool().required_dependencies == ()

    def test_enabled_true_by_default(self):
        assert _DummyTool().enabled is True

    def test_status_enabled_by_default(self):
        assert _DummyTool().status() == ToolStatus.ENABLED

    def test_initialize_is_noop(self):
        _DummyTool().initialize()  # must not raise

    def test_shutdown_is_noop(self):
        _DummyTool().shutdown()  # must not raise

    def test_health_returns_dict_with_expected_keys(self, tmp_path):
        h = _DummyTool().health()
        assert "id" in h and "status" in h and "healthy" in h

    def test_health_reports_healthy(self):
        assert _DummyTool().health()["healthy"] is True


# ---------------------------------------------------------------------------
# 4. PathValidator & SafetyError
# ---------------------------------------------------------------------------

class TestPathValidator:
    def test_relative_path_within_workspace_ok(self, tmp_path):
        v = PathValidator(str(tmp_path))
        result = v.resolve_safe("subdir/file.txt")
        assert result == (tmp_path / "subdir" / "file.txt").resolve()

    def test_absolute_path_within_workspace_ok(self, tmp_path):
        v = PathValidator(str(tmp_path))
        target = tmp_path / "file.txt"
        assert v.resolve_safe(str(target)) == target.resolve()

    def test_path_escaping_workspace_raises(self, tmp_path):
        v = PathValidator(str(tmp_path))
        with pytest.raises(SafetyError):
            v.resolve_safe("../../etc/passwd")

    def test_path_pointing_to_parent_raises(self, tmp_path):
        v = PathValidator(str(tmp_path))
        with pytest.raises(SafetyError):
            v.resolve_safe("..")

    def test_check_not_protected_source_smartagent(self, tmp_path):
        v = PathValidator(str(tmp_path))
        dangerous = tmp_path / "smartagent" / "core.py"
        with pytest.raises(SafetyError):
            v.check_not_protected_source(dangerous)

    def test_check_not_protected_source_tests(self, tmp_path):
        v = PathValidator(str(tmp_path))
        dangerous = tmp_path / "tests" / "test_foo.py"
        with pytest.raises(SafetyError):
            v.check_not_protected_source(dangerous)

    def test_safe_path_passes_source_check(self, tmp_path):
        v = PathValidator(str(tmp_path))
        safe = tmp_path / "data" / "notes.txt"
        v.check_not_protected_source(safe)  # must not raise

    def test_workspace_property(self, tmp_path):
        v = PathValidator(str(tmp_path))
        assert v.workspace == tmp_path.resolve()


# ---------------------------------------------------------------------------
# 5. ToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_register_tool_findable(self):
        reg = ToolRegistry()
        tool = _DummyTool()
        reg.register(tool)
        assert reg.find("dummy_tool") is tool

    def test_unregister_removes_tool(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        reg.unregister("dummy_tool")
        assert reg.find("dummy_tool") is None

    def test_unregister_nonexistent_is_noop(self):
        reg = ToolRegistry()
        reg.unregister("nonexistent")  # must not raise

    def test_list_enabled_only_default(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        assert len(reg.list()) == 1

    def test_list_all_includes_disabled(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        reg.disable("dummy_tool")
        assert len(reg.list(enabled_only=False)) == 1
        assert len(reg.list(enabled_only=True)) == 0

    def test_list_by_category(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        assert len(reg.list(category=ToolCategory.UTILITIES)) == 1
        assert len(reg.list(category=ToolCategory.FILESYSTEM)) == 0

    def test_enable_returns_true_for_known(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        assert reg.enable("dummy_tool") is True

    def test_enable_returns_false_for_unknown(self):
        reg = ToolRegistry()
        assert reg.enable("nobody") is False

    def test_disable_returns_true_for_known(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        assert reg.disable("dummy_tool") is True

    def test_disable_returns_false_for_unknown(self):
        reg = ToolRegistry()
        assert reg.disable("nobody") is False

    def test_disable_then_enable_cycle(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        reg.disable("dummy_tool")
        assert not reg.is_enabled("dummy_tool")
        reg.enable("dummy_tool")
        assert reg.is_enabled("dummy_tool")

    def test_reload_returns_fresh_instance(self):
        reg = ToolRegistry()
        original = _DummyTool()
        reg.register(original)
        fresh = reg.reload("dummy_tool")
        assert fresh is not original
        assert fresh is not None

    def test_reload_preserves_disabled_status(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        reg.disable("dummy_tool")
        reg.reload("dummy_tool")
        assert not reg.is_enabled("dummy_tool")

    def test_reload_unknown_returns_none(self):
        reg = ToolRegistry()
        assert reg.reload("nobody") is None

    def test_health_check_structure(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        report = reg.health_check()
        assert "healthy" in report
        assert "tools" in report
        assert "dummy_tool" in report["tools"]

    def test_statistics_counts(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        reg.register(_PermissionedTool())
        reg.disable("dummy_tool")
        stats = reg.statistics()
        assert stats["total"] == 2
        assert stats["enabled"] == 1
        assert stats["disabled"] == 1

    def test_record_execution_increments_count(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        reg.record_execution("dummy_tool")
        reg.record_execution("dummy_tool")
        assert reg.statistics()["execution_counts"]["dummy_tool"] == 2

    def test_list_available_backward_compat(self):
        reg = ToolRegistry()
        reg.register(_DummyTool())
        assert "dummy_tool" in reg.list_available()

    # Legacy (Milestone 1) backward-compat tests are preserved in test_tools.py
    # (the original file). These confirm the NEW registry also works for legacy.


# ---------------------------------------------------------------------------
# 6. ToolLoader
# ---------------------------------------------------------------------------

class TestToolLoader:
    def test_discovers_all_15_builtin_tools(self):
        classes = discover_tool_classes()
        assert len(classes) == 15

    def test_no_abstract_classes_discovered(self):
        import inspect
        for cls in discover_tool_classes():
            assert not inspect.isabstract(cls), f"{cls.__name__} is abstract"

    def test_all_discovered_are_base_tool_subclasses(self):
        for cls in discover_tool_classes():
            assert issubclass(cls, BaseTool)

    def test_bad_package_returns_empty(self):
        result = discover_tool_classes("smartagent.tools.does_not_exist")
        assert result == []

    def test_tool_ids_are_unique(self):
        ids = [cls().id for cls in discover_tool_classes()]
        assert len(ids) == len(set(ids))

    def test_expected_tool_ids_present(self):
        ids = {cls().id for cls in discover_tool_classes()}
        expected = {
            "file_read", "file_write", "directory_create", "directory_list",
            "copy_file", "move_file", "delete_file", "search_files",
            "open_text_file", "read_markdown",
            "system_info", "date_time", "environment_info",
            "uuid_generate", "hash_compute",
        }
        assert expected == ids


# ---------------------------------------------------------------------------
# 7. ToolEngine
# ---------------------------------------------------------------------------

class TestToolEngine:
    def test_run_known_tool_succeeds(self, tmp_path):
        engine = _engine(tmp_path)
        engine.register(_DummyTool())
        ctx = _tool_context(tmp_path)
        result = engine.run("dummy_tool", ctx)
        assert result.success is True

    def test_run_unknown_tool_returns_failure(self, tmp_path):
        engine = _engine(tmp_path)
        ctx = _tool_context(tmp_path)
        result = engine.run("no_such_tool", ctx)
        assert result.success is False
        assert "no_such_tool" in result.message.lower() or "no tool" in result.message.lower()

    def test_run_without_required_permission_returns_failure(self, tmp_path):
        engine = _engine(tmp_path, grant=[])
        engine.register(_PermissionedTool())
        ctx = _tool_context(tmp_path)
        result = engine.run("permissioned_tool", ctx)
        assert result.success is False
        assert "read_files" in result.message

    def test_run_with_permission_succeeds(self, tmp_path):
        engine = _engine(tmp_path, grant=[Permission.READ_FILES])
        engine.register(_PermissionedTool())
        ctx = _tool_context(tmp_path)
        result = engine.run("permissioned_tool", ctx)
        assert result.success is True

    def test_run_with_invalid_params_returns_failure(self, tmp_path):
        engine = _engine(tmp_path)
        engine.register(_ValidatedTool())
        ctx = _tool_context(tmp_path)
        result = engine.run("validated_tool", ctx)  # no 'key' param
        assert result.success is False

    def test_run_disabled_tool_returns_failure(self, tmp_path):
        engine = _engine(tmp_path)
        engine.register(_DummyTool())
        engine.registry.disable("dummy_tool")
        ctx = _tool_context(tmp_path)
        result = engine.run("dummy_tool", ctx)
        assert result.success is False
        assert "disabled" in result.message.lower()

    def test_load_tools_registers_all_builtins(self, tmp_path):
        engine = _engine(tmp_path)
        loaded = engine.load_tools()
        assert len(loaded) == 15

    def test_list_available_after_load(self, tmp_path):
        engine = _engine_loaded(tmp_path)
        assert len(engine.list_available()) == 15

    def test_health_check_returns_dict(self, tmp_path):
        engine = _engine(tmp_path)
        engine.register(_DummyTool())
        report = engine.health_check()
        assert "healthy" in report

    def test_tool_executed_event_published(self, tmp_path):
        bus = EventBus()
        engine = ToolEngine(permissions=_all_perms(), event_bus=bus)
        engine.register(_DummyTool())
        ctx = _tool_context(tmp_path)
        engine.run("dummy_tool", ctx)
        events = [e for e in bus.history() if e.name == Events.TOOL_EXECUTED]
        assert len(events) == 1
        assert events[0].payload["tool_id"] == "dummy_tool"
        assert events[0].payload["success"] is True

    def test_tool_loaded_event_published(self, tmp_path):
        bus = EventBus()
        engine = ToolEngine(permissions=_all_perms(), event_bus=bus)
        engine.register(_DummyTool())
        events = [e for e in bus.history() if e.name == Events.TOOL_LOADED]
        assert len(events) == 1

    def test_source_set_on_result(self, tmp_path):
        engine = _engine(tmp_path)
        engine.register(_DummyTool())
        result = engine.run("dummy_tool", _tool_context(tmp_path))
        assert result.source == "dummy_tool"

    def test_execution_count_incremented(self, tmp_path):
        engine = _engine(tmp_path)
        engine.register(_DummyTool())
        ctx = _tool_context(tmp_path)
        engine.run("dummy_tool", ctx)
        engine.run("dummy_tool", ctx)
        stats = engine.registry.statistics()
        assert stats["execution_counts"]["dummy_tool"] == 2

    def test_describe_no_tools(self, tmp_path):
        engine = _engine(tmp_path)
        assert "No tools" in engine.describe()

    def test_describe_with_tools(self, tmp_path):
        engine = _engine_loaded(tmp_path)
        desc = engine.describe()
        assert "15" in desc


# ---------------------------------------------------------------------------
# 8. Built-in tools
# ---------------------------------------------------------------------------

class TestFileReadTool:
    def test_read_existing_file(self, tmp_path):
        (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")
        ctx = _tool_context(tmp_path)
        result = FileReadTool().execute({"path": "hello.txt"}, ctx)
        assert result.success
        assert "hello world" in result.message

    def test_read_missing_file_returns_failure(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = FileReadTool().execute({"path": "missing.txt"}, ctx)
        assert not result.success
        assert "not found" in result.message.lower()

    def test_read_directory_returns_failure(self, tmp_path):
        (tmp_path / "adir").mkdir()
        ctx = _tool_context(tmp_path)
        result = FileReadTool().execute({"path": "adir"}, ctx)
        assert not result.success

    def test_path_outside_workspace_rejected(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = FileReadTool().execute({"path": "../../etc/passwd"}, ctx)
        assert not result.success

    def test_validate_requires_path(self):
        assert FileReadTool().validate({}) is False
        assert FileReadTool().validate({"path": "x.txt"}) is True

    def test_result_data_contains_path_and_size(self, tmp_path):
        (tmp_path / "f.txt").write_text("abc", encoding="utf-8")
        ctx = _tool_context(tmp_path)
        result = FileReadTool().execute({"path": "f.txt"}, ctx)
        assert result.data["size_bytes"] == 3


class TestFileWriteTool:
    def test_write_new_file(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = FileWriteTool().execute({"path": "out.txt", "content": "saved"}, ctx)
        assert result.success
        assert (tmp_path / "out.txt").read_text() == "saved"

    def test_write_existing_no_overwrite(self, tmp_path):
        (tmp_path / "exist.txt").write_text("original")
        ctx = _tool_context(tmp_path)
        result = FileWriteTool().execute(
            {"path": "exist.txt", "content": "new", "overwrite": False}, ctx
        )
        assert not result.success
        assert (tmp_path / "exist.txt").read_text() == "original"

    def test_write_existing_with_overwrite(self, tmp_path):
        (tmp_path / "exist.txt").write_text("original")
        ctx = _tool_context(tmp_path)
        result = FileWriteTool().execute(
            {"path": "exist.txt", "content": "updated", "overwrite": True}, ctx
        )
        assert result.success
        assert (tmp_path / "exist.txt").read_text() == "updated"

    def test_write_creates_parent_dirs(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = FileWriteTool().execute(
            {"path": "a/b/c.txt", "content": "nested"}, ctx
        )
        assert result.success
        assert (tmp_path / "a" / "b" / "c.txt").read_text() == "nested"

    def test_path_outside_workspace_rejected(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = FileWriteTool().execute({"path": "../../evil.txt", "content": "x"}, ctx)
        assert not result.success

    def test_validate_requires_path_and_content(self):
        assert FileWriteTool().validate({}) is False
        assert FileWriteTool().validate({"path": "x"}) is False
        assert FileWriteTool().validate({"path": "x", "content": ""}) is True


class TestDirectoryCreateTool:
    def test_create_directory(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DirectoryCreateTool().execute({"path": "newdir"}, ctx)
        assert result.success
        assert (tmp_path / "newdir").is_dir()

    def test_create_nested_directory(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DirectoryCreateTool().execute({"path": "a/b/c"}, ctx)
        assert result.success
        assert (tmp_path / "a" / "b" / "c").is_dir()

    def test_already_exists_is_success(self, tmp_path):
        (tmp_path / "existing").mkdir()
        ctx = _tool_context(tmp_path)
        result = DirectoryCreateTool().execute({"path": "existing"}, ctx)
        assert result.success

    def test_outside_workspace_rejected(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DirectoryCreateTool().execute({"path": "../../danger"}, ctx)
        assert not result.success

    def test_validate_requires_path(self):
        assert DirectoryCreateTool().validate({}) is False


class TestDirectoryListTool:
    def test_list_directory(self, tmp_path):
        (tmp_path / "file.txt").write_text("x")
        (tmp_path / "sub").mkdir()
        ctx = _tool_context(tmp_path)
        result = DirectoryListTool().execute({"path": "."}, ctx)
        assert result.success
        names = [item["name"] for item in result.data["items"]]
        assert "file.txt" in names
        assert "sub" in names

    def test_list_missing_directory(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DirectoryListTool().execute({"path": "no_such_dir"}, ctx)
        assert not result.success

    def test_list_file_as_directory_returns_failure(self, tmp_path):
        (tmp_path / "f.txt").write_text("x")
        ctx = _tool_context(tmp_path)
        result = DirectoryListTool().execute({"path": "f.txt"}, ctx)
        assert not result.success

    def test_result_data_has_items(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DirectoryListTool().execute({"path": "."}, ctx)
        assert "items" in result.data
        assert "path" in result.data


class TestCopyFileTool:
    def test_copy_file(self, tmp_path):
        (tmp_path / "src.txt").write_text("content")
        ctx = _tool_context(tmp_path)
        result = CopyFileTool().execute({"src": "src.txt", "dst": "dst.txt"}, ctx)
        assert result.success
        assert (tmp_path / "dst.txt").read_text() == "content"
        assert (tmp_path / "src.txt").exists()  # original unchanged

    def test_copy_missing_src_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = CopyFileTool().execute({"src": "ghost.txt", "dst": "out.txt"}, ctx)
        assert not result.success

    def test_copy_no_overwrite_protection(self, tmp_path):
        (tmp_path / "src.txt").write_text("x")
        (tmp_path / "dst.txt").write_text("existing")
        ctx = _tool_context(tmp_path)
        result = CopyFileTool().execute(
            {"src": "src.txt", "dst": "dst.txt", "overwrite": False}, ctx
        )
        assert not result.success
        assert (tmp_path / "dst.txt").read_text() == "existing"

    def test_validate_requires_src_and_dst(self):
        assert CopyFileTool().validate({}) is False
        assert CopyFileTool().validate({"src": "a"}) is False
        assert CopyFileTool().validate({"src": "a", "dst": "b"}) is True


class TestMoveFileTool:
    def test_move_file(self, tmp_path):
        (tmp_path / "src.txt").write_text("hello")
        ctx = _tool_context(tmp_path)
        result = MoveFileTool().execute({"src": "src.txt", "dst": "moved.txt"}, ctx)
        assert result.success
        assert (tmp_path / "moved.txt").read_text() == "hello"
        assert not (tmp_path / "src.txt").exists()

    def test_move_missing_src_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = MoveFileTool().execute({"src": "ghost.txt", "dst": "out.txt"}, ctx)
        assert not result.success

    def test_validate_requires_src_and_dst(self):
        assert MoveFileTool().validate({}) is False
        assert MoveFileTool().validate({"src": "a", "dst": "b"}) is True


class TestDeleteFileTool:
    def test_delete_file(self, tmp_path):
        f = tmp_path / "del.txt"
        f.write_text("gone")
        ctx = _tool_context(tmp_path)
        result = DeleteFileTool().execute({"path": "del.txt"}, ctx)
        assert result.success
        assert not f.exists()

    def test_delete_missing_file_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DeleteFileTool().execute({"path": "ghost.txt"}, ctx)
        assert not result.success

    def test_delete_protected_source_directory_rejected(self, tmp_path):
        (tmp_path / "smartagent").mkdir()
        (tmp_path / "smartagent" / "code.py").write_text("x")
        ctx = _tool_context(tmp_path)
        result = DeleteFileTool().execute({"path": "smartagent/code.py"}, ctx)
        assert not result.success
        assert (tmp_path / "smartagent" / "code.py").exists()  # untouched

    def test_delete_protected_tests_dir_rejected(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("x")
        ctx = _tool_context(tmp_path)
        result = DeleteFileTool().execute({"path": "tests/test_foo.py"}, ctx)
        assert not result.success

    def test_validate_requires_path(self):
        assert DeleteFileTool().validate({}) is False
        assert DeleteFileTool().validate({"path": "x"}) is True


class TestSearchFilesTool:
    def test_search_finds_matching_files(self, tmp_path):
        (tmp_path / "a.md").write_text("x")
        (tmp_path / "b.md").write_text("x")
        (tmp_path / "c.txt").write_text("x")
        ctx = _tool_context(tmp_path)
        result = SearchFilesTool().execute({"pattern": "*.md"}, ctx)
        assert result.success
        assert result.data["count"] == 2
        assert all(m.endswith(".md") for m in result.data["matches"])

    def test_search_no_results(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = SearchFilesTool().execute({"pattern": "*.xyz"}, ctx)
        assert result.success
        assert result.data["count"] == 0

    def test_search_recursive(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "deep.py").write_text("x")
        ctx = _tool_context(tmp_path)
        result = SearchFilesTool().execute({"pattern": "**/*.py"}, ctx)
        assert result.success
        assert result.data["count"] >= 1

    def test_search_missing_directory_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = SearchFilesTool().execute({"pattern": "*.md", "directory": "no_dir"}, ctx)
        assert not result.success

    def test_validate_requires_pattern(self):
        assert SearchFilesTool().validate({}) is False
        assert SearchFilesTool().validate({"pattern": "*.txt"}) is True


class TestOpenTextFileTool:
    def test_read_text_file_with_metadata(self, tmp_path):
        (tmp_path / "doc.txt").write_text("line1\nline2\n", encoding="utf-8")
        ctx = _tool_context(tmp_path)
        result = OpenTextFileTool().execute({"path": "doc.txt"}, ctx)
        assert result.success
        assert "line1" in result.message
        assert result.data["line_count"] == 2

    def test_read_missing_file_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = OpenTextFileTool().execute({"path": "nope.txt"}, ctx)
        assert not result.success

    def test_validate_requires_path(self):
        assert OpenTextFileTool().validate({}) is False
        assert OpenTextFileTool().validate({"path": "x"}) is True


class TestReadMarkdownTool:
    def test_read_markdown_parses_headings(self, tmp_path):
        content = "# Title\n\nSome text.\n\n## Section\n\nMore text.\n"
        (tmp_path / "README.md").write_text(content, encoding="utf-8")
        ctx = _tool_context(tmp_path)
        result = ReadMarkdownTool().execute({"path": "README.md"}, ctx)
        assert result.success
        headings = result.data["headings"]
        assert len(headings) == 2
        assert headings[0] == {"level": 1, "text": "Title"}
        assert headings[1] == {"level": 2, "text": "Section"}

    def test_non_markdown_extension_rejected_by_validate(self):
        assert ReadMarkdownTool().validate({"path": "file.txt"}) is False
        assert ReadMarkdownTool().validate({"path": "note.md"}) is True
        assert ReadMarkdownTool().validate({"path": "note.markdown"}) is True

    def test_read_missing_markdown_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = ReadMarkdownTool().execute({"path": "ghost.md"}, ctx)
        assert not result.success

    def test_result_data_has_heading_count(self, tmp_path):
        (tmp_path / "empty.md").write_text("no headings here", encoding="utf-8")
        ctx = _tool_context(tmp_path)
        result = ReadMarkdownTool().execute({"path": "empty.md"}, ctx)
        assert result.success
        assert result.data["heading_count"] == 0


class TestSystemInfoTool:
    def test_returns_system_info(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = SystemInfoTool().execute({}, ctx)
        assert result.success
        assert "os" in result.data
        assert "python_version" in result.data

    def test_validate_no_params_needed(self):
        assert SystemInfoTool().validate({}) is True
        assert SystemInfoTool().validate({"anything": 1}) is True

    def test_permission_is_read_system_info(self):
        assert Permission.READ_SYSTEM_INFO in SystemInfoTool().permissions


class TestDateTimeTool:
    def test_iso_format(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DateTimeTool().execute({"format": "iso"}, ctx)
        assert result.success
        # ISO 8601 contains 'T' separator
        assert "T" in result.message

    def test_date_format(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DateTimeTool().execute({"format": "date"}, ctx)
        assert result.success
        parts = result.message.split("-")
        assert len(parts) == 3  # YYYY-MM-DD

    def test_time_format(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DateTimeTool().execute({"format": "time"}, ctx)
        assert result.success
        parts = result.message.split(":")
        assert len(parts) == 3  # HH:MM:SS

    def test_unix_format(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DateTimeTool().execute({"format": "unix"}, ctx)
        assert result.success
        assert result.message.isdigit()

    def test_default_format_is_iso(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DateTimeTool().execute({}, ctx)
        assert result.success
        assert "T" in result.message

    def test_unknown_format_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = DateTimeTool().execute({"format": "nonsense"}, ctx)
        assert not result.success

    def test_no_permissions_required(self):
        assert DateTimeTool().permissions == ()


class TestEnvironmentTool:
    def test_returns_env_vars(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = EnvironmentTool().execute({}, ctx)
        assert result.success
        assert "variables" in result.data

    def test_no_sensitive_keys_exposed(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = EnvironmentTool().execute({}, ctx)
        for name, value in result.data["variables"].items():
            if any(sub in name.lower() for sub in {"key", "secret", "token", "password"}):
                assert value == "<redacted>", f"{name} should be redacted"

    def test_specific_key_lookup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SMARTAGENT_TEST_VAR", "hello_test_value")
        ctx = _tool_context(tmp_path)
        result = EnvironmentTool().execute({"key": "SMARTAGENT_TEST_VAR"}, ctx)
        assert result.success
        assert result.data["value"] == "hello_test_value"

    def test_missing_key_returns_failure(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = EnvironmentTool().execute({"key": "DEFINITELY_NOT_SET_XYZZY"}, ctx)
        assert not result.success

    def test_permission_is_read_system_info(self):
        assert Permission.READ_SYSTEM_INFO in EnvironmentTool().permissions


class TestUUIDTool:
    def test_generates_uuid4_by_default(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = UUIDTool().execute({}, ctx)
        assert result.success
        parsed = uuid_module.UUID(result.message)
        assert parsed.version == 4

    def test_generates_uuid1(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = UUIDTool().execute({"version": 1}, ctx)
        assert result.success
        parsed = uuid_module.UUID(result.message)
        assert parsed.version == 1

    def test_generates_uuid5(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = UUIDTool().execute(
            {"version": 5, "namespace": "dns", "name": "example.com"}, ctx
        )
        assert result.success
        assert uuid_module.UUID(result.message).version == 5

    def test_unsupported_version_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = UUIDTool().execute({"version": 99}, ctx)
        assert not result.success

    def test_no_permissions_required(self):
        assert UUIDTool().permissions == ()

    def test_each_call_produces_unique_uuid(self, tmp_path):
        ctx = _tool_context(tmp_path)
        r1 = UUIDTool().execute({}, ctx)
        r2 = UUIDTool().execute({}, ctx)
        assert r1.message != r2.message


class TestHashTool:
    def test_sha256(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = HashTool().execute({"content": "hello", "algorithm": "sha256"}, ctx)
        assert result.success
        expected = hashlib.sha256(b"hello").hexdigest()
        assert result.message == expected

    def test_md5(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = HashTool().execute({"content": "test", "algorithm": "md5"}, ctx)
        assert result.success
        expected = hashlib.md5(b"test").hexdigest()
        assert result.message == expected

    def test_default_algorithm_is_sha256(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = HashTool().execute({"content": "abc"}, ctx)
        assert result.success
        assert result.message == hashlib.sha256(b"abc").hexdigest()

    def test_unknown_algorithm_fails(self, tmp_path):
        ctx = _tool_context(tmp_path)
        result = HashTool().execute({"content": "x", "algorithm": "fakehash"}, ctx)
        assert not result.success

    def test_validate_requires_content(self):
        assert HashTool().validate({}) is False
        assert HashTool().validate({"content": "abc"}) is True

    def test_no_permissions_required(self):
        assert HashTool().permissions == ()


# ---------------------------------------------------------------------------
# 9. Integration tests
# ---------------------------------------------------------------------------

class TestToolsIntegration:
    def test_tool_engine_on_agent(self, tmp_path):
        agent = _agent(tmp_path)
        assert agent.tool_engine is not None
        assert len(agent.tool_engine.list_available()) == 15

    def test_skill_context_has_tool_engine(self, tmp_path):
        agent = _agent(tmp_path)
        from smartagent.brain.module_bindings import _build_skill_context
        ctx = _build_skill_context(agent)
        assert ctx.tool_engine is agent.tool_engine

    def test_permission_manager_shared_between_engines(self, tmp_path):
        agent = _agent(tmp_path)
        assert agent.skill_engine.permissions is agent.tool_engine.permissions

    def test_tools_handler_reports_available_tools(self, tmp_path):
        agent = _agent(tmp_path)
        result = agent.modules.get("tools")("list tools")
        # tools_handler always returns success=False (NL routing not possible without AI)
        assert result.success is False
        # But it should include tool names in its data
        assert isinstance(result.data, list)
        assert len(result.data) == 15

    def test_tools_in_list_available_after_agent_init(self, tmp_path):
        agent = _agent(tmp_path)
        available = agent.tools.list_available()
        assert "file_read" in available
        assert "hash_compute" in available

    def test_file_read_via_engine_with_permission(self, tmp_path):
        (tmp_path / "note.txt").write_text("agent test content")
        agent = _agent(tmp_path)
        # Grant READ_FILES for this test
        agent.permissions.grant(Permission.READ_FILES)
        ctx = ToolContext(
            settings=agent.settings,
            workspace_path=str(tmp_path),
            events=agent.events,
        )
        result = agent.tool_engine.run("file_read", ctx, path="note.txt")
        assert result.success
        assert "agent test content" in result.message

    def test_file_read_denied_without_permission(self, tmp_path):
        (tmp_path / "note.txt").write_text("secret")
        agent = _agent(tmp_path)
        # Default settings do NOT grant READ_FILES
        ctx = ToolContext(
            settings=agent.settings,
            workspace_path=str(tmp_path),
            events=agent.events,
        )
        result = agent.tool_engine.run("file_read", ctx, path="note.txt")
        assert not result.success
        assert "read_files" in result.message

    def test_hash_tool_no_permission_needed(self, tmp_path):
        agent = _agent(tmp_path)
        ctx = ToolContext(
            settings=agent.settings,
            workspace_path=str(tmp_path),
            events=agent.events,
        )
        result = agent.tool_engine.run("hash_compute", ctx, content="hello")
        assert result.success

    def test_uuid_tool_no_permission_needed(self, tmp_path):
        agent = _agent(tmp_path)
        ctx = ToolContext(
            settings=agent.settings,
            workspace_path=str(tmp_path),
            events=agent.events,
        )
        result = agent.tool_engine.run("uuid_generate", ctx)
        assert result.success
        assert uuid_module.UUID(result.message)
