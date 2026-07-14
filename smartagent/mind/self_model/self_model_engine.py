"""
SelfModelEngine — Milestone 6, Part 2.

Owns one `SelfModel` and keeps it updated in place as the rest of the Mind
(and, indirectly, the Brain) reports changes. Deliberately does not reach
out and pull data from other subsystems itself (no dependency on
`SmartAgent`, `SkillEngine`, etc.) — callers (typically
`ExecutiveController`) push updates via `update()`, keeping this engine
trivially testable in isolation and free of import cycles.
"""

from __future__ import annotations

from typing import Any

from smartagent.brain.events import EventBus, Events
from smartagent.logs.logger import get_logger
from smartagent.mind.identity.identity_model import Identity
from smartagent.mind.self_model.self_model import SelfModel

logger = get_logger(__name__)

_MAX_RECENT_CHANGES = 20


class SelfModelEngine:
    """
    Maintains a continuously-updated `SelfModel`.

    Args:
        identity: Seeds `name`/`owner`/`mission` on the initial `SelfModel`.
        event_bus: Optional bus to publish `SelfModelUpdated` onto.
    """

    def __init__(self, identity: Identity, event_bus: EventBus | None = None) -> None:
        self.events = event_bus
        self._model = SelfModel(name=identity.name, owner=identity.owner, mission=identity.mission)

    def snapshot(self) -> SelfModel:
        """Return the current `SelfModel`. Callers should treat this as read-only."""
        return self._model

    def update(self, **fields: Any) -> SelfModel:
        """
        Apply changes to the self model, record a change-log entry, and publish `SelfModelUpdated`.

        Raises:
            AttributeError: If a keyword does not name a real `SelfModel` field.
        """
        import datetime as _dt

        changed: list[str] = []
        for key, value in fields.items():
            if not hasattr(self._model, key):
                raise AttributeError(f"SelfModel has no field {key!r}.")
            old_value = getattr(self._model, key)
            if old_value != value:
                setattr(self._model, key, value)
                changed.append(f"{key}: {old_value!r} -> {value!r}")

        if not changed:
            return self._model

        self._model.last_updated = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        self._model.recent_changes.extend(changed)
        del self._model.recent_changes[:-_MAX_RECENT_CHANGES]

        logger.info("SelfModel updated: %s", "; ".join(changed))
        if self.events is not None:
            self.events.publish(Events.SELF_MODEL_UPDATED, changes=changed)
        return self._model

    def describe(self) -> str:
        """Delegate to `SelfModel.describe()` for a human-readable summary."""
        return self._model.describe()
