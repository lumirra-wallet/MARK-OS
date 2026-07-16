"""
The SmartAgent core class.

This is the orchestrator that ties configuration, memory, models, skills,
tools, and the rest of the subsystems together to handle a user's request
and produce a response. As of Brain v2 (Milestone 2), `SmartAgent` no
longer contains the actual decision logic itself — it constructs every
subsystem, registers each one with a `ModuleRegistry`, and delegates all
routing to a `BrainRouter`. This keeps `SmartAgent` a thin composition
root: the place that wires things together, not the place that decides
things.
"""

from __future__ import annotations

from smartagent.automation.task_scheduler import TaskScheduler
from smartagent.brain.events import EventBus, Events
from smartagent.brain.module_bindings import register_default_modules
from smartagent.brain.module_registry import ModuleRegistry
from smartagent.brain.router import BrainRouter
from smartagent.config.settings import Settings
from smartagent.knowledge.knowledge_manager import KnowledgeManager
from smartagent.logs.logger import get_logger
from smartagent.memory.memory_manager import MemoryManager
from smartagent.executive.executive_controller import ExecutiveController as PlanningController
from smartagent.mind.executive.executive_controller import ExecutiveController, MindProviders
from smartagent.mind.state.state_machine import InternalState
from smartagent.models.config.model_settings import ModelSettings
from smartagent.models.manager.model_manager import ModelManager
from smartagent.models.model_client import ModelClient
from smartagent.planning.goal_manager import GoalManager
from smartagent.planning.task_planner import TaskPlanner
from smartagent.reflection.learning_store import LearningStore
from smartagent.reflection.prompt_registry import PromptRegistry
from smartagent.reflection.reflection_engine import ReflectionEngine
from smartagent.workspace.workspace_manager import WorkspaceManager
from smartagent.multi_agent.ceo_agent import CEOAgent
from smartagent.project_memory.project_memory import ProjectMemory
from smartagent.long_running.long_running_engine import LongRunningEngine
from smartagent.dev_loop.dev_loop import DevLoop
from smartagent.engineer.software_engineer import SoftwareEngineer
from smartagent.research.research_manager import ResearchManager
from smartagent.skills.permissions import Permission, PermissionManager
from smartagent.skills.skill_engine import SkillEngine
from smartagent.skills.skill_registry import SkillRegistry
from smartagent.tools.tool_engine import ToolEngine
from smartagent.tools.tool_registry import ToolRegistry
from smartagent.vision.image_analysis import ImageAnalyzer
from smartagent.voice.speech_to_text import SpeechToText
from smartagent.voice.text_to_speech import TextToSpeech

_logger = get_logger(__name__)


