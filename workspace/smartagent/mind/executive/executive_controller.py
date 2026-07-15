"""
ExecutiveController — Milestone 6, Part 1.

MARK's central coordinator, and the composition root of the whole Mind
package: it owns every other Mind engine (self model, working memory,
attention, context, confidence, state machine, reflection, homeostasis +
sensory + loop) and is "the only component allowed to coordinate all major
systems" per the milestone brief.

Design decision — read-only providers, not hard dependencies:
    `ExecutiveController` must reflect what Skills/Tools/Model/Goals are
    doing *without* importing `smartagent.brain.agent.SmartAgent` (that
    would invert the dependency direction — `SmartAgent` constructs the
    Mind, so the Mind can't also construct/import `SmartAgent`) and
    without changing how those subsystems behave (explicit milestone
    constraint). The fix is `MindProviders`: a bag of zero-argument
    callables `SmartAgent` binds to its own live subsystems (e.g.
    `tools=lambda: agent.tool_engine.list_available()`). Every provider is
    optional and defaults to returning empty/neutral data, so
    `ExecutiveController` is fully constructible and testable with zero
    providers bound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger
from smartagent.mind.attention.attention_manager import AttentionManager, FocusItem
from smartagent.mind.confidence.confidence_engine import ConfidenceAssessment, ConfidenceEngine
from smartagent.mind.context.context_manager import ContextBundle, ContextManager
from smartagent.mind.homeostasis.health_metrics import HealthMetrics
from smartagent.mind.homeostasis.homeostasis_engine import HomeostasisEngine
from smartagent.mind.homeostasis.loop import DigitalHomeostasisLoop, HomeostasisTickResult
from smartagent.mind.homeostasis.sensory import DigitalSensorySystem, SensorySignal
from smartagent.mind.identity.identity_engine import IdentityEngine
from smartagent.mind.identity.identity_model import Identity
from smartagent.mind.reflection.reflection_engine import Reflection, ReflectionEngine
from smartagent.mind.self_model.self_model import SelfModel
from smartagent.mind.self_model.self_model_engine import SelfModelEngine
from smartagent.mind.state.state_machine import InternalState, StateMachine
from smartagent.mind.working_memory.working_memory import WorkingMemory

logger = get_logger(__name__)


@dataclass
class MindProviders:
    """
    Optional zero-argument callables into a running `SmartAgent`'s live state.

    Every field defaults to a no-op returning empty/neutral data, so an
    `ExecutiveController` built with no providers at all is still fully
    functional for direct testing. `SmartAgent` binds the real ones after
    constructing its other subsystems (see `smartagent/brain/agent.py`).
    """

    active_goal: Callable[[], str | None] = field(default=lambda: None)
    goals: Callable[[], list[str]] = field(default=lambda: [])
    skills: Callable[[], list[str]] = field(default=lambda: [])
    tools: Callable[[], list[str]] = field(default=lambda: [])
    active_model: Callable[[], str | None] = field(default=lambda: None)
    running_processes: Callable[[], list[str]] = field(default=lambda: [])


@dataclass
class RunningProcess:
    """A named process/module the Executive Controller currently considers active."""

    name: str
    detail: str = ""


class ExecutiveController:
    """
    Coordinates every Mind subsystem and mirrors (read-only) what the Brain is doing.

    Args:
        identity: The `Identity` to seed the `SelfModel` from. Defaults to
            `IdentityEngine().identity` (parsed from `SMARTAGENT.md`, or the
            built-in default identity if that file is missing/unparseable).
        providers: Optional `MindProviders` bound to a live `SmartAgent`.
        event_bus: Shared `EventBus` every engine publishes onto.
    """

    def __init__(
        self,
        identity: Identity | None = None,
        providers: MindProviders | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.events = event_bus
        self.identity = identity or IdentityEngine().identity
        self.providers = providers or MindProviders()

        self.self_model_engine = SelfModelEngine(identity=self.identity, event_bus=event_bus)
        self.working_memory = WorkingMemory()
        self.attention = AttentionManager(event_bus=event_bus)
        self.context_manager = ContextManager()
        self.confidence_engine = ConfidenceEngine(event_bus=event_bus)
        self.state_machine = StateMachine(event_bus=event_bus)
        self.reflection_engine = ReflectionEngine(event_bus=event_bus)
        self.homeostasis_engine = HomeostasisEngine(event_bus=event_bus)
        self.sensory = DigitalSensorySystem(event_bus=event_bus)
        self.homeostasis_loop = DigitalHomeostasisLoop(homeostasis_engine=self.homeostasis_engine)

        self._current_goal: str | None = None
        self._current_task: str | None = None
        self._priority_queue: list[FocusItem] = []
        self._task_load = 0

        self.sync_self_model()

    # ------------------------------------------------------------------
    # Self model synchronization
    # ------------------------------------------------------------------

    def sync_self_model(self) -> SelfModel:
        """
        Pull the latest data from every bound provider into the `SelfModel`.

        Safe to call as often as desired (e.g. before answering "what are
        you doing?") — cheap, in-memory, side-effect-free beyond the
        `SelfModel` itself.
        """
        return self.self_model_engine.update(
            current_goal=self.providers.active_goal(),
            goals=self.providers.goals(),
            skills=self.providers.skills(),
            tools=self.providers.tools(),
            active_model=self.providers.active_model(),
            current_activity=self._current_task or "idle",
            state=self.state_machine.state.value,
        )

    def self_model(self) -> SelfModel:
        """The current `SelfModel` snapshot, without re-syncing providers first."""
        return self.self_model_engine.snapshot()

    # ------------------------------------------------------------------
    # Goal / task / process coordination
    # ------------------------------------------------------------------

    def set_current_goal(self, goal: str | None) -> None:
        """Record the goal MARK is currently pursuing and publish `GoalChanged`."""
        previous = self._current_goal
        self._current_goal = goal
        if self.events is not None and previous != goal:
            self.events.publish(Events.GOAL_CHANGED, previous_goal=previous, goal=goal)
        self.sync_self_model()

    @property
    def current_goal(self) -> str | None:
        """The goal currently being pursued, or `None`."""
        return self._current_goal

    def start_task(self, task_name: str, importance: float = 0.5) -> None:
        """
        Begin coordinating a new task: transition to EXECUTING, focus attention on it,
        publish `TaskStarted`, and track it as the current task.
        """
        self._current_task = task_name
        self._task_load += 1
        self.attention.focus_on(FocusItem(name=task_name, importance=importance, source="executive"))
        self.state_machine.transition(InternalState.EXECUTING, reason=f"starting task {task_name!r}")
        if self.events is not None:
            self.events.publish(Events.TASK_STARTED, task_name=task_name)
        self.sync_self_model()

    def complete_task(
        self,
        task_name: str,
        succeeded: bool,
        what_happened: str,
        what_failed: str | None = None,
        learned: str | None = None,
    ) -> Reflection:
        """
        Finish coordinating a task: reflect on it, drop it from attention, and
        transition to REFLECTING then IDLE. Publishes `TaskCompleted` (via
        the reflection engine's `ReflectionFinished` plus its own event).
        """
        self._task_load = max(0, self._task_load - 1)
        self.attention.drop(task_name)
        self.state_machine.transition(InternalState.REFLECTING, reason=f"completing task {task_name!r}")
        reflection = self.reflection_engine.reflect(
            task_name=task_name,
            succeeded=succeeded,
            what_happened=what_happened,
            what_failed=what_failed,
            learned=learned,
        )
        if self.events is not None:
            self.events.publish(Events.TASK_COMPLETED, task_name=task_name, succeeded=succeeded)
        if self._current_task == task_name:
            self._current_task = None
        self.state_machine.transition(InternalState.IDLE, reason="task cycle complete")
        self.sync_self_model()
        return reflection

    def running_processes(self) -> list[RunningProcess]:
        """Currently active processes: the current task (if any) plus anything a provider reports."""
        processes = [RunningProcess(name=name) for name in self.providers.running_processes()]
        if self._current_task:
            processes.append(RunningProcess(name=self._current_task, detail="current task"))
        return processes

    # ------------------------------------------------------------------
    # Priority queue / interrupt handling
    # ------------------------------------------------------------------

    def enqueue(self, name: str, importance: float = 0.5, source: str = "executive") -> list[FocusItem]:
        """Add an item to the priority queue, ranked by importance."""
        self._priority_queue.append(FocusItem(name=name, importance=importance, source=source))
        self._priority_queue = self.attention.rank(self._priority_queue)
        return list(self._priority_queue)

    def next_in_queue(self) -> FocusItem | None:
        """Pop and return the highest-importance queued item, or `None` if empty."""
        if not self._priority_queue:
            return None
        return self._priority_queue.pop(0)

    def priority_queue(self) -> list[FocusItem]:
        """The current priority queue, most important first."""
        return list(self._priority_queue)

    def interrupt(self, name: str, importance: float = 1.0) -> list[FocusItem]:
        """Interrupt current focus with a higher-priority item (delegates to `AttentionManager`)."""
        return self.attention.interrupt(FocusItem(name=name, importance=importance, source="interrupt"))

    def resume(self) -> list[FocusItem]:
        """Resume whatever focus was interrupted (delegates to `AttentionManager`)."""
        return self.attention.resume()

    # ------------------------------------------------------------------
    # Decision coordination (confidence-scored)
    # ------------------------------------------------------------------

    def decide(
        self,
        reason: str,
        evidence: list[str] | None = None,
        conflicts: list[str] | None = None,
        missing_information: list[str] | None = None,
        unknowns: list[str] | None = None,
    ) -> ConfidenceAssessment:
        """Score a decision via `ConfidenceEngine` and mirror the result onto the `SelfModel`."""
        assessment = self.confidence_engine.score(
            reason=reason,
            evidence=evidence,
            conflicts=conflicts,
            missing_information=missing_information,
            unknowns=unknowns,
        )
        self.self_model_engine.update(confidence=assessment.confidence)
        return assessment

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def build_context(
        self,
        conversation: list[str] | None = None,
        knowledge: list[str] | None = None,
        research: list[str] | None = None,
        tool_outputs: list[str] | None = None,
    ) -> ContextBundle:
        """Assemble a `ContextBundle` from live sources: working memory, goals, identity, and inputs."""
        return self.context_manager.assemble(
            conversation=conversation,
            working_memory=[str(item.value) for item in self.working_memory.all()],
            knowledge=knowledge,
            goals=self.providers.goals(),
            research=research,
            reflection=[r.what_happened for r in self.reflection_engine.list_reflections()[-5:]],
            tool_outputs=tool_outputs,
            identity=[self.identity.summary()],
        )

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    def health_check(self, metrics: HealthMetrics | None = None) -> HomeostasisTickResult:
        """
        Run one homeostasis tick using `metrics` (or a snapshot derived from
        current Mind state if omitted) and mirror the score onto the `SelfModel`.
        """
        resolved_metrics = metrics or HealthMetrics(
            memory_usage=min(1.0, len(self.working_memory) / 100),
            task_load=min(1.0, self._task_load / 10),
            queue_length=len(self._priority_queue),
            model_availability=self.providers.active_model() is not None or True,
        )
        result = self.homeostasis_loop.tick(
            metrics=resolved_metrics,
            progress_made=self._task_load == 0 or self.reflection_engine.list_reflections(succeeded=True) != [],
            goals=self.providers.goals(),
            mission_keywords=self.identity.mission.split() if self.identity.mission else None,
        )
        self.self_model_engine.update(health_score=self.homeostasis_engine.last_report().score)
        if not result.is_healthy:
            self.sensory.detect(SensorySignal.HIGH_CPU_LOAD, detail="Health check reported a non-healthy band.")
        return result

    def notify_owner(self, message: str) -> str:
        """
        Placeholder notification channel: logs and returns the message that would
        be sent to the owner. No real notification transport exists yet (out of
        scope for Milestone 6) — this keeps the call site (the homeostasis loop's
        `should_notify_owner`) honest about what currently happens.
        """
        logger.warning("Owner notification (no transport wired up yet): %s", message)
        return message

    def describe(self) -> str:
        """One-line human-readable summary of the current Mind state."""
        self.sync_self_model()
        return self.self_model_engine.describe()
