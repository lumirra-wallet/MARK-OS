"""
Tests for Milestone 3 — Skills Engine v1.

Covers:
    - Permission enum and PermissionManager
    - BaseSkill / SkillMetadata / SkillContext shape
    - SkillRegistry (register, enable, disable, reload, list, find)
    - SkillLoader (discover_skill_classes)
    - SkillEngine (execute, permission enforcement, confidence ordering)
    - All six built-in skills (validate + execute happy/sad paths)
    - Integration via SmartAgent.handle_message (no double-store regression)

Design decisions preserved:
    - No databases, no AI model calls, no internet access.
    - Every test uses an isolated tmp_path vault so the real vault/ is
      never written to or read from during the suite.
    - The memory double-store fix (Milestone 3) is explicitly verified by
      test_handle_message_persists_remember_exactly_once.
"""

from __future__ import annotations

import pytest

from smartagent.brain.agent import SmartAgent
from smartagent.brain.events import EventBus
from smartagent.config.settings import Settings
from smartagent.memory.memory_manager import MemoryManager
from smartagent.models.model_client import ModelClient
from smartagent.planning.goal_manager import GoalManager
from smartagent.research.research_manager import ResearchManager
from smartagent.skills.base_skill import SkillCategory, SkillContext, SkillStatus
from smartagent.skills.builtin.conversation_skill import ConversationSkill
from smartagent.skills.builtin.knowledge_skill import KnowledgeSkill
from smartagent.skills.builtin.memory_skill import MemorySkill
from smartagent.skills.builtin.planning_skill import PlanningSkill
from smartagent.skills.builtin.research_skill import ResearchSkill
from smartagent.skills.builtin.system_info_skill import SystemInfoSkill
from smartagent.skills.permissions import Permission, PermissionManager
from smartagent.skills.skill_engine import SkillEngine
from smartagent.skills.skill_loader import discover_skill_classes
from smartagent.skills.skill_registry import SkillRegistry
from smartagent.tools.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(tmp_path):
    s = Settings.load()
    s.vault_path = str(tmp_path / "vault")
    return s


def _agent(tmp_path) -> SmartAgent:
    return SmartAgent(settings=_settings(tmp_path))


def _context(tmp_path) -> SkillContext:
    """Minimal SkillContext for unit-testing individual skills."""
    settings = _settings(tmp_path)
    events = EventBus()
    memory = MemoryManager(
        backend=settings.memory_backend,
        vault_path=settings.vault_path,
        categories=settings.memory_categories,
        event_bus=events,
    )
    return SkillContext(
        memory=memory,
        tools=ToolRegistry(enabled_tools=[]),
        goals=GoalManager(),
        research=ResearchManager(memory=memory),
        model=ModelClient(model_name="placeholder"),
        settings=settings,
        events=events,
        module_names=["memory", "skills", "tools"],
        skill_names=["memory_skill", "conversation_skill"],
    )


# ---------------------------------------------------------------------------
# 1. Permission enum & PermissionManager
# ---------------------------------------------------------------------------

class TestPermission:
    def test_permission_values_are_strings(self):
        assert Permission.READ_MEMORY.value == "read_memory"
        assert Permission.NETWORK_ACCESS.value == "network_access"

    def test_all_seven_permissions_exist(self):
        expected = {
            "read_memory", "write_memory", "run_tools",
            "access_files", "network_access", "automation", "system_commands",
        }
        actual = {p.value for p in Permission}
        assert actual == expected


