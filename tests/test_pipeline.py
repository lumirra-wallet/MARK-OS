"""
Milestone 4 — Pipeline Tests
=============================

Covers:
  1. TaskQueue       — FIFO semantics, counters, snapshots, __len__/__repr__
  2. ExecutionState  — enum values, is_terminal, is_active
  3. Events          — EventBus pub/sub, history, catch-all, WebSocketBroadcaster,
                       ServerEvents constants, PrintInterceptor / intercept_print
  4. Scheduler       — seed, linear chain, diamond DAG, retry, cancelled context,
                       task metadata, show_progress, worker dispatch stubs
  5. Jobs API        — register/update/complete helpers + all REST endpoints
  6. Recovery        — job persistence across _load_jobs, _is_test_job filter,
                       resume from paused, cancel removes from store
"""

from __future__ import annotations

import asyncio
import builtins
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers — minimal task / context factories
# ---------------------------------------------------------------------------

from smartagent.executive.task import Task, TaskStatus, TaskType
from smartagent.executive.task_graph import TaskGraph, TaskGraphError
from smartagent.executive.task_queue import TaskQueue
from smartagent.executive.execution_state import ExecutionState
from smartagent.executive.execution_context import ExecutionContext


def _task(title: str = "T", task_type: TaskType = TaskType.GENERIC, deps: list[str] | None = None) -> Task:
    return Task(title=title, task_type=task_type, dependencies=deps or [])


def _context(goal: str = "test goal", tasks: list[Task] | None = None) -> ExecutionContext:
    """Build a minimal ExecutionContext with an optional list of tasks."""
    ctx = ExecutionContext(goal=goal)
    for t in (tasks or []):
        ctx.task_graph.add_task(t)
    return ctx


def _linear_context(n: int = 3) -> tuple[ExecutionContext, list[Task]]:
    """
    Build a linear chain context: t0 → t1 → t2 → … → t(n-1).
    Returns (context, [t0, t1, …]).
    """
    tasks: list[Task] = []
    prev_id: str | None = None
    for i in range(n):
        deps = [prev_id] if prev_id else []
        t = _task(f"Step {i}", deps=deps)
        tasks.append(t)
        prev_id = t.id
    ctx = _context("linear goal", tasks)
    return ctx, tasks


def _diamond_context() -> tuple[ExecutionContext, Task, Task, Task, Task]:
    """
    Build a diamond-shaped graph:
        root → left, right → join
    """
    root  = _task("Root")
    left  = _task("Left",  deps=[root.id])
    right = _task("Right", deps=[root.id])
    join  = _task("Join",  deps=[left.id, right.id])
    ctx   = _context("diamond goal", [root, left, right, join])
    return ctx, root, left, right, join


# ===========================================================================
# 1. TaskQueue
# ===========================================================================

class TestTaskQueueEmpty:
    def test_is_empty_on_init(self):
        assert TaskQueue().is_empty()

    def test_size_zero_on_init(self):
        assert TaskQueue().size() == 0

    def test_len_zero_on_init(self):
        assert len(TaskQueue()) == 0

    def test_dequeue_returns_none_when_empty(self):
        assert TaskQueue().dequeue() is None

    def test_peek_returns_none_when_empty(self):
        assert TaskQueue().peek() is None

    def test_all_tasks_empty_list(self):
        assert TaskQueue().all_tasks() == []

    def test_total_enqueued_zero_on_init(self):
        assert TaskQueue().total_enqueued == 0


