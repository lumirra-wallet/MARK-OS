"""Tests for `EventBus` and the memory events it now carries."""

from smartagent.brain.events import Event, EventBus, Events
from smartagent.memory.memory_manager import MemoryManager


def test_publish_notifies_subscribers():
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe("Ping", received.append)

    event = bus.publish("Ping", value=42)

    assert received == [event]
    assert event.name == "Ping"
    assert event.payload == {"value": 42}


def test_publish_with_no_subscribers_does_not_raise():
    bus = EventBus()
    bus.publish("Nobody listening")  # should not raise


def test_history_records_every_published_event():
    bus = EventBus()
    bus.publish("First")
    bus.publish("Second")

    names = [event.name for event in bus.history()]
    assert names == ["First", "Second"]


def test_subscribers_for_different_events_stay_independent():
    bus = EventBus()
    a_events: list[Event] = []
    b_events: list[Event] = []
    bus.subscribe("A", a_events.append)
    bus.subscribe("B", b_events.append)

    bus.publish("A")

    assert len(a_events) == 1
    assert len(b_events) == 0


def test_memory_manager_publishes_memory_saved(tmp_path):
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(Events.MEMORY_SAVED, events.append)

    memory = MemoryManager(vault_path=str(tmp_path / "vault"), event_bus=bus)
    entry = memory.remember("Some fact.")

    assert len(events) == 1
    assert events[0].payload["id"] == entry.id


def test_memory_manager_publishes_memory_updated_and_deleted(tmp_path):
    bus = EventBus()
    updated: list[Event] = []
    deleted: list[Event] = []
    bus.subscribe(Events.MEMORY_UPDATED, updated.append)
    bus.subscribe(Events.MEMORY_DELETED, deleted.append)

    memory = MemoryManager(vault_path=str(tmp_path / "vault"), event_bus=bus)
    entry = memory.remember("Some fact.")

    memory.update(entry.id, content="Updated fact.")
    assert len(updated) == 1

    memory.delete(entry.id)
    assert len(deleted) == 1


def test_memory_manager_without_event_bus_does_not_raise(tmp_path):
    memory = MemoryManager(vault_path=str(tmp_path / "vault"))
    entry = memory.remember("Some fact.")
    memory.update(entry.id, content="Updated.")
    assert memory.delete(entry.id) is True