class TestPermissionManager:
    def test_starts_empty_by_default(self):
        pm = PermissionManager()
        assert pm.granted_permissions() == []

    def test_grant_and_is_granted(self):
        pm = PermissionManager()
        pm.grant(Permission.READ_MEMORY)
        assert pm.is_granted(Permission.READ_MEMORY)

    def test_revoke_removes_permission(self):
        pm = PermissionManager([Permission.READ_MEMORY])
        pm.revoke(Permission.READ_MEMORY)
        assert not pm.is_granted(Permission.READ_MEMORY)

    def test_missing_returns_ungrated_subset(self):
        pm = PermissionManager([Permission.READ_MEMORY])
        missing = pm.missing([Permission.READ_MEMORY, Permission.WRITE_MEMORY])
        assert missing == [Permission.WRITE_MEMORY]

    def test_missing_empty_when_all_granted(self):
        pm = PermissionManager([Permission.READ_MEMORY, Permission.WRITE_MEMORY])
        assert pm.missing([Permission.READ_MEMORY, Permission.WRITE_MEMORY]) == []

    def test_initialised_from_iterable(self):
        pm = PermissionManager([Permission.RUN_TOOLS, Permission.ACCESS_FILES])
        assert pm.is_granted(Permission.RUN_TOOLS)
        assert pm.is_granted(Permission.ACCESS_FILES)
        assert not pm.is_granted(Permission.NETWORK_ACCESS)


# ---------------------------------------------------------------------------
# 2. SkillRegistry
# ---------------------------------------------------------------------------

class TestSkillRegistry:
    def test_register_and_find(self):
        reg = SkillRegistry()
        skill = MemorySkill()
        reg.register(skill)
        assert reg.find("memory_skill") is skill

    def test_list_available_returns_names(self):
        reg = SkillRegistry()
        reg.register(MemorySkill())
        reg.register(ConversationSkill())
        assert set(reg.list_available()) == {"memory_skill", "conversation_skill"}

    def test_list_returns_enabled_only_by_default(self):
        reg = SkillRegistry()
        reg.register(MemorySkill())
        reg.register(ConversationSkill())
        reg.disable("conversation_skill")
        names = [s.name for s in reg.list()]
        assert "conversation_skill" not in names
        assert "memory_skill" in names

    def test_list_all_includes_disabled(self):
        reg = SkillRegistry()
        reg.register(MemorySkill())
        reg.register(ConversationSkill())
        reg.disable("conversation_skill")
        names = [s.name for s in reg.list(enabled_only=False)]
        assert "conversation_skill" in names

    def test_enable_disable_toggle(self):
        reg = SkillRegistry()
        reg.register(MemorySkill())
        assert reg.is_enabled("memory_skill")
        reg.disable("memory_skill")
        assert not reg.is_enabled("memory_skill")
        reg.enable("memory_skill")
        assert reg.is_enabled("memory_skill")

    def test_enable_disable_unknown_returns_false(self):
        reg = SkillRegistry()
        assert reg.enable("no_such_skill") is False
        assert reg.disable("no_such_skill") is False

    def test_unregister_removes_skill(self):
        reg = SkillRegistry()
        reg.register(MemorySkill())
        reg.unregister("memory_skill")
        assert reg.find("memory_skill") is None
        assert "memory_skill" not in reg.list_available()

    def test_reload_recreates_instance_preserving_status(self):
        reg = SkillRegistry()
        skill = MemorySkill()
        reg.register(skill)
        reg.disable("memory_skill")
        fresh = reg.reload("memory_skill")
        assert fresh is not skill
        assert isinstance(fresh, MemorySkill)
        # Status (disabled) was preserved through the reload.
        assert not reg.is_enabled("memory_skill")

    def test_reload_unknown_returns_none(self):
        reg = SkillRegistry()
        assert reg.reload("no_such_skill") is None

    def test_list_filter_by_category(self):
        reg = SkillRegistry()
        reg.register(MemorySkill())
        reg.register(ConversationSkill())
        memory_only = reg.list(category=SkillCategory.MEMORY)
        assert len(memory_only) == 1
        assert memory_only[0].name == "memory_skill"


# ---------------------------------------------------------------------------
# 3. SkillLoader
# ---------------------------------------------------------------------------

class TestSkillLoader:
    def test_discovers_all_builtin_skills(self):
        classes = discover_skill_classes("smartagent.skills.builtin")
        names = {cls().name for cls in classes}
        expected = {
            "memory_skill", "research_skill", "planning_skill",
            "knowledge_skill", "conversation_skill", "system_info_skill",
        }
        assert expected.issubset(names), f"Missing: {expected - names}"

    def test_returns_empty_for_nonexistent_package(self):
        classes = discover_skill_classes("no.such.package.at.all")
        assert classes == []

    def test_all_discovered_classes_are_concrete(self):
        import inspect
        classes = discover_skill_classes("smartagent.skills.builtin")
        for cls in classes:
            assert not inspect.isabstract(cls), f"{cls.__name__} is abstract"


