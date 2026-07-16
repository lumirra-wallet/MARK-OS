"""
Long Running Jobs — Feature 14.

Background jobs persist their state to disk so the agent can be reconnected
after the browser tab closes or the server restarts.

Endpoints
---------
GET  /jobs              — list all jobs
GET  /jobs/{id}         — single job status
POST /jobs/{id}/pause   — pause (sets flag, worker checks it)
POST /jobs/{id}/resume  — resume a paused job
DELETE /jobs/{id}       — cancel and remove a job
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

_JOBS_FILE = Path(".mark_jobs.json")
_jobs: dict[str, dict] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_jobs() -> None:
    global _jobs
    if _JOBS_FILE.exists():
        try:
            _jobs = json.loads(_JOBS_FILE.read_text())
        except Exception:
            _jobs = {}


def _save_jobs() -> None:
    try:
        _JOBS_FILE.write_text(json.dumps(_jobs, indent=2))
    except Exception as exc:
        logger.warning("Could not save jobs: %s", exc)


_load_jobs()


def register_job(goal: str, workspace: str, run_id: str = "") -> str:
    """Called by api.py execute endpoint to register a new job."""
    job_id = run_id or str(uuid.uuid4())
    _jobs[job_id] = {
        "id":           job_id,
        "goal":         goal[:500],
        "workspace":    workspace,
        "status":       "running",   # running | paused | completed | failed | cancelled
        "created_at":   _now_iso(),
        "updated_at":   _now_iso(),
        "paused":       False,
        "progress":     0,
        "current_step": "Starting…",
        "result":       None,
    }
    _save_jobs()
    return job_id


def update_job(job_id: str, **kwargs: Any) -> None:
    if job_id in _jobs:
        _jobs[job_id].update(kwargs)
        _jobs[job_id]["updated_at"] = _now_iso()
        _save_jobs()


def complete_job(job_id: str, success: bool, result: dict | None = None) -> None:
    if job_id in _jobs:
        _jobs[job_id]["status"]     = "completed" if success else "failed"
        _jobs[job_id]["progress"]   = 100
        _jobs[job_id]["result"]     = result
        _jobs[job_id]["updated_at"] = _now_iso()
        _save_jobs()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def list_jobs() -> dict:
    items = sorted(_jobs.values(), key=lambda x: x["created_at"], reverse=True)
    return {"jobs": items, "count": len(items)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    return job


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    if job["status"] != "running":
        raise HTTPException(400, f"Job is not running (status: {job['status']})")
    job["paused"]      = True
    job["status"]      = "paused"
    job["updated_at"]  = _now_iso()
    _save_jobs()
    return {"success": True, "job_id": job_id, "status": "paused"}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    job["paused"]     = False
    job["status"]     = "running"
    job["updated_at"] = _now_iso()
    _save_jobs()
    return {"success": True, "job_id": job_id, "status": "running"}


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict:
    job = _jobs.pop(job_id, None)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    _save_jobs()
    return {"success": True, "cancelled": job_id}