class SmartAgent:
    """
    Central orchestrator for the assistant.

    Responsibilities:
        - Construct every subsystem (memory, tools, skills, models,
          planning, research, voice, vision, automation) from `settings`.
        - Register each subsystem with a `ModuleRegistry` and build a
          `BrainRouter` on top of it (see `smartagent.brain.module_bindings`
          for how each subsystem is adapted into a module handler).
        - Receive a message/command from a user (text or transcribed
          voice) and hand it to `BrainRouter.route()`.
        - Persist the exchange back into memory.
        - Return the response to the caller (ui, voice output, etc.).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Shared event bus: every subsystem that wants to announce what it
        # did (e.g. memory saving an entry, the router making a decision)
        # publishes onto this one bus, so anything else in the system can
        # observe it without a direct dependency (see `smartagent.brain.events`).
        self.events = EventBus()

        self.memory = MemoryManager(
            backend=settings.memory_backend,
            vault_path=settings.vault_path,
            categories=settings.memory_categories,
            event_bus=self.events,
        )
        self.tools = ToolRegistry(enabled_tools=settings.enabled_tools)

        # Build a single PermissionManager from config-supplied permission names
        # (stored as strings so `config` stays free of a dependency on `skills`).
        # Shared by both SkillEngine and ToolEngine — one authority governs both.
        try:
            granted = [Permission(p) for p in settings.granted_permissions]
        except ValueError:
            granted = []
        self.permissions = PermissionManager(granted=granted)

        # SkillRegistry is the low-level container; SkillEngine sits on top of it
        # and is what the Brain (via module_bindings) actually talks to. Keeping
        # `self.skills` pointing at the registry preserves backward-compatibility
        # with any code that inspected `agent.skills` before Milestone 3.
        self.skills = SkillRegistry()
        self.skill_engine = SkillEngine(
            registry=self.skills,
            permissions=self.permissions,
            event_bus=self.events,
        )
        # Auto-discover and register every class in `smartagent.skills.builtin`.
        self.skill_engine.load_skills()

        # Milestone 4: ToolEngine wraps the same ToolRegistry and shares the same
        # PermissionManager and EventBus so permission grants affect both layers
        # and tool events appear on the same audit trail as skill events.
        self.tool_engine = ToolEngine(
            registry=self.tools,
            permissions=self.permissions,
            event_bus=self.events,
        )
        # Auto-discover and register every built-in tool.
        self.tool_engine.load_tools()

        # Milestone 1 placeholder client — kept only for backward compatibility
        # with `SkillContext.model` and code written before Milestone 5. New
        # code (and the Brain's `model` module handler below) must go through
        # `self.model_manager` instead; see `smartagent.models.manager.model_manager`.
        self.model = ModelClient(model_name=settings.default_language_model)

        # Milestone 5: ModelManager is the only component allowed to talk to
        # model providers (Part 11). `default_model_id=""` means no provider
        # is auto-loaded, so free-text routing behavior is unchanged from
        # before Milestone 5 — see `ModelManager`'s module docstring for why.
        self.model_manager = ModelManager(
            settings=ModelSettings(
                default_model_id=settings.default_model_id,
                ollama_base_url=getattr(settings, "ollama_base_url", "http://127.0.0.1:11434"),
                ollama_default_model=getattr(settings, "ollama_default_model", "llama3.1:8b"),
                ollama_coding_model=getattr(settings, "ollama_coding_model", "qwen2.5-coder:7b"),
            ),
            event_bus=self.events,
        )
        self.model_manager.discover_providers()
        # Milestone 9: register Ollama model providers so console commands
        # like ``model use llama3.1:8b`` work even if Ollama is offline.
        # Discovery runs quickly (3 s timeout) and never blocks startup.
        self.model_manager.load_ollama_models(
            base_url=getattr(settings, "ollama_base_url", "http://127.0.0.1:11434"),
            default_model=getattr(settings, "ollama_default_model", "llama3.1:8b"),
            coding_model=getattr(settings, "ollama_coding_model", "qwen2.5-coder:7b"),
        )

        # Milestone 2 wires the previously-standalone planning/research/
        # voice/vision/automation packages into the agent so the Brain has
        # something to register in its ModuleRegistry (Part 4). None of
        # them gain new free-text-handling behavior here — see
        # `module_bindings.py` for why each one still honestly reports
        # "not available yet" for arbitrary messages.
        self.goals = GoalManager()
        self.task_planner = TaskPlanner()
        self.research = ResearchManager(memory=self.memory)

        # Milestone 7: Knowledge Engine v1. The Brain communicates only
        # through KnowledgeManager — never by importing sub-engines directly.
        # knowledge_path is configurable (defaults to "knowledge/") so tests
        # and deployments can redirect it without code changes.
        self.knowledge = KnowledgeManager(
            knowledge_path=getattr(settings, "knowledge_path", "knowledge")
        )
        self.speech_to_text = SpeechToText(enabled=settings.voice_enabled)
        self.text_to_speech = TextToSpeech(enabled=settings.voice_enabled)
        self.vision = ImageAnalyzer()
        self.automation = TaskScheduler(enabled=settings.automation_enabled)

        # Brain v2: build the module registry and hand it to a router. The
        # router (and the DecisionEngine it uses) only ever refers to
        # modules by the names registered here — see
        # `smartagent.brain.module_registry` for why that matters.
        self.modules = ModuleRegistry()
        register_default_modules(self.modules, self)
        self.router = BrainRouter(self.modules, event_bus=self.events)

        # Milestone 6: the Mind observes the rest of SmartAgent through
        # read-only providers (Part 1) — it never changes what Brain
        # routing, Skills, Tools, or the Model Framework decide (see
        # `smartagent.mind`'s package docstring). Constructed last so every
        # provider closes over a fully-initialized `self`.
        self.mind = ExecutiveController(
            providers=MindProviders(
                active_goal=lambda: next(
                    (g.name for g in self.goals.list_goals(status="active")), None
                ),
                goals=lambda: [g.name for g in self.goals.list_goals()],
                skills=lambda: self.skill_engine.list_available(),
                tools=lambda: self.tool_engine.list_available(),
                active_model=lambda: self.model_manager.active_model_id,
            ),
            event_bus=self.events,
        )

        # Milestone 14 — Autonomous Learning & Self-Improvement.
        # A shared PromptRegistry and LearningStore live on the agent so they
        # accumulate state across multiple executions within a session.  The
        # ReflectionEngine is exposed as `agent.reflection_engine` so console
        # commands can query it directly.
        self.prompt_registry = PromptRegistry()
        self.learning_store = LearningStore(memory_manager=self.memory)
        self.reflection_engine = ReflectionEngine(
            memory_manager=self.memory,
            knowledge_manager=self.knowledge,
            model_manager=self.model_manager,
            prompt_registry=self.prompt_registry,
            learning_store=self.learning_store,
        )

        # Milestone 15 — Project Workspace Manager.
        # Provides per-project isolation for memory, knowledge, execution
        # history, output files, and lessons. The base path is configurable
        # so tests and deployments can redirect it without code changes.
        self.workspace_manager = WorkspaceManager(
            base_path=getattr(settings, "workspaces_path", "workspaces")
        )

        # Milestone 11 — Executive Framework (planning & task orchestration).
        # Distinct from `self.mind` (which is the Mind OS executive controller).
        # `agent.executive` is the goal-decomposition and task-scheduling layer.
        # Use with_agent() so all services (model, memory, knowledge, tools,
        # reflection, and workspace) are threaded through automatically.
        self.executive = PlanningController.with_agent(self)

        # Milestone 17 — Multi-Agent Collaboration.
        # Sits above the executive: CEO decomposes goals into team assignments,
        # each team runs its own Orchestrator with team-scoped workers.
        self.ceo = CEOAgent.with_agent(self)

        # Milestone 22 — Project Memory.
        # Stores per-project tech-stack profiles so every future task in that
        # project benefits from known context (framework, test runner, DB, etc.)
        self.project_memory = ProjectMemory(
            base_path=getattr(settings, "project_memory_path", "project_memory")
        )

        # Milestone 23 — Long Running Execution.
        # Wraps the CEO pipeline with structured CompletionReport output,
        # per-phase timing, and optional progress callbacks.
        self.long_running_engine = LongRunningEngine(
            ceo_agent=self.ceo,
            memory_manager=self.memory,
            project_memory=self.project_memory,
        )

        # Milestone 24 — Autonomous Development Loop.
        # plan → code → test → debug → reflect → retry until tests pass.
        self.dev_loop = DevLoop.with_agent(self)

        # Milestone 25 — Full Software Engineer.
        # Analyze requirements → clarify → plan → execute DevLoop → commit.
        self.software_engineer = SoftwareEngineer.with_agent(self)

    def handle_message(self, message: str) -> str:
        """
        Process a single user message and return a response.

        All routing/decision logic now lives in `BrainRouter` (Brain v2) —
        this method's only remaining responsibilities are handing the
        message to the router and persisting the exchange afterward, so
        future messages can find it via `self.memory.search()`.

        Milestone 3 deduplication: if a skill (e.g. `MemorySkill`) already
        wrote something to memory during routing, the event bus will have a
        new `MemorySaved` entry in its history. We snapshot the history
        length before routing and skip the unconditional Journal auto-persist
        afterward if memory was already written — otherwise every explicit
        "remember that X" request would store *two* entries (one from the
        skill, one from the Journal persist), causing off-by-one failures in
        memory search results.

        Conversations and unknown-handler fallbacks still get persisted
        because their handlers never emit `MemorySaved`.
        """
        history_before = len(self.events.history())
        self.mind.state_machine.transition(InternalState.THINKING, reason="handling a message")
        result = self.router.route(message)
        memory_written = any(
            event.name == Events.MEMORY_SAVED
            for event in self.events.history()[history_before:]
        )
        if not memory_written:
            self.memory.remember(message, category="Journal")

        # Milestone 6: the Mind observes the outcome (state + reflection)
        # without altering it — `result.message` below is exactly what
        # `BrainRouter` produced, unchanged. Wrapped defensively so a Mind
        # bug can never break message handling itself.
        try:
            self.mind.reflection_engine.reflect(
                task_name="handle_message",
                succeeded=result.success,
                what_happened=f"Routed via {result.source!r}: {result.message}",
            )
            self.mind.state_machine.transition(InternalState.IDLE, reason="message handled")
            self.mind.sync_self_model()
        except Exception:  # noqa: BLE001 — Mind observation must never break message handling
            _logger.warning("Mind observation failed during handle_message", exc_info=True)

        return result.message

    def run(self) -> None:
        """
        Start the assistant's main interaction loop.

        Placeholder implementation: prints a startup message. This will
        eventually branch into a text REPL (see `smartagent.ui`), a voice
        loop (see `smartagent.voice`), or be driven externally (e.g. by an
        automation trigger).
        """
        print(f"{self.settings.agent_name} is starting up (placeholder run loop).")
        print("Real conversational behavior has not been implemented yet.")