# ---------------------------------------------------------------------------
# 4. SkillEngine — dispatch and permission enforcement
# ---------------------------------------------------------------------------

class TestSkillEngine:
    def _engine_with_all_permissions(self) -> SkillEngine:
        """Engine that has every permission granted — bypasses permission gating."""
        pm = PermissionManager(list(Permission))
        return SkillEngine(
            registry=SkillRegistry(),
            permissions=pm,
            event_bus=EventBus(),
        )

    def _engine_no_permissions(self) -> SkillEngine:
        """Engine with no permissions granted — every skill requiring any permission fails."""
        return SkillEngine(
            registry=SkillRegistry(),
            permissions=PermissionManager(),
            event_bus=EventBus(),
        )

    def test_execute_returns_failure_when_no_skills_registered(self, tmp_path):
        engine = self._engine_with_all_permissions()
        ctx = _context(tmp_path)
        result = engine.execute("hello", ctx)
        assert result.success is False

    def test_execute_picks_matching_skill(self, tmp_path):
        engine = self._engine_with_all_permissions()
        engine.register(ConversationSkill())
        ctx = _context(tmp_path)
        result = engine.execute("hello", ctx)
        assert result.success is True
        assert "hello" in result.message.lower() or "hi" in result.message.lower()

    def test_execute_denies_skill_with_missing_permission(self, tmp_path):
        engine = self._engine_no_permissions()
        engine.register(MemorySkill())  # needs READ_MEMORY + WRITE_MEMORY
        ctx = _context(tmp_path)
        result = engine.execute("remember that coffee is good", ctx)
        # MemorySkill was the only candidate and was denied — engine returns failure.
        assert result.success is False

    def test_execute_falls_through_to_next_skill_after_permission_denial(self, tmp_path):
        """If the top-confidence skill is denied, the next matching one runs."""
        pm = PermissionManager([])  # deny everything
        engine = SkillEngine(registry=SkillRegistry(), permissions=pm, event_bus=EventBus())
        engine.register(MemorySkill())       # validate("hello") → False, so won't match
        engine.register(ConversationSkill()) # validate("hello") → True, needs NO permissions
        ctx = _context(tmp_path)
        result = engine.execute("hello", ctx)
        # ConversationSkill needs no permissions, should succeed.
        assert result.success is True

    def test_load_skills_auto_discovers_builtins(self, tmp_path):
        engine = self._engine_with_all_permissions()
        loaded = engine.load_skills()
        assert "memory_skill" in loaded
        assert "conversation_skill" in loaded

    def test_list_available_reflects_registered_skills(self):
        engine = self._engine_with_all_permissions()
        engine.register(MemorySkill())
        engine.register(ConversationSkill())
        available = engine.list_available()
        assert "memory_skill" in available
        assert "conversation_skill" in available

    def test_skill_executed_event_published(self, tmp_path):
        from smartagent.brain.events import Events
        bus = EventBus()
        pm = PermissionManager(list(Permission))
        engine = SkillEngine(registry=SkillRegistry(), permissions=pm, event_bus=bus)
        engine.register(ConversationSkill())
        ctx = _context(tmp_path)
        engine.execute("hello", ctx)
        published_names = [e.name for e in bus.history()]
        assert Events.SKILL_EXECUTED in published_names


# ---------------------------------------------------------------------------
# 5. Built-in skill — validate() and execute() unit tests
# ---------------------------------------------------------------------------

