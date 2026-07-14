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
from smartagent.brain.events import EventBus
from smartagent.brain.module_bindings import register_default_modules
from smartagent.brain.module_registry import ModuleRegistry
from smartagent.brain.router import BrainRouter
from smartagent.config.settings import Settings
from smartagent.memory.memory_manager import MemoryManager
from smartagent.models.model_client import ModelClient
from smartagent.planning.goal_manager import GoalManager
from smartagent.planning.task_planner import TaskPlanner
from smartagent.research.research_manager import ResearchManager
from smartagent.skills.skill_registry import SkillRegistry
from smartagent.tools.tool_registry import ToolRegistry
from smartagent.vision.image_analysis import ImageAnalyzer
from smartagent.voice.speech_to_text import SpeechToText
from smartagent.voice.text_to_speech import TextToSpeech


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
        self.skills = SkillRegistry()
        self.model = ModelClient(model_name=settings.default_language_model)

        # Milestone 2 wires the previously-standalone planning/research/
        # voice/vision/automation packages into the agent so the Brain has
        # something to register in its ModuleRegistry (Part 4). None of
        # them gain new free-text-handling behavior here — see
        # `module_bindings.py` for why each one still honestly reports
        # "not available yet" for arbitrary messages.
        self.goals = GoalManager()
        self.task_planner = TaskPlanner()
        self.research = ResearchManager(memory=self.memory)
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

    def handle_message(self, message: str) -> str:
        """
        Process a single user message and return a response.

        All routing/decision logic now lives in `BrainRouter` (Brain v2) —
        this method's only remaining responsibilities are handing the
        message to the router and persisting the exchange afterward, so
        future messages can find it via `self.memory.search()`. Persisting
        unconditionally (regardless of which module answered) is what let
        Milestone 1's "check memory before the model" behavior work, and
        Brain v2 preserves it rather than special-casing memory.
        """
        result = self.router.route(message)
        self.memory.remember(message, category="Journal")
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