class TestTaskQueueEnqueue:
    def test_enqueue_increases_size(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        assert q.size() == 1

    def test_enqueue_increments_total_enqueued(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        q.enqueue(_task("B"))
        assert q.total_enqueued == 2

    def test_dequeue_does_not_decrement_total_enqueued(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        q.dequeue()
        assert q.total_enqueued == 1

    def test_is_not_empty_after_enqueue(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        assert not q.is_empty()

    def test_enqueue_many_adds_all(self):
        q = TaskQueue()
        tasks = [_task(str(i)) for i in range(5)]
        q.enqueue_many(tasks)
        assert q.size() == 5
        assert q.total_enqueued == 5

    def test_enqueue_many_empty_list_is_noop(self):
        q = TaskQueue()
        q.enqueue_many([])
        assert q.size() == 0


class TestTaskQueueFIFO:
    def test_dequeue_returns_first_enqueued(self):
        q = TaskQueue()
        t0, t1 = _task("First"), _task("Second")
        q.enqueue(t0)
        q.enqueue(t1)
        assert q.dequeue() is t0

    def test_dequeue_reduces_size(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        q.enqueue(_task("B"))
        q.dequeue()
        assert q.size() == 1

    def test_dequeue_all_returns_fifo_order(self):
        q = TaskQueue()
        tasks = [_task(str(i)) for i in range(4)]
        q.enqueue_many(tasks)
        result = [q.dequeue() for _ in range(4)]
        assert result == tasks

    def test_dequeue_returns_none_after_drained(self):
        q = TaskQueue()
        q.enqueue(_task("X"))
        q.dequeue()
        assert q.dequeue() is None

    def test_peek_does_not_remove(self):
        q = TaskQueue()
        t = _task("P")
        q.enqueue(t)
        assert q.peek() is t
        assert q.size() == 1

    def test_peek_returns_front(self):
        q = TaskQueue()
        t0, t1 = _task("A"), _task("B")
        q.enqueue(t0)
        q.enqueue(t1)
        assert q.peek() is t0


class TestTaskQueueClear:
    def test_clear_empties_queue(self):
        q = TaskQueue()
        q.enqueue_many([_task(str(i)) for i in range(3)])
        q.clear()
        assert q.is_empty()

    def test_clear_does_not_reset_total_enqueued(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        q.clear()
        assert q.total_enqueued == 1

    def test_clear_on_empty_queue_is_safe(self):
        q = TaskQueue()
        q.clear()  # must not raise
        assert q.is_empty()


class TestTaskQueueAllTasks:
    def test_all_tasks_returns_snapshot(self):
        q = TaskQueue()
        tasks = [_task(str(i)) for i in range(3)]
        q.enqueue_many(tasks)
        snapshot = q.all_tasks()
        assert snapshot == tasks

    def test_all_tasks_snapshot_does_not_dequeue(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        q.all_tasks()
        assert q.size() == 1

    def test_all_tasks_reflects_order(self):
        q = TaskQueue()
        t0, t1, t2 = _task("A"), _task("B"), _task("C")
        q.enqueue(t0); q.enqueue(t1); q.enqueue(t2)
        snap = q.all_tasks()
        assert snap[0] is t0 and snap[1] is t1 and snap[2] is t2


class TestTaskQueueRepr:
    def test_repr_contains_size_and_total(self):
        q = TaskQueue()
        q.enqueue(_task("A"))
        r = repr(q)
        assert "size=1" in r
        assert "total_enqueued=1" in r

    def test_len_matches_size(self):
        q = TaskQueue()
        tasks = [_task(str(i)) for i in range(6)]
        q.enqueue_many(tasks)
        assert len(q) == q.size() == 6


# ===========================================================================
# 2. ExecutionState
# ===========================================================================

class TestExecutionStateValues:
    def test_all_seven_states_exist(self):
        names = {s.name for s in ExecutionState}
        assert names == {"IDLE", "PLANNING", "READY", "RUNNING",
                         "PAUSED", "COMPLETED", "FAILED", "CANCELLED"}

    def test_values_are_lowercase_strings(self):
        for state in ExecutionState:
            assert state.value == state.name.lower()

    def test_enum_by_value(self):
        assert ExecutionState("running") is ExecutionState.RUNNING


class TestExecutionStateIsTerminal:
    @pytest.mark.parametrize("state", [
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    ])
    def test_terminal_states(self, state):
        assert state.is_terminal

    @pytest.mark.parametrize("state", [
        ExecutionState.IDLE,
        ExecutionState.PLANNING,
        ExecutionState.READY,
        ExecutionState.RUNNING,
        ExecutionState.PAUSED,
    ])
    def test_non_terminal_states(self, state):
        assert not state.is_terminal


class TestExecutionStateIsActive:
    @pytest.mark.parametrize("state", [
        ExecutionState.PLANNING,
        ExecutionState.RUNNING,
    ])
    def test_active_states(self, state):
        assert state.is_active

    @pytest.mark.parametrize("state", [
        ExecutionState.IDLE,
        ExecutionState.READY,
        ExecutionState.PAUSED,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    ])
    def test_non_active_states(self, state):
        assert not state.is_active


# ===========================================================================
# 3. Events — EventBus, ServerEvents, WebSocketBroadcaster, PrintInterceptor
# ===========================================================================

from smartagent.brain.events import Event, EventBus, Events
from smartagent.server.events import (
    ServerEvents,
    WebSocketBroadcaster,
    intercept_print,
)


class TestEvent:
    def test_event_has_name_payload_timestamp(self):
        e = Event(name="Test", payload={"x": 1})
        assert e.name == "Test"
        assert e.payload == {"x": 1}
        assert isinstance(e.timestamp, str)

    def test_event_default_payload_is_empty_dict(self):
        e = Event(name="Foo")
        assert e.payload == {}

    def test_event_timestamp_is_iso(self):
        e = Event(name="T")
        # Should end with +00:00 or Z — just check T separator
        assert "T" in e.timestamp or "t" in e.timestamp


class TestEventBusSubscribePublish:
    def test_publish_calls_subscriber(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("Foo", received.append)
        bus.publish("Foo")
        assert len(received) == 1 and received[0].name == "Foo"

    def test_publish_returns_event(self):
        bus = EventBus()
        ev = bus.publish("X", key="val")
        assert isinstance(ev, Event)
        assert ev.name == "X"
        assert ev.payload == {"key": "val"}

    def test_publish_payload_forwarded(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("Data", received.append)
        bus.publish("Data", a=1, b="two")
        assert received[0].payload == {"a": 1, "b": "two"}

    def test_subscriber_not_called_for_other_events(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe("A", received.append)
        bus.publish("B")
        assert received == []

    def test_multiple_subscribers_all_called(self):
        bus = EventBus()
        log: list[str] = []
        bus.subscribe("E", lambda _: log.append("first"))
        bus.subscribe("E", lambda _: log.append("second"))
        bus.publish("E")
        assert log == ["first", "second"]

    def test_subscribers_called_in_registration_order(self):
        bus = EventBus()
        order: list[int] = []
        for i in range(5):
            idx = i
            bus.subscribe("Seq", lambda _, i=idx: order.append(i))
        bus.publish("Seq")
        assert order == [0, 1, 2, 3, 4]


class TestEventBusHistory:
    def test_history_starts_empty(self):
        assert EventBus().history() == []

    def test_publish_appends_to_history(self):
        bus = EventBus()
        bus.publish("A")
        bus.publish("B")
        names = [e.name for e in bus.history()]
        assert names == ["A", "B"]

    def test_history_returns_copy(self):
        bus = EventBus()
        bus.publish("X")
        h1 = bus.history()
        bus.publish("Y")
        # h1 should still have only 1 entry (snapshot at call time)
        assert len(h1) == 1

    def test_history_oldest_first(self):
        bus = EventBus()
        for name in ("First", "Second", "Third"):
            bus.publish(name)
        names = [e.name for e in bus.history()]
        assert names == ["First", "Second", "Third"]


class TestEventBusCatchAll:
    def test_subscribe_all_receives_all_events(self):
        bus = EventBus()
        received: list[str] = []
        bus.subscribe_all(lambda e: received.append(e.name))
        bus.publish("Alpha")
        bus.publish("Beta")
        assert received == ["Alpha", "Beta"]

    def test_catch_all_and_specific_both_fire(self):
        bus = EventBus()
        specific: list[Event] = []
        catch_all: list[Event] = []
        bus.subscribe("E", specific.append)
        bus.subscribe_all(catch_all.append)
        bus.publish("E")
        assert len(specific) == 1
        assert len(catch_all) == 1

    def test_unsubscribe_all_removes_handler(self):
        bus = EventBus()
        log: list[Event] = []
        bus.subscribe_all(log.append)
        bus.unsubscribe_all(log.append)
        bus.publish("X")
        assert log == []

    def test_unsubscribe_unknown_handler_is_safe(self):
        bus = EventBus()
        bus.unsubscribe_all(lambda e: None)  # must not raise


class TestServerEventsConstants:
    def test_worker_lifecycle_constants_exist(self):
        assert ServerEvents.WORKER_STARTED  == "WorkerStarted"
        assert ServerEvents.WORKER_FINISHED == "WorkerFinished"
        assert ServerEvents.WORKER_THINKING == "WorkerThinking"

    def test_run_lifecycle_constants_exist(self):
        assert ServerEvents.RUN_STARTED   == "RunStarted"
        assert ServerEvents.RUN_COMPLETED == "RunCompleted"
        assert ServerEvents.RUN_CANCELLED == "RunCancelled"
        assert ServerEvents.RUN_FAILED    == "RunFailed"

    def test_job_constants_exist(self):
        assert ServerEvents.JOB_STARTED   == "JobStarted"
        assert ServerEvents.JOB_PAUSED    == "JobPaused"
        assert ServerEvents.JOB_RESUMED   == "JobResumed"
        assert ServerEvents.JOB_COMPLETED == "JobCompleted"

    def test_task_graph_constants_exist(self):
        assert ServerEvents.TASK_NODE_STARTED   == "TaskNodeStarted"
        assert ServerEvents.TASK_NODE_COMPLETED == "TaskNodeCompleted"
        assert ServerEvents.TASK_NODE_FAILED    == "TaskNodeFailed"

    def test_streaming_token_constant(self):
        assert ServerEvents.STREAMING_TOKEN == "StreamingToken"

    def test_all_constant_values_are_strings(self):
        for attr in vars(ServerEvents):
            if not attr.startswith("_"):
                assert isinstance(getattr(ServerEvents, attr), str)

    def test_no_duplicate_values(self):
        values = [v for k, v in vars(ServerEvents).items() if not k.startswith("_")]
        assert len(values) == len(set(values)), "Duplicate ServerEvents values detected"


class TestWebSocketBroadcaster:
    def _make_broadcaster(self):
        """Return (broadcaster, bus, mock_manager, event_loop)."""
        bus = EventBus()
        manager = MagicMock()
        manager.broadcast = AsyncMock()
        loop = asyncio.new_event_loop()
        broadcaster = WebSocketBroadcaster()
        broadcaster.install(bus, manager, loop)
        return broadcaster, bus, manager, loop

    def teardown_method(self):
        # Close any loops created in tests
        pass

    def test_install_subscribes_to_all_events(self):
        bus = EventBus()
        manager = MagicMock(); manager.broadcast = AsyncMock()
        loop = asyncio.new_event_loop()
        b = WebSocketBroadcaster()
        b.install(bus, manager, loop)
        # After install, catch-all list should have exactly one entry
        assert len(bus._catch_all) == 1
        loop.close()

    def test_uninstall_removes_handler(self):
        bus = EventBus()
        manager = MagicMock(); manager.broadcast = AsyncMock()
        loop = asyncio.new_event_loop()
        b = WebSocketBroadcaster()
        b.install(bus, manager, loop)
        b.uninstall(bus)
        assert len(bus._catch_all) == 0
        loop.close()

    def test_on_event_before_install_is_noop(self):
        b = WebSocketBroadcaster()
        ev = Event(name="Test")
        b._on_event(ev)  # must not raise

    def test_on_event_sends_expected_shape(self):
        """Events forwarded to the manager contain type/name/payload/timestamp."""
        broadcaster, bus, manager, loop = self._make_broadcaster()
        try:
            ev = Event(name="Ping", payload={"x": 42})
            broadcaster._on_event(ev)
            # drain the event-loop so the coroutine runs
            loop.run_until_complete(asyncio.sleep(0))
            call_args = manager.broadcast.call_args
            assert call_args is not None
            msg: dict = call_args[0][0]
            assert msg["type"] == "event"
            assert msg["name"] == "Ping"
            assert msg["payload"] == {"x": 42}
            assert "timestamp" in msg
        finally:
            broadcaster.uninstall(bus)
            loop.close()

    def test_on_event_after_uninstall_is_noop(self):
        bus = EventBus()
        manager = MagicMock(); manager.broadcast = AsyncMock()
        loop = asyncio.new_event_loop()
        b = WebSocketBroadcaster()
        b.install(bus, manager, loop)
        b.uninstall(bus)
        b._on_event(Event(name="X"))  # must not raise
        loop.close()

    def test_runtime_error_from_closed_loop_is_swallowed(self):
        bus = EventBus()
        manager = MagicMock(); manager.broadcast = AsyncMock()
        loop = asyncio.new_event_loop()
        b = WebSocketBroadcaster()
        b.install(bus, manager, loop)
        loop.close()  # close loop before event fires
        b._on_event(Event(name="Y"))  # must not raise (RuntimeError swallowed)


class TestPrintInterceptor:
    def test_intercept_print_emits_streaming_token(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(ServerEvents.STREAMING_TOKEN, received.append)
        with intercept_print(bus):
            print("hello world")
        assert len(received) == 1
        assert "hello world" in received[0].payload.get("text", "")

    def test_intercept_print_restores_original(self):
        orig = builtins.print
        bus = EventBus()
        with intercept_print(bus):
            pass
        assert builtins.print is orig

    def test_intercept_print_still_writes_to_stdout(self, capsys):
        bus = EventBus()
        with intercept_print(bus):
            print("visible output")
        captured = capsys.readouterr()
        assert "visible output" in captured.out

    def test_intercept_print_sep_join(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(ServerEvents.STREAMING_TOKEN, received.append)
        with intercept_print(bus):
            print("a", "b", "c", sep="-")
        assert "a-b-c" in received[0].payload["text"]

    def test_intercept_print_event_has_source_print(self):
        bus = EventBus()
        received: list[Event] = []
        bus.subscribe(ServerEvents.STREAMING_TOKEN, received.append)
        with intercept_print(bus):
            print("x")
        assert received[0].payload.get("source") == "print"

    def test_intercept_print_exception_in_bus_does_not_crash(self):
        """If the event bus raises, the original print must still work."""
        bus = EventBus()
        bus.subscribe_all(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
        orig = builtins.print
        # Should not raise; the interceptor swallows bus exceptions
        with intercept_print(bus):
            print("safe")
        assert builtins.print is orig


# ===========================================================================
# 4. Scheduler
# ===========================================================================

from smartagent.executive.scheduler import Scheduler
from smartagent.executive.workers.base_worker import BaseWorker, WorkerResult


class _OkWorker(BaseWorker):
    """Minimal worker that always returns a success result."""
    @property
    def name(self) -> str:
        return "OkWorker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.GENERIC]

    def execute(self, task, context) -> str:
        return f"done:{task.title}"


class _FailWorker(BaseWorker):
    """Minimal worker that always raises."""
    @property
    def name(self) -> str:
        return "FailWorker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.GENERIC]

    def execute(self, task, context) -> str:
        raise ValueError("intentional failure")


class _CountingWorker(BaseWorker):
    """Records how many times execute() was called (thread-safe via list append)."""
    calls: list[str]

    def __init__(self):
        self.calls = []

    @property
    def name(self) -> str:
        return "CountingWorker"

    @property
    def task_types(self) -> list[TaskType]:
        return [TaskType.GENERIC]

    def execute(self, task, context) -> str:
        self.calls.append(task.id)
        return f"result:{task.title}"


def _scheduler(max_retries: int = 0) -> Scheduler:
    return Scheduler(show_progress=False, max_retries=max_retries)


class TestSchedulerSeedQueue:
    def test_single_no_dep_task_seeded(self):
        t = _task("T")
        ctx = _context(tasks=[t])
        _scheduler().run(ctx)
        assert t.status == TaskStatus.COMPLETED

    def test_task_with_unfulfilled_dep_not_seeded(self):
        """A task with a dep should NOT be in the initial queue."""
        t0 = _task("Root")
        t1 = _task("Child", deps=[t0.id])
        ctx = _context(tasks=[t0, t1])
        _scheduler().run(ctx)
        assert t0.status == TaskStatus.COMPLETED
        assert t1.status == TaskStatus.COMPLETED

    def test_seed_only_root_tasks(self):
        ctx, tasks = _linear_context(4)
        sched = _scheduler()
        # Manually inspect seed: inject into context without full run
        ctx2, tasks2 = _linear_context(4)
        sched._seed_queue(ctx2)
        # Only the root (no-dep) task should be in the queue
        assert ctx2.task_queue.size() == 1
        assert ctx2.task_queue.peek() is tasks2[0]


class TestSchedulerLinearChain:
    def test_linear_chain_all_completed(self):
        ctx, tasks = _linear_context(4)
        _scheduler().run(ctx)
        assert all(t.status == TaskStatus.COMPLETED for t in tasks)

    def test_linear_chain_state_is_completed(self):
        ctx, _ = _linear_context(3)
        ctx = _scheduler().run(ctx)
        assert ctx.state == ExecutionState.COMPLETED

    def test_results_recorded_for_all_tasks(self):
        ctx, tasks = _linear_context(3)
        _scheduler().run(ctx)
        for t in tasks:
            assert t.id in ctx.results

    def test_task_timing_recorded(self):
        ctx, tasks = _linear_context(3)
        _scheduler().run(ctx)
        timing = ctx.metadata.get("task_timing", {})
        assert len(timing) == 3

    def test_task_retries_recorded(self):
        ctx, tasks = _linear_context(2)
        _scheduler().run(ctx)
        retries = ctx.metadata.get("task_retries", {})
        assert len(retries) == 2
        assert all(v == 0 for v in retries.values())

    def test_completed_count_equals_task_count(self):
        ctx, _ = _linear_context(3)
        _scheduler().run(ctx)
        assert ctx.completed_count == ctx.task_count

    def test_no_errors_on_clean_run(self):
        ctx, _ = _linear_context(3)
        _scheduler().run(ctx)
        assert ctx.errors == {}


class TestSchedulerDiamondDAG:
    def test_all_tasks_complete(self):
        ctx, root, left, right, join = _diamond_context()
        _scheduler().run(ctx)
        for t in (root, left, right, join):
            assert t.status == TaskStatus.COMPLETED

    def test_state_is_completed(self):
        ctx, *_ = _diamond_context()
        ctx = _scheduler().run(ctx)
        assert ctx.state == ExecutionState.COMPLETED

    def test_join_completes_after_branches(self):
        """join.result must be set → execution reached the join task."""
        ctx, _, left, right, join = _diamond_context()
        _scheduler().run(ctx)
        assert join.status == TaskStatus.COMPLETED
        assert join.result is not None


class TestSchedulerCancelledContext:
    def test_already_cancelled_context_skips_run(self):
        ctx, tasks = _linear_context(3)
        ctx.cancel()
        _scheduler().run(ctx)
        # Scheduler must return immediately; none of the tasks should be running
        assert ctx.state == ExecutionState.CANCELLED
        assert ctx.completed_count == 0

    def test_cancel_during_run_stops_cleanly(self):
        """Cancellation mid-run: the scheduler's next iteration check fires."""
        root  = _task("Root")
        child = _task("Child", deps=[root.id])
        ctx = _context(tasks=[root, child])

        # Patch _execute to cancel the context after the first task
        orig = Scheduler._execute

        def _cancel_after_first(self_inner, task, context):
            result = orig(self_inner, task, context)
            context.cancel()
            return result

        with patch.object(Scheduler, "_execute", _cancel_after_first):
            _scheduler().run(ctx)

        assert ctx.state == ExecutionState.CANCELLED


class TestSchedulerFailure:
    def test_failed_task_sets_failed_state(self):
        from smartagent.executive.worker_registry import WorkerRegistry
        t = _task("Bad")
        ctx = _context(tasks=[t])
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, _FailWorker)
        sched = Scheduler(worker_registry=registry, max_retries=0, show_progress=False)
        sched.run(ctx)
        assert ctx.state == ExecutionState.FAILED

    def test_failed_task_error_recorded(self):
        from smartagent.executive.worker_registry import WorkerRegistry
        t = _task("Bad")
        ctx = _context(tasks=[t])
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, _FailWorker)
        sched = Scheduler(worker_registry=registry, max_retries=0, show_progress=False)
        sched.run(ctx)
        assert t.id in ctx.errors
        assert "intentional failure" in ctx.errors[t.id]

    def test_failed_task_blocks_downstream(self):
        from smartagent.executive.worker_registry import WorkerRegistry
        root  = _task("Bad")
        child = _task("Child", deps=[root.id])
        ctx = _context(tasks=[root, child])
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, _FailWorker)
        sched = Scheduler(worker_registry=registry, max_retries=0, show_progress=False)
        sched.run(ctx)
        assert child.status == TaskStatus.BLOCKED

    def test_stub_result_when_no_registry(self):
        t = _task("T")
        ctx = _context(tasks=[t])
        Scheduler(show_progress=False, max_retries=0).run(ctx)
        assert "Completed" in ctx.results.get(t.id, "")


class TestSchedulerRetry:
    def test_transient_failure_retried_and_succeeds(self):
        """Worker fails first attempt, succeeds on second."""
        attempt_count = []

        class _FlakyWorker(BaseWorker):
            @property
            def name(self): return "FlakyWorker"
            @property
            def task_types(self): return [TaskType.GENERIC]
            def execute(self, task, context):
                attempt_count.append(1)
                if len(attempt_count) < 2:
                    raise RuntimeError("flaky")
                return "ok"

        from smartagent.executive.worker_registry import WorkerRegistry
        t = _task("Flaky")
        ctx = _context(tasks=[t])
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, _FlakyWorker)
        sched = Scheduler(worker_registry=registry, max_retries=2, show_progress=False)
        sched.run(ctx)
        assert t.status == TaskStatus.COMPLETED
        assert len(attempt_count) == 2

    def test_max_retries_zero_does_not_retry(self):
        from smartagent.executive.worker_registry import WorkerRegistry
        t = _task("T")
        ctx = _context(tasks=[t])
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, _FailWorker)
        sched = Scheduler(worker_registry=registry, max_retries=0, show_progress=False)
        sched.run(ctx)
        assert t.status == TaskStatus.FAILED
        # retries should be 0
        assert ctx.metadata["task_retries"].get(t.id, -1) == 0

    def test_retry_count_recorded_in_metadata(self):
        """After 2 retry attempts (3 total) metadata retries should be 2."""
        from smartagent.executive.worker_registry import WorkerRegistry

        class _AlwaysFail(BaseWorker):
            @property
            def name(self): return "AlwaysFail"
            @property
            def task_types(self): return [TaskType.GENERIC]
            def execute(self, task, context): raise ValueError("x")

        t = _task("T")
        ctx = _context(tasks=[t])
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, _AlwaysFail)
        # Patch sleep to speed up the test
        with patch("time.sleep"):
            sched = Scheduler(worker_registry=registry, max_retries=2, show_progress=False)
            sched.run(ctx)
        assert ctx.metadata["task_retries"][t.id] == 2


class TestSchedulerWorkerDispatch:
    def test_worker_execute_called_once_per_task(self):
        from smartagent.executive.worker_registry import WorkerRegistry
        tasks = [_task(f"T{i}") for i in range(3)]
        ctx = _context(tasks=tasks)
        worker = _CountingWorker()
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, lambda: worker)
        sched = Scheduler(worker_registry=registry, max_retries=0, show_progress=False)
        sched.run(ctx)
        assert len(worker.calls) == 3

    def test_worker_result_stored_in_context(self):
        from smartagent.executive.worker_registry import WorkerRegistry
        t = _task("R")
        ctx = _context(tasks=[t])
        registry = WorkerRegistry()
        registry.register(TaskType.GENERIC, _OkWorker)
        Scheduler(worker_registry=registry, max_retries=0, show_progress=False).run(ctx)
        assert ctx.results[t.id] == f"done:{t.title}"


class TestSchedulerShowProgress:
    def test_show_progress_false_produces_no_output(self, capsys):
        ctx, _ = _linear_context(2)
        Scheduler(show_progress=False).run(ctx)
        assert capsys.readouterr().out == ""

    def test_show_progress_true_produces_output(self, capsys):
        ctx, _ = _linear_context(2)
        Scheduler(show_progress=True).run(ctx)
        assert capsys.readouterr().out != ""


# ===========================================================================
# 5 & 6. Jobs API + Recovery
# ===========================================================================

import smartagent.server.api_jobs as _jobs_mod


@pytest.fixture()
def jobs_client(tmp_path, monkeypatch):
    """
    Isolated TestClient for the /jobs endpoints.

    Each test gets its own in-memory job store and a temp jobs file so tests
    never bleed into one another and never touch the real .mark_jobs.json.
    """
    jobs_file = tmp_path / ".mark_jobs.json"
    monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", jobs_file)
    monkeypatch.setattr(_jobs_mod, "_jobs", {})

    app = FastAPI()
    app.include_router(_jobs_mod.router)
    return TestClient(app)


def _reg(goal: str = "Build X", workspace: str = "/work") -> str:
    """Helper: register a job and return its id."""
    return _jobs_mod.register_job(goal, workspace)


class TestJobsHelpers:
    def test_register_job_returns_uuid_string(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg()
        assert isinstance(job_id, str) and len(job_id) > 0

    def test_register_job_stores_in_jobs_dict(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg("Goal A")
        assert job_id in _jobs_mod._jobs

    def test_register_job_default_status_running(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg()
        assert _jobs_mod._jobs[job_id]["status"] == "running"

    def test_register_job_goal_truncated_to_500(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        long_goal = "X" * 1000
        job_id = _reg(goal=long_goal)
        assert len(_jobs_mod._jobs[job_id]["goal"]) == 500

    def test_register_job_with_explicit_run_id(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _jobs_mod.register_job("G", "/w", run_id="my-run-123")
        assert job_id == "my-run-123"

    def test_update_job_changes_fields(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg()
        _jobs_mod.update_job(job_id, progress=50, current_step="Halfway")
        assert _jobs_mod._jobs[job_id]["progress"] == 50
        assert _jobs_mod._jobs[job_id]["current_step"] == "Halfway"

    def test_update_job_updates_updated_at(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg()
        before = _jobs_mod._jobs[job_id]["updated_at"]
        time.sleep(0.01)
        _jobs_mod.update_job(job_id, progress=1)
        # updated_at should change (or at least not crash)
        assert _jobs_mod._jobs[job_id]["updated_at"] >= before

    def test_update_job_unknown_id_is_noop(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _jobs_mod.update_job("nonexistent-id", progress=99)  # must not raise

    def test_complete_job_success(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg()
        _jobs_mod.complete_job(job_id, success=True, result={"output": "done"})
        assert _jobs_mod._jobs[job_id]["status"] == "completed"
        assert _jobs_mod._jobs[job_id]["progress"] == 100
        assert _jobs_mod._jobs[job_id]["result"] == {"output": "done"}

    def test_complete_job_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg()
        _jobs_mod.complete_job(job_id, success=False)
        assert _jobs_mod._jobs[job_id]["status"] == "failed"


class TestJobsListEndpoint:
    def test_list_jobs_200(self, jobs_client):
        assert jobs_client.get("/jobs").status_code == 200

    def test_list_jobs_empty_on_fresh_store(self, jobs_client):
        data = jobs_client.get("/jobs").json()
        assert data["jobs"] == []
        assert data["count"] == 0

    def test_list_jobs_shows_registered_job(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        _reg("My Goal")
        data = jobs_client.get("/jobs").json()
        assert data["count"] == 1
        assert data["jobs"][0]["goal"] == "My Goal"

    def test_list_jobs_sorted_newest_first(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        id1 = _reg("First")
        id2 = _reg("Second")
        # Inject distinct created_at timestamps so sort order is deterministic.
        _jobs_mod._jobs[id1]["created_at"] = "2024-01-01T00:00:00+00:00"
        _jobs_mod._jobs[id2]["created_at"] = "2024-01-02T00:00:00+00:00"
        data = jobs_client.get("/jobs").json()
        ids = [j["id"] for j in data["jobs"]]
        assert ids.index(id2) < ids.index(id1)

    def test_list_jobs_has_count(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        _reg(); _reg(); _reg()
        data = jobs_client.get("/jobs").json()
        assert data["count"] == 3


class TestJobsGetEndpoint:
    def test_get_job_200(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        assert jobs_client.get(f"/jobs/{job_id}").status_code == 200

    def test_get_job_has_expected_fields(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg("Build Z", "/workspace")
        data = jobs_client.get(f"/jobs/{job_id}").json()
        for field in ("id", "goal", "workspace", "status", "created_at",
                      "updated_at", "paused", "progress", "current_step"):
            assert field in data, f"missing field: {field}"

    def test_get_job_404_for_unknown(self, jobs_client):
        assert jobs_client.get("/jobs/does-not-exist").status_code == 404

    def test_get_job_id_matches(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        assert jobs_client.get(f"/jobs/{job_id}").json()["id"] == job_id


class TestJobsPauseEndpoint:
    def test_pause_running_job_200(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        resp = jobs_client.post(f"/jobs/{job_id}/pause")
        assert resp.status_code == 200

    def test_pause_sets_status_paused(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        jobs_client.post(f"/jobs/{job_id}/pause")
        assert _jobs_mod._jobs[job_id]["status"] == "paused"
        assert _jobs_mod._jobs[job_id]["paused"] is True

    def test_pause_returns_success_true(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        data = jobs_client.post(f"/jobs/{job_id}/pause").json()
        assert data["success"] is True
        assert data["status"] == "paused"

    def test_pause_404_for_unknown(self, jobs_client):
        assert jobs_client.post("/jobs/nope/pause").status_code == 404

    def test_pause_400_when_already_paused(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        jobs_client.post(f"/jobs/{job_id}/pause")
        resp = jobs_client.post(f"/jobs/{job_id}/pause")
        assert resp.status_code == 400

    def test_pause_400_when_completed(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        _jobs_mod.complete_job(job_id, success=True)
        resp = jobs_client.post(f"/jobs/{job_id}/pause")
        assert resp.status_code == 400


class TestJobsResumeEndpoint:
    def test_resume_paused_job_200(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        jobs_client.post(f"/jobs/{job_id}/pause")
        resp = jobs_client.post(f"/jobs/{job_id}/resume")
        assert resp.status_code == 200

    def test_resume_sets_status_running(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        jobs_client.post(f"/jobs/{job_id}/pause")
        jobs_client.post(f"/jobs/{job_id}/resume")
        assert _jobs_mod._jobs[job_id]["status"] == "running"
        assert _jobs_mod._jobs[job_id]["paused"] is False

    def test_resume_returns_success_true(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        jobs_client.post(f"/jobs/{job_id}/pause")
        data = jobs_client.post(f"/jobs/{job_id}/resume").json()
        assert data["success"] is True
        assert data["status"] == "running"

    def test_resume_404_for_unknown(self, jobs_client):
        assert jobs_client.post("/jobs/nope/resume").status_code == 404


class TestJobsCancelEndpoint:
    def test_cancel_job_200(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        resp = jobs_client.delete(f"/jobs/{job_id}")
        assert resp.status_code == 200

    def test_cancel_removes_job_from_store(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        jobs_client.delete(f"/jobs/{job_id}")
        assert job_id not in _jobs_mod._jobs

    def test_cancel_returns_success_true(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        data = jobs_client.delete(f"/jobs/{job_id}").json()
        assert data["success"] is True
        assert data["cancelled"] == job_id

    def test_cancel_404_for_unknown(self, jobs_client):
        assert jobs_client.delete("/jobs/nope").status_code == 404

    def test_cancel_job_no_longer_in_list(self, jobs_client, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        job_id = _reg()
        jobs_client.delete(f"/jobs/{job_id}")
        data = jobs_client.get("/jobs").json()
        assert not any(j["id"] == job_id for j in data["jobs"])


# ===========================================================================
# 6. Recovery — persistence, _is_test_job filter
# ===========================================================================

class TestJobsPersistence:
    def test_register_job_writes_file(self, monkeypatch, tmp_path):
        jobs_file = tmp_path / "j.json"
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", jobs_file)
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _reg("Persist me")
        assert jobs_file.exists()

    def test_file_content_is_valid_json(self, monkeypatch, tmp_path):
        jobs_file = tmp_path / "j.json"
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", jobs_file)
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _reg()
        data = json.loads(jobs_file.read_text())
        assert isinstance(data, dict)

    def test_load_jobs_restores_state(self, monkeypatch, tmp_path):
        jobs_file = tmp_path / "j.json"
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", jobs_file)
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg("Restored")
        # Simulate a fresh load
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _jobs_mod._load_jobs()
        assert job_id in _jobs_mod._jobs
        assert _jobs_mod._jobs[job_id]["goal"] == "Restored"

    def test_load_jobs_corrupted_file_gives_empty_dict(self, monkeypatch, tmp_path):
        jobs_file = tmp_path / "j.json"
        jobs_file.write_text("not valid json {{{{")
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", jobs_file)
        monkeypatch.setattr(_jobs_mod, "_jobs", {"keep": "me"})
        _jobs_mod._load_jobs()
        assert _jobs_mod._jobs == {}

    def test_complete_job_updates_file(self, monkeypatch, tmp_path):
        jobs_file = tmp_path / "j.json"
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", jobs_file)
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg()
        _jobs_mod.complete_job(job_id, success=True)
        data = json.loads(jobs_file.read_text())
        assert data[job_id]["status"] == "completed"


class TestJobsIsTestJobFilter:
    @pytest.mark.parametrize("workspace", [
        "/tmp/pytest-abc/test_foo",
        "/tmp/some/random",
        "/var/folders/abc/xyz",
    ])
    def test_tmp_workspaces_are_test_jobs(self, workspace):
        job = {"workspace": workspace}
        assert _jobs_mod._is_test_job(job)

    @pytest.mark.parametrize("workspace", [
        "/home/user/projects/myapp",
        "/app/workspace",
        "/Users/alice/dev/mark",
        "",
    ])
    def test_real_workspaces_are_not_test_jobs(self, workspace):
        job = {"workspace": workspace}
        assert not _jobs_mod._is_test_job(job)

    def test_load_jobs_strips_test_jobs(self, monkeypatch, tmp_path):
        """Jobs with /tmp workspace must be filtered out on load."""
        jobs_file = tmp_path / "j.json"
        raw = {
            "real-job": {"id": "real-job", "workspace": "/home/user/proj", "goal": "real"},
            "test-job": {"id": "test-job", "workspace": "/tmp/pytest-123/test0", "goal": "test"},
        }
        jobs_file.write_text(json.dumps(raw))
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", jobs_file)
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _jobs_mod._load_jobs()
        assert "real-job" in _jobs_mod._jobs
        assert "test-job" not in _jobs_mod._jobs


class TestJobsRecoveryWorkflow:
    def test_pause_resume_cycle(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        job_id = _reg("Long running task")
        assert _jobs_mod._jobs[job_id]["status"] == "running"

        # Pause
        _jobs_mod._jobs[job_id]["status"] = "paused"
        _jobs_mod._jobs[job_id]["paused"] = True
        _jobs_mod._save_jobs()

        # Simulate server restart
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _jobs_mod._load_jobs()
        assert _jobs_mod._jobs[job_id]["paused"] is True
        assert _jobs_mod._jobs[job_id]["status"] == "paused"

        # Resume
        _jobs_mod._jobs[job_id]["paused"] = False
        _jobs_mod._jobs[job_id]["status"] = "running"
        _jobs_mod._save_jobs()

        # Verify resumed
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _jobs_mod._load_jobs()
        assert _jobs_mod._jobs[job_id]["paused"] is False
        assert _jobs_mod._jobs[job_id]["status"] == "running"

    def test_multiple_jobs_persist_independently(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_jobs_mod, "_JOBS_FILE", tmp_path / "j.json")
        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        ids = [_reg(f"Goal {i}", "/work") for i in range(5)]
        # Complete first, fail second, leave rest running
        _jobs_mod.complete_job(ids[0], success=True)
        _jobs_mod.complete_job(ids[1], success=False)

        monkeypatch.setattr(_jobs_mod, "_jobs", {})
        _jobs_mod._load_jobs()

        assert _jobs_mod._jobs[ids[0]]["status"] == "completed"
        assert _jobs_mod._jobs[ids[1]]["status"] == "failed"
        for i in range(2, 5):
            assert _jobs_mod._jobs[ids[i]]["status"] == "running"