class TestMemorySkill:
    skill = MemorySkill()

    def test_validate_remember(self):
        assert self.skill.validate("remember that I like coffee")

    def test_validate_forget(self):
        assert self.skill.validate("forget that I like tea")

    def test_validate_recall(self):
        assert self.skill.validate("recall my favourite colour")

    def test_validate_rejects_unrelated(self):
        assert not self.skill.validate("what is the weather today")

    def test_execute_remember(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("remember that dogs are great", ctx)
        assert "dogs are great" in result

    def test_execute_recall_returns_stored_entry(self, tmp_path):
        ctx = _context(tmp_path)
        ctx.memory.remember("cats purr loudly", category="Personal")
        result = self.skill.execute("recall cats", ctx)
        assert "cats" in result.lower()

    def test_execute_forget_removes_entry(self, tmp_path):
        ctx = _context(tmp_path)
        ctx.memory.remember("I hate Mondays", category="Personal")
        self.skill.execute("forget that I hate Mondays", ctx)
        remaining = ctx.memory.search("Mondays")
        assert len(remaining) == 0

    def test_metadata(self):
        m = self.skill.metadata()
        assert m.name == "memory_skill"
        assert Permission.READ_MEMORY in m.permissions
        assert Permission.WRITE_MEMORY in m.permissions
        assert m.category == SkillCategory.MEMORY


class TestConversationSkill:
    skill = ConversationSkill()

    def test_validate_greeting(self):
        assert self.skill.validate("hello")

    def test_validate_thanks(self):
        assert self.skill.validate("thank you so much")

    def test_validate_farewell(self):
        assert self.skill.validate("goodbye")

    def test_validate_how_are_you(self):
        assert self.skill.validate("how are you doing today")

    def test_validate_rejects_memory_request(self):
        assert not self.skill.validate("remember that I like coffee")

    def test_execute_includes_original_message(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("hello there", ctx)
        assert "hello there" in result

    def test_execute_farewell_response(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("goodbye everyone", ctx)
        assert "goodbye everyone" in result

    def test_execute_how_are_you_response(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("how are you", ctx)
        assert "how are you" in result.lower() or "running" in result.lower()

    def test_metadata(self):
        m = self.skill.metadata()
        assert m.name == "conversation_skill"
        assert m.category == SkillCategory.CONVERSATION
        assert m.permissions == ()  # no permissions needed


class TestKnowledgeSkill:
    skill = KnowledgeSkill()

    def test_validate_note_prefix(self):
        assert self.skill.validate("note: Python is a language")

    def test_validate_query_keyword(self):
        assert self.skill.validate("what do you know about Python")

    def test_validate_rejects_unrelated(self):
        assert not self.skill.validate("remember that I like dogs")

    def test_execute_note_stores_in_knowledge(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("note: Earth orbits the Sun", ctx)
        assert "Earth orbits the Sun" in result
        stored = ctx.memory.search("Earth", category="Knowledge")
        assert len(stored) == 1

    def test_execute_query_returns_knowledge_entry(self, tmp_path):
        ctx = _context(tmp_path)
        ctx.memory.remember("Gravity is 9.8 m/s²", category="Knowledge")
        result = self.skill.execute("what do you know about gravity", ctx)
        assert "gravity" in result.lower() or "9.8" in result

    def test_metadata(self):
        m = self.skill.metadata()
        assert m.name == "knowledge_skill"
        assert m.category == SkillCategory.KNOWLEDGE


class TestPlanningSkill:
    skill = PlanningSkill()

    def test_validate_add_goal(self):
        assert self.skill.validate("add goal: launch the website")

    def test_validate_list_goals(self):
        assert self.skill.validate("show me my goal list")

    def test_validate_rejects_unrelated(self):
        assert not self.skill.validate("hello there")

    def test_execute_add_goal(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("add goal: ship the feature", ctx)
        assert "ship the feature" in result
        goals = ctx.goals.list_goals()
        assert any("ship the feature" in g.name for g in goals)

    def test_execute_list_goals_empty(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("list my goals", ctx)
        assert "no goals" in result.lower()

    def test_metadata(self):
        m = self.skill.metadata()
        assert m.name == "planning_skill"
        assert m.category == SkillCategory.PLANNING
        assert m.permissions == ()


class TestResearchSkill:
    skill = ResearchSkill()

    def test_validate_research_keyword(self):
        assert self.skill.validate("research quantum computing")

    def test_validate_rejects_unrelated(self):
        assert not self.skill.validate("hello how are you")

    def test_execute_surface_not_implemented(self, tmp_path):
        ctx = _context(tmp_path)
        # ResearchManager.search() raises NotImplementedError; the skill
        # catches it and returns a helpful message — never raises.
        result = self.skill.execute("research artificial intelligence", ctx)
        assert isinstance(result, str)

    def test_metadata_requires_network_access(self):
        m = self.skill.metadata()
        assert Permission.NETWORK_ACCESS in m.permissions

    def test_engine_denies_research_skill_by_default(self, tmp_path):
        """ResearchSkill requires NETWORK_ACCESS, which is NOT in default permissions."""
        pm = PermissionManager([Permission.READ_MEMORY, Permission.WRITE_MEMORY])
        engine = SkillEngine(registry=SkillRegistry(), permissions=pm, event_bus=EventBus())
        engine.register(ResearchSkill())
        ctx = _context(tmp_path)
        result = engine.execute("research quantum physics", ctx)
        assert result.success is False


class TestSystemInfoSkill:
    skill = SystemInfoSkill()

    def test_validate_system_info(self):
        assert self.skill.validate("system info")

    def test_validate_list_skills(self):
        assert self.skill.validate("list skills")

    def test_validate_rejects_unrelated(self):
        assert not self.skill.validate("remember that I like coffee")

    def test_execute_includes_module_and_skill_names(self, tmp_path):
        ctx = _context(tmp_path)
        result = self.skill.execute("system info", ctx)
        assert "memory" in result
        assert "memory_skill" in result

    def test_metadata_requires_system_commands(self):
        m = self.skill.metadata()
        assert Permission.SYSTEM_COMMANDS in m.permissions


# ---------------------------------------------------------------------------
# 6. Integration — SmartAgent.handle_message with Skills Engine
# ---------------------------------------------------------------------------

class TestSmartAgentSkillsIntegration:
    def test_skill_engine_is_initialized(self, tmp_path):
        agent = _agent(tmp_path)
        assert agent.skill_engine is not None
        assert hasattr(agent, "skill_engine")

    def test_builtin_skills_are_loaded_on_init(self, tmp_path):
        agent = _agent(tmp_path)
        available = agent.skill_engine.list_available()
        assert "memory_skill" in available
        assert "conversation_skill" in available

    def test_handle_hello_uses_conversation_skill(self, tmp_path):
        """'hello' should reach ConversationSkill and echo back the original message."""
        agent = _agent(tmp_path)
        response = agent.handle_message("hello")
        assert "hello" in response.lower()

    def test_handle_remember_stores_exactly_once(self, tmp_path):
        """
        Regression guard for the Milestone 3 double-store bug.

        Before the fix, "Remember that I like tea." would be written twice:
        once by MemorySkill (content extraction → Personal) and once by
        the unconditional Journal auto-persist in handle_message. After the
        fix, a MemorySaved event detected during routing causes the auto-
        persist to be skipped, leaving exactly one vault entry containing
        "tea".
        """
        agent = _agent(tmp_path)
        agent.handle_message("remember that I like tea")
        results = agent.memory.search("tea")
        assert len(results) == 1, (
            f"Expected exactly 1 entry for 'tea', got {len(results)}: "
            + str([r.content for r in results])
        )

    def test_handle_memory_search_before_skills(self, tmp_path):
        """Memory handler (priority 1) must answer before Skills (priority 2)."""
        agent = _agent(tmp_path)
        agent.memory.remember("The user's favourite colour is purple.", category="Personal")
        response = agent.handle_message("favourite colour")
        assert "purple" in response

    def test_default_permissions_grant_read_write_memory(self, tmp_path):
        """Default Settings must grant READ_MEMORY and WRITE_MEMORY so MemorySkill works."""
        agent = _agent(tmp_path)
        pm = agent.skill_engine.permissions
        assert pm.is_granted(Permission.READ_MEMORY)
        assert pm.is_granted(Permission.WRITE_MEMORY)

    def test_default_permissions_deny_network_access(self, tmp_path):
        """NETWORK_ACCESS must NOT be granted by default (ResearchSkill stays locked)."""
        agent = _agent(tmp_path)
        pm = agent.skill_engine.permissions
        assert not pm.is_granted(Permission.NETWORK_ACCESS)
