"""
Agent Timeline API — Feature 16 (replayable timeline).

Every WebSocket event is also appended to an in-memory timeline log so the
dashboard can replay, filter, and inspect any event from any run.

Endpoints
---------
GET  /timeline              — all timeline events (paginated)
GET  /timeline?run_id=      — events for a specific run
DELETE /timeline            — clear the timeline
POST /timeline/event        — manually append an event (used by broadcaster)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

router = APIRouter()

# ── In-memory event store ─────────────────────────────────────────────────────

_timeline: list[dict] = []
_current_run_id: str  = ""

MAX_EVENTS = 10_000


def record_event(name: str, payload: dict, run_id: str = "", timestamp: str = "") -> None:
    """Called by broadcaster / api.py to persist every WS event to the timeline."""
    global _current_run_id
    if not run_id:
        run_id = _current_run_id
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    entry = {
        "id":        str(uuid.uuid4()),
        "run_id":    run_id,
        "name":      name,
        "payload":   payload,
        "timestamp": timestamp,
    }
    _timeline.append(entry)
    if len(_timeline) > MAX_EVENTS:
        _timeline.pop(0)


def set_run_id(run_id: str) -> None:
    global _current_run_id
    _current_run_id = run_id


def new_run_id() -> str:
    global _current_run_id
    _current_run_id = str(uuid.uuid4())
    return _current_run_id


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/timeline")
async def get_timeline(
    run_id: str | None = None,
    name: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict:
    events = _timeline
    if run_id:
        events = [e for e in events if e["run_id"] == run_id]
    if name:
        events = [e for e in events if e["name"] == name]
    total  = len(events)
    page   = events[offset : offset + limit]
    runs   = list({e["run_id"] for e in _timeline if e["run_id"]})
    return {
        "events":   page,
        "total":    total,
        "offset":   offset,
        "limit":    limit,
        "run_ids":  runs[-20:],
    }


@router.delete("/timeline")
async def clear_timeline(run_id: str | None = None) -> dict:
    global _timeline
    if run_id:
        before = len(_timeline)
        _timeline = [e for e in _timeline if e["run_id"] != run_id]
        return {"cleared": before - len(_timeline)}
    count = len(_timeline)
    _timeline.clear()
    return {"cleared": count}
