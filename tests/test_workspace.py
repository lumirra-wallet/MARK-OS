"""
tests/test_workspace.py — Milestone 15: Project Workspace Manager.

Covers:
  - Workspace dataclass (paths, dirs, serialisation)
  - validate_workspace_name
  - WorkspaceStore (save/load/list/delete/exists)
  - WorkspaceManager CRUD (create/activate/deactivate/delete/list/get)
  - WorkspaceManager goal management (set_goal / goals.md)
  - WorkspaceManager execution recording (history JSON + lessons)
  - WorkspaceManager export_zip
  - WorkspaceManager scoped services (active_memory / active_knowledge)
  - file_output (write / list / count)
  - Orchestrator workspace injection (context.metadata["workspace"])
  - ExecutiveController workspace wiring (with_agent extracts workspace_manager)
  - SmartAgent workspace_manager attribute
  - Console: workspace and goal commands registered
  - Backward compatibility (no regression when workspace_manager is absent)
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_base(tmp_path):
    """A temporary directory for workspace storage."""
    return str(tmp_path / "workspaces")


@pytest.fixture()
def store(tmp_base):
    from smartagent.workspace.workspace_store import WorkspaceStore
    return WorkspaceStore(base_path=tmp_base)


@pytest.fixture()
def manager(tmp_base):
    from smartagent.workspace.workspace_manager import WorkspaceManager
    return WorkspaceManager(base_path=tmp_base)


# ---------------------------------------------------------------------------
# validate_workspace_name
# ---------------------------------------------------------------------------

class TestValidateWorkspaceName:
    def test_valid_names(self):
        from smartagent.workspace.workspace import validate_workspace_name
        for name in ("abc", "weather-api", "my-project-v2", "x1y", "a" * 63):
            validate_workspace_name(name)  # must not raise

    def test_empty_raises(self):
        from smartagent.workspace.workspace import validate_workspace_name
        with pytest.raises(ValueError, match="empty"):
            validate_workspace_name("")

    def test_too_short_raises(self):
        from smartagent.workspace.workspace import validate_workspace_name
        with pytest.raises(ValueError):
            validate_workspace_name("ab")  # only 2 chars

    def test_leading_hyphen_raises(self):
        from smartagent.workspace.workspace import validate_workspace_name
        with pytest.raises(ValueError):
            validate_workspace_name("-bad")

    def test_trailing_hyphen_raises(self):
        from smartagent.workspace.workspace import validate_workspace_name
        with pytest.raises(ValueError):
            validate_workspace_name("bad-")

    def test_uppercase_raises(self):
        from smartagent.workspace.workspace import validate_workspace_name
        with pytest.raises(ValueError):
            validate_workspace_name("BadName")

    def test_spaces_raises(self):
        from smartagent.workspace.workspace import validate_workspace_name
        with pytest.raises(ValueError):
            validate_workspace_name("my project")

    def test_too_long_raises(self):
        from smartagent.workspace.workspace import validate_workspace_name
        with pytest.raises(ValueError):
            validate_workspace_name("a" * 64)


# ---------------------------------------------------------------------------
# Workspace dataclass
# ---------------------------------------------------------------------------

class TestWorkspace:
    def test_default_paths(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="test-ws", path=str(tmp_path))
        assert ws.memory_path    == str(tmp_path / "memory")
        assert ws.knowledge_path == str(tmp_path / "knowledge")
        assert ws.output_path    == str(tmp_path / "output")
        assert ws.history_path   == str(tmp_path / "history")
        assert ws.lessons_file   == str(tmp_path / "LESSONS.md")
        assert ws.goals_file     == str(tmp_path / "goals.md")
        assert ws.metadata_file  == str(tmp_path / "workspace.json")

    def test_ensure_dirs_creates_structure(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="test-ws", path=str(tmp_path / "ws"))
        ws.ensure_dirs()
        assert os.path.isdir(ws.memory_path)
        assert os.path.isdir(ws.knowledge_path)
        assert os.path.isdir(ws.output_path)
        assert os.path.isdir(ws.history_path)

    def test_to_dict_round_trips(self, tmp_path):
        from smartagent.workspace.workspace import Workspace, WorkspaceStatus
        ws = Workspace(
            name="myws", path=str(tmp_path),
            active_goal="Build something", run_count=3,
        )
        d = ws.to_dict()
        ws2 = Workspace.from_dict(d, path=str(tmp_path))
        assert ws2.name == "myws"
        assert ws2.active_goal == "Build something"
        assert ws2.run_count == 3

    def test_file_count_empty(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="ws", path=str(tmp_path))
        assert ws.file_count() == 0

    def test_file_count_with_files(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="ws", path=str(tmp_path))
        ws.ensure_dirs()
        (tmp_path / "output" / "main.py").write_text("print('hello')")
        assert ws.file_count() == 1

    def test_history_count_empty(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="ws", path=str(tmp_path))
        assert ws.history_count() == 0

    def test_one_line_summary(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="weather-api", path=str(tmp_path), run_count=5)
        summary = ws.one_line_summary()
        assert "weather-api" in summary
        assert "5" in summary

    def test_repr(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="ws", path=str(tmp_path))
        assert "ws" in repr(ws)


# ---------------------------------------------------------------------------
# WorkspaceStore
# ---------------------------------------------------------------------------

class TestWorkspaceStore:
    def test_save_and_load(self, store, tmp_base):
        from smartagent.workspace.workspace import Workspace
        ws_dir = os.path.join(tmp_base, "my-project")
        ws = Workspace(name="my-project", path=ws_dir, run_count=2)
        store.save(ws)
        assert store.exists("my-project")

        loaded = store.load("my-project")
        assert loaded.name == "my-project"
        assert loaded.run_count == 2

    def test_load_missing_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.load("nonexistent")

    def test_exists_false_when_missing(self, store):
        assert not store.exists("ghost")

    def test_list_names_empty(self, store):
        assert store.list_names() == []

    def test_list_names_finds_workspaces(self, store, tmp_base):
        from smartagent.workspace.workspace import Workspace
        for name in ("alpha", "beta", "gamma"):
            ws = Workspace(name=name, path=os.path.join(tmp_base, name))
            store.save(ws)
        names = store.list_names()
        assert set(names) == {"alpha", "beta", "gamma"}
        assert names == sorted(names)  # alphabetical

    def test_delete_removes_directory(self, store, tmp_base):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="bye", path=os.path.join(tmp_base, "bye"))
        store.save(ws)
        assert store.exists("bye")
        store.delete("bye")
        assert not store.exists("bye")
        assert not os.path.isdir(os.path.join(tmp_base, "bye"))

    def test_delete_missing_raises(self, store):
        with pytest.raises(FileNotFoundError):
            store.delete("ghost")

    def test_atomic_save_no_corrupt_on_partial(self, store, tmp_base):
        """save() writes to .tmp then renames — metadata file is never half-written."""
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="safe", path=os.path.join(tmp_base, "safe"))
        store.save(ws)
        meta = os.path.join(tmp_base, "safe", "workspace.json")
        with open(meta) as f:
            data = json.load(f)
        assert data["name"] == "safe"
        assert not os.path.exists(meta + ".tmp")

    def test_workspace_dir(self, store, tmp_base):
        assert store.workspace_dir("foo") == os.path.join(
            os.path.abspath(tmp_base), "foo"
        )


# ---------------------------------------------------------------------------
# WorkspaceManager — CRUD
# ---------------------------------------------------------------------------

class TestWorkspaceManagerCRUD:
    def test_create_new(self, manager):
        ws = manager.create("new-project")
        assert ws.name == "new-project"
        assert manager.exists("new-project")

    def test_create_invalid_name(self, manager):
        with pytest.raises(ValueError):
            manager.create("Bad Name!")

    def test_create_duplicate_raises(self, manager):
        from smartagent.workspace.workspace_manager import WorkspaceError
        manager.create("dupes")
        with pytest.raises(WorkspaceError, match="already exists"):
            manager.create("dupes")

    def test_activate_sets_active(self, manager):
        manager.create("ws-one")
        ws = manager.activate("ws-one")
        assert manager.active is not None
        assert manager.active.name == "ws-one"
        assert ws.status == "active"

    def test_activate_missing_raises(self, manager):
        from smartagent.workspace.workspace_manager import WorkspaceError
        with pytest.raises(WorkspaceError, match="does not exist"):
            manager.activate("ghost")

    def test_create_and_activate_flow(self, manager):
        manager.create("calc")
        manager.activate("calc")
        assert manager.active.name == "calc"

    def test_deactivate_clears_active(self, manager):
        manager.create("wsx")
        manager.activate("wsx")
        manager.deactivate()
        assert manager.active is None

    def test_deactivate_noop_when_none(self, manager):
        manager.deactivate()  # should not raise

    def test_switching_workspaces(self, manager):
        manager.create("ws-a")
        manager.create("ws-b")
        manager.activate("ws-a")
        manager.activate("ws-b")
        assert manager.active.name == "ws-b"

    def test_get_existing(self, manager):
        manager.create("exists")
        ws = manager.get("exists")
        assert ws is not None
        assert ws.name == "exists"

    def test_get_missing_returns_none(self, manager):
        assert manager.get("missing") is None

    def test_exists_true_and_false(self, manager):
        manager.create("real")
        assert manager.exists("real")
        assert not manager.exists("fake")

    def test_list_workspaces_empty(self, manager):
        assert manager.list_workspaces() == []

    def test_list_workspaces_multiple(self, manager):
        for name in ("alpha", "beta", "gamma"):
            manager.create(name)
        workspaces = manager.list_workspaces()
        assert len(workspaces) == 3
        names = {ws.name for ws in workspaces}
        assert names == {"alpha", "beta", "gamma"}

    def test_list_shows_active_status(self, manager):
        manager.create("active-ws")
        manager.activate("active-ws")
        workspaces = manager.list_workspaces()
        active = next(ws for ws in workspaces if ws.name == "active-ws")
        assert active.status == "active"

    def test_delete_removes(self, manager):
        manager.create("to-delete")
        manager.delete("to-delete")
        assert not manager.exists("to-delete")

    def test_delete_active_without_force_raises(self, manager):
        from smartagent.workspace.workspace_manager import WorkspaceError
        manager.create("del-me")
        manager.activate("del-me")
        with pytest.raises(WorkspaceError, match="currently active"):
            manager.delete("del-me")

    def test_delete_active_with_force(self, manager):
        manager.create("force-del")
        manager.activate("force-del")
        manager.delete("force-del", force=True)
        assert manager.active is None
        assert not manager.exists("force-del")

    def test_delete_missing_raises(self, manager):
        from smartagent.workspace.workspace_manager import WorkspaceError
        with pytest.raises(WorkspaceError, match="does not exist"):
            manager.delete("ghost")


# ---------------------------------------------------------------------------
# WorkspaceManager — goal management
# ---------------------------------------------------------------------------

class TestWorkspaceManagerGoals:
    def test_set_goal_updates_active(self, manager):
        manager.create("goal-ws")
        manager.activate("goal-ws")
        manager.set_goal("Build a REST API")
        assert manager.active.active_goal == "Build a REST API"

    def test_set_goal_appends_to_goals_list(self, manager):
        manager.create("goal-ws")
        manager.activate("goal-ws")
        manager.set_goal("Goal A")
        manager.set_goal("Goal B")
        assert "Goal A" in manager.active.goals
        assert "Goal B" in manager.active.goals

    def test_set_goal_writes_goals_md(self, manager):
        manager.create("goal-ws")
        manager.activate("goal-ws")
        manager.set_goal("Build something")
        assert os.path.isfile(manager.active.goals_file)
        content = open(manager.active.goals_file).read()
        assert "Build something" in content

    def test_set_goal_no_active_raises(self, manager):
        from smartagent.workspace.workspace_manager import WorkspaceError
        with pytest.raises(WorkspaceError, match="No workspace"):
            manager.set_goal("some goal")

    def test_duplicate_goal_not_added_twice(self, manager):
        manager.create("goal-ws")
        manager.activate("goal-ws")
        manager.set_goal("Same goal")
        manager.set_goal("Same goal")
        assert manager.active.goals.count("Same goal") == 1


# ---------------------------------------------------------------------------
# WorkspaceManager — execution recording
# ---------------------------------------------------------------------------

class _FakeContext:
    def __init__(self, goal="Test goal", state="completed", plan_id="plan-001"):
        self.goal = goal
        self.plan_id = plan_id
        self.created_at = "2026-07-16T00:00:00+00:00"
        self.ended_at   = "2026-07-16T00:01:00+00:00"
        self.task_count       = 3
        self.completed_count  = 3
        self.failed_count     = 0
        from types import SimpleNamespace
        self.state = SimpleNamespace(value=state)
        self.metadata = {}


class _FakeReflectionResult:
    def __init__(self, score=0.8):
        from types import SimpleNamespace
        self.critic = SimpleNamespace(overall_score=score)
        self.memory_entries_added  = 2
        self.prompt_versions_added = 1
        # Fake plan with memory entries
        self.plan = SimpleNamespace(
            memory_entries=[
                SimpleNamespace(content="Lesson A"),
                SimpleNamespace(content="Lesson B"),
            ]
        )


class TestWorkspaceManagerRecording:
    def test_record_execution_increments_run_count(self, manager):
        manager.create("run-ws")
        manager.activate("run-ws")
        manager.record_execution(_FakeContext())
        assert manager.active.run_count == 1

    def test_record_execution_writes_history_file(self, manager):
        manager.create("hist-ws")
        manager.activate("hist-ws")
        ctx = _FakeContext(plan_id="plan-abc")
        manager.record_execution(ctx)
        hist_file = os.path.join(manager.active.history_path, "plan-abc.json")
        assert os.path.isfile(hist_file)
        with open(hist_file) as f:
            data = json.load(f)
        assert data["goal"] == "Test goal"
        assert data["plan_id"] == "plan-abc"

    def test_record_execution_with_reflection(self, manager):
        manager.create("ref-ws")
        manager.activate("ref-ws")
        ctx = _FakeContext(plan_id="plan-ref")
        manager.record_execution(ctx, _FakeReflectionResult())
        hist_file = os.path.join(manager.active.history_path, "plan-ref.json")
        with open(hist_file) as f:
            data = json.load(f)
        assert "reflection" in data
        assert data["reflection"]["score"] == pytest.approx(0.8)

    def test_record_execution_appends_lessons(self, manager):
        manager.create("lesson-ws")
        manager.activate("lesson-ws")
        manager.record_execution(_FakeContext(), _FakeReflectionResult())
        lessons_file = manager.active.lessons_file
        assert os.path.isfile(lessons_file)
        content = open(lessons_file).read()
        assert "Lesson A" in content
        assert "Lesson B" in content

    def test_record_execution_noop_when_no_active(self, manager):
        manager.record_execution(_FakeContext())  # must not raise

    def test_append_lessons_noop_when_no_active(self, manager):
        manager.append_lessons([])  # must not raise

    def test_multiple_runs_accumulate(self, manager):
        manager.create("multi-ws")
        manager.activate("multi-ws")
        for i in range(3):
            manager.record_execution(_FakeContext(plan_id=f"plan-{i}"))
        assert manager.active.run_count == 3
        assert manager.active.history_count() == 3


# ---------------------------------------------------------------------------
# WorkspaceManager — scoped services
# ---------------------------------------------------------------------------

class TestWorkspaceManagerScopedServices:
    def test_active_memory_returns_manager(self, manager):
        manager.create("svc-ws")
        manager.activate("svc-ws")
        mem = manager.active_memory()
        assert mem is not None
        # Should be a MemoryManager instance
        from smartagent.memory.memory_manager import MemoryManager
        assert isinstance(mem, MemoryManager)

    def test_active_memory_uses_workspace_path(self, manager):
        manager.create("path-ws")
        manager.activate("path-ws")
        mem = manager.active_memory()
        ws  = manager.active
        # The vault root should point inside the workspace memory directory
        assert os.path.abspath(ws.memory_path) == os.path.abspath(mem.vault.root)

    def test_active_memory_cached(self, manager):
        manager.create("cache-ws")
        manager.activate("cache-ws")
        m1 = manager.active_memory()
        m2 = manager.active_memory()
        assert m1 is m2  # same instance

    def test_active_knowledge_returns_manager(self, manager):
        manager.create("km-ws")
        manager.activate("km-ws")
        km = manager.active_knowledge()
        assert km is not None
        from smartagent.knowledge.knowledge_manager import KnowledgeManager
        assert isinstance(km, KnowledgeManager)

    def test_active_memory_none_when_no_active(self, manager):
        assert manager.active_memory() is None

    def test_active_knowledge_none_when_no_active(self, manager):
        assert manager.active_knowledge() is None

    def test_scoped_cache_cleared_on_delete(self, manager):
        manager.create("del-cache-ws")
        manager.activate("del-cache-ws")
        manager.active_memory()  # populate cache
        manager.delete("del-cache-ws", force=True)
        # Cache should be gone — no dangling reference
        assert "del-cache-ws" not in manager._scoped_memory


# ---------------------------------------------------------------------------
# WorkspaceManager — export
# ---------------------------------------------------------------------------

class TestWorkspaceManagerExport:
    def test_export_creates_zip(self, manager, tmp_base):
        manager.create("export-ws")
        archive = manager.export_zip("export-ws")
        assert archive.endswith(".zip")
        assert os.path.isfile(archive)

    def test_export_missing_raises(self, manager):
        from smartagent.workspace.workspace_manager import WorkspaceError
        with pytest.raises(WorkspaceError, match="does not exist"):
            manager.export_zip("ghost")


# ---------------------------------------------------------------------------
# file_output
# ---------------------------------------------------------------------------

class TestFileOutput:
    def _make_ws(self, tmp_path):
        from smartagent.workspace.workspace import Workspace
        ws = Workspace(name="out-ws", path=str(tmp_path / "out-ws"))
        ws.ensure_dirs()
        return ws

    def test_write_and_read_file(self, tmp_path):
        from smartagent.workspace.file_output import write_output_file
        ws   = self._make_ws(tmp_path)
        path = write_output_file(ws, "main.py", "print('hello')")
        assert os.path.isfile(path)
        assert open(path).read() == "print('hello')"

    def test_write_creates_subdirectories(self, tmp_path):
        from smartagent.workspace.file_output import write_output_file
        ws   = self._make_ws(tmp_path)
        path = write_output_file(ws, "src/api/routes.py", "# routes")
        assert os.path.isfile(path)

    def test_list_output_files_empty(self, tmp_path):
        from smartagent.workspace.file_output import list_output_files
        ws = self._make_ws(tmp_path)
        assert list_output_files(ws) == []

    def test_list_output_files_finds_files(self, tmp_path):
        from smartagent.workspace.file_output import write_output_file, list_output_files
        ws = self._make_ws(tmp_path)
        write_output_file(ws, "a.py", "")
        write_output_file(ws, "b.py", "")
        write_output_file(ws, "sub/c.py", "")
        files = list_output_files(ws)
        assert len(files) == 3
        assert "a.py" in files

    def test_output_file_count(self, tmp_path):
        from smartagent.workspace.file_output import write_output_file, output_file_count
        ws = self._make_ws(tmp_path)
        write_output_file(ws, "x.py", "")
        write_output_file(ws, "y.py", "")
        assert output_file_count(ws) == 2

    def test_write_returns_absolute_path(self, tmp_path):
        from smartagent.workspace.file_output import write_output_file
        ws   = self._make_ws(tmp_path)
        path = write_output_file(ws, "out.txt", "content")
        assert os.path.isabs(path)


# ---------------------------------------------------------------------------
# Orchestrator — workspace injection
# ---------------------------------------------------------------------------

class TestOrchestratorWorkspaceInjection:
    def test_orchestrator_accepts_workspace_manager(self, manager):
        from smartagent.executive.orchestrator import Orchestrator
        orc = Orchestrator(workspace_manager=manager)
        assert orc._workspace_manager is manager

    def test_inject_services_adds_workspace_to_metadata(self, manager, tmp_path):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        manager.create("inject-ws")
        manager.activate("inject-ws")
        orc = Orchestrator(workspace_manager=manager)
        ctx = ExecutionContext(goal="test")
        orc._inject_services(ctx)
        assert "workspace" in ctx.metadata
        assert ctx.metadata["workspace"].name == "inject-ws"

    def test_inject_overrides_memory_manager(self, manager):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        from smartagent.memory.memory_manager import MemoryManager
        global_mem = MemoryManager(vault_path="vault")
        manager.create("mem-ws")
        manager.activate("mem-ws")
        orc = Orchestrator(memory_manager=global_mem, workspace_manager=manager)
        ctx = ExecutionContext(goal="test")
        orc._inject_services(ctx)
        # The injected memory_manager should be the workspace-scoped one, not global
        assert ctx.metadata["memory_manager"] is not global_mem

    def test_inject_noop_when_no_active_workspace(self, manager):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        # No workspace activated
        orc = Orchestrator(workspace_manager=manager)
        ctx = ExecutionContext(goal="test")
        orc._inject_services(ctx)
        assert "workspace" not in ctx.metadata

    def test_save_to_workspace_noop_when_no_manager(self):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        orc = Orchestrator()
        ctx = ExecutionContext(goal="test")
        orc._save_to_workspace(ctx)  # must not raise

    def test_save_to_workspace_records_run(self, manager):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        manager.create("save-ws")
        manager.activate("save-ws")
        orc = Orchestrator(workspace_manager=manager)
        ctx = ExecutionContext(goal="test goal")
        orc._save_to_workspace(ctx)
        assert manager.active.run_count == 1


# ---------------------------------------------------------------------------
# ExecutiveController — workspace wiring
# ---------------------------------------------------------------------------

class TestExecutiveControllerWorkspaceWiring:
    def test_controller_accepts_workspace_manager(self, manager):
        from smartagent.executive.executive_controller import ExecutiveController
        ctrl = ExecutiveController(workspace_manager=manager)
        assert ctrl._orchestrator._workspace_manager is manager

    def test_with_agent_extracts_workspace_manager(self, manager):
        from smartagent.executive.executive_controller import ExecutiveController

        class FakeAgent:
            workspace_manager = manager
            model_manager    = None
            memory           = None
            knowledge        = None
            settings         = None
            tool_engine      = None
            events           = None
            reflection_engine = None

        ctrl = ExecutiveController.with_agent(FakeAgent())
        assert ctrl._orchestrator._workspace_manager is manager

    def test_with_agent_no_workspace_manager_attribute(self):
        """with_agent must not crash if agent has no workspace_manager."""
        from smartagent.executive.executive_controller import ExecutiveController

        class MinimalAgent:
            model_manager = None
            memory        = None
            knowledge     = None
            settings      = None
            tool_engine   = None
            events        = None
            reflection_engine = None

        ctrl = ExecutiveController.with_agent(MinimalAgent())
        assert ctrl._orchestrator._workspace_manager is None


# ---------------------------------------------------------------------------
# SmartAgent — workspace_manager attribute
# ---------------------------------------------------------------------------

class TestSmartAgentWorkspaceManager:
    def test_agent_has_workspace_manager(self):
        from smartagent.brain.agent import SmartAgent
        from smartagent.config.settings import Settings
        from smartagent.workspace.workspace_manager import WorkspaceManager

        s = Settings(workspaces_path=tempfile.mkdtemp())
        agent = SmartAgent(s)
        assert hasattr(agent, "workspace_manager")
        assert isinstance(agent.workspace_manager, WorkspaceManager)

    def test_agent_executive_wired_with_workspace_manager(self):
        from smartagent.brain.agent import SmartAgent
        from smartagent.config.settings import Settings

        s = Settings(workspaces_path=tempfile.mkdtemp())
        agent = SmartAgent(s)
        # The orchestrator inside the executive must have the workspace_manager
        orc = agent.executive._orchestrator
        assert orc._workspace_manager is agent.workspace_manager


# ---------------------------------------------------------------------------
# Console commands — registration
# ---------------------------------------------------------------------------

class TestWorkspaceCommandsRegistration:
    def test_workspace_command_registered(self):
        from smartagent.ui.command_router import CommandRouter
        from smartagent.ui.commands import workspace
        router = CommandRouter()
        workspace.register(router)
        names = {e.name for e in router.commands()}
        assert "workspace" in names
        assert "goal" in names

    def test_workspace_handler_callable(self):
        from smartagent.ui.commands.workspace import handle_workspace, handle_goal
        assert callable(handle_workspace)
        assert callable(handle_goal)


# ---------------------------------------------------------------------------
# Console commands — handler logic
# ---------------------------------------------------------------------------

class _FakeAgent:
    """Minimal agent stub for command handler tests."""
    def __init__(self, manager):
        self.workspace_manager = manager

        class FakeExecutive:
            current_context = None
            def plan(self, goal):
                from smartagent.executive.execution_context import ExecutionContext
                from smartagent.executive.execution_state import ExecutionState
                ctx = ExecutionContext(goal=goal)
                ctx.transition_to(ExecutionState.PLANNING)
                ctx.transition_to(ExecutionState.READY)
                return ctx
        self.executive = FakeExecutive()


class TestWorkspaceCommandHandlers:
    def test_create_handler(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["create", "new-proj"])
        assert "created" in result.lower() or "new-proj" in result

    def test_create_invalid_name(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["create", "Bad Name!"])
        assert "[error]" in result

    def test_list_empty(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["list"])
        assert "no workspace" in result.lower() or "create" in result.lower()

    def test_list_with_workspaces(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        manager.create("proj-a")
        manager.create("proj-b")
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["list"])
        assert "proj-a" in result
        assert "proj-b" in result

    def test_open_existing(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        manager.create("open-me")
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["open", "open-me"])
        assert "open-me" in result
        assert manager.active is not None

    def test_open_missing(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["open", "ghost"])
        assert "[error]" in result

    def test_status_no_active(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["status"])
        assert "no workspace" in result.lower()

    def test_status_with_active(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        manager.create("status-ws")
        manager.activate("status-ws")
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["status"])
        assert "status-ws" in result

    def test_close_active(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        manager.create("close-me")
        manager.activate("close-me")
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["close"])
        assert "closed" in result.lower()
        assert manager.active is None

    def test_close_no_active(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["close"])
        assert "no workspace" in result.lower()

    def test_delete_existing(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        manager.create("del-this")
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["delete", "del-this"])
        assert "deleted" in result.lower()
        assert not manager.exists("del-this")

    def test_delete_missing(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["delete", "ghost"])
        assert "[error]" in result

    def test_delete_active_warns(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        manager.create("del-active")
        manager.activate("del-active")
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["delete", "del-active"])
        # Should warn, not delete
        assert manager.exists("del-active")

    def test_unknown_subcommand(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, ["unknowncmd"])
        assert "unknown" in result.lower() or "workspace" in result.lower()

    def test_no_subcommand_shows_help(self, manager):
        from smartagent.ui.commands.workspace import handle_workspace
        agent = _FakeAgent(manager)
        result = handle_workspace(agent, [])
        assert "workspace" in result.lower()

    def test_goal_handler_no_active_workspace(self, manager):
        from smartagent.ui.commands.workspace import handle_goal
        agent = _FakeAgent(manager)
        result = handle_goal(agent, ["Build", "a", "calculator"])
        # No workspace active — goal still pre-loads a plan
        assert "plan" in result.lower() or "task" in result.lower()

    def test_goal_handler_with_active_workspace(self, manager):
        from smartagent.ui.commands.workspace import handle_goal
        manager.create("goal-proj")
        manager.activate("goal-proj")
        agent = _FakeAgent(manager)
        result = handle_goal(agent, ["Build", "a", "REST", "API"])
        assert "goal-proj" in result
        assert manager.active.active_goal == "Build a REST API"

    def test_goal_handler_no_args(self, manager):
        from smartagent.ui.commands.workspace import handle_goal
        agent = _FakeAgent(manager)
        result = handle_goal(agent, [])
        assert "usage" in result.lower() or "goal" in result.lower()


# ---------------------------------------------------------------------------
# Settings — workspaces_path
# ---------------------------------------------------------------------------

class TestSettings:
    def test_settings_has_workspaces_path(self):
        from smartagent.config.settings import Settings
        s = Settings()
        assert hasattr(s, "workspaces_path")
        assert s.workspaces_path == "workspaces"

    def test_settings_workspaces_path_configurable(self):
        from smartagent.config.settings import Settings
        s = Settings(workspaces_path="/custom/path")
        assert s.workspaces_path == "/custom/path"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_orchestrator_default_no_workspace_manager(self):
        from smartagent.executive.orchestrator import Orchestrator
        orc = Orchestrator()
        assert orc._workspace_manager is None

    def test_executive_controller_default_no_workspace_manager(self):
        from smartagent.executive.executive_controller import ExecutiveController
        ctrl = ExecutiveController()
        assert ctrl._workspace_manager is None
        assert ctrl._orchestrator._workspace_manager is None

    def test_workspace_package_importable(self):
        from smartagent import workspace  # noqa: F401
        from smartagent.workspace import (
            Workspace, WorkspaceManager, WorkspaceStore,
            WorkspaceStatus, WorkspaceError,
            write_output_file, list_output_files, output_file_count,
        )
        assert WorkspaceManager is not None

    def test_existing_tests_still_pass_with_workspace_manager(self):
        """SmartAgent creates workspace_manager without breaking any prior behaviour."""
        from smartagent.brain.agent import SmartAgent
        from smartagent.config.settings import Settings
        s = Settings(workspaces_path=tempfile.mkdtemp())
        agent = SmartAgent(s)
        # All previously-tested attributes still present
        assert hasattr(agent, "memory")
        assert hasattr(agent, "knowledge")
        assert hasattr(agent, "executive")
        assert hasattr(agent, "reflection_engine")
        assert hasattr(agent, "workspace_manager")
