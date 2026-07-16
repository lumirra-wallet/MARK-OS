"""
Checkpoint System — Feature 10.

Every significant milestone can create a snapshot containing:
  - git diff / commit hash
  - conversation messages (passed from dashboard)
  - pipeline / worker state
  - metadata (goal, timestamp, workspace)

Endpoints
---------
POST /checkpoints            — create a checkpoint
GET  /checkpoints            — list checkpoints
GET  /checkpoints/{id}       — get checkpoint detail
POST /checkpoints/{id}/restore — restore checkpoint (re-applies git stash / checkout)
DELETE /checkpoints/{id}     — delete a checkpoint
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Persistence ───────────────────────────────────────────────────────────────

_CHECKPOINTS_FILE = Path(".mark_checkpoints.json")
_checkpoints: dict[str, dict] = {}


def _load() -> None:
    global _checkpoints
    if _CHECKPOINTS_FILE.exists():
        try:
            _checkpoints = json.loads(_CHECKPOINTS_FILE.read_text())
        except Exception:
            _checkpoints = {}


def _save() -> None:
    try:
        _CHECKPOINTS_FILE.write_text(json.dumps(_checkpoints, indent=2))
    except Exception as exc:
        logger.warning("Could not save checkpoints: %s", exc)


_load()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(args: list[str], cwd: str) -> tuple[str, int]:
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=cwd, timeout=15)
        return r.stdout.strip(), r.returncode
    except Exception as exc:
        return str(exc), 1


# ── Models ────────────────────────────────────────────────────────────────────

class CreateCheckpointRequest(BaseModel):
    workspace:    str         = "."
    label:        str         = ""
    goal:         str         = ""
    messages:     list[Any]   = []   # conversation snapshot from dashboard
    pipeline:     list[Any]   = []   # worker states


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/checkpoints")
async def create_checkpoint(req: CreateCheckpointRequest) -> dict:
    ws  = os.path.abspath(req.workspace)
    cid = str(uuid.uuid4())[:8]

    # Capture git state
    git_hash,   _ = _git(["rev-parse", "HEAD"], ws)
    git_branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], ws)
    git_diff,   _ = _git(["diff", "HEAD"], ws)

    # Create a git tag for easy restoration
    tag_name  = f"mark-ckpt-{cid}"
    _git(["tag", tag_name], ws)

    cp = {
        "id":         cid,
        "label":      req.label or f"Checkpoint {len(_checkpoints) + 1}",
        "created_at": _now_iso(),
        "workspace":  ws,
        "goal":       req.goal,
        "git_hash":   git_hash,
        "git_branch": git_branch,
        "git_tag":    tag_name,
        "git_diff":   git_diff[:20_000],   # cap
        "messages":   req.messages[-50:],  # last 50 messages
        "pipeline":   req.pipeline,
    }
    _checkpoints[cid] = cp
    _save()
    logger.info("Checkpoint created: %s (%s)", cid, cp["label"])
    return {k: v for k, v in cp.items() if k != "messages"}   # omit large fields


@router.get("/checkpoints")
async def list_checkpoints() -> dict:
    items = [
        {k: v for k, v in cp.items() if k not in ("messages", "git_diff")}
        for cp in sorted(_checkpoints.values(), key=lambda x: x["created_at"], reverse=True)
    ]
    return {"checkpoints": items, "count": len(items)}


@router.get("/checkpoints/{cp_id}")
async def get_checkpoint(cp_id: str) -> dict:
    cp = _checkpoints.get(cp_id)
    if cp is None:
        raise HTTPException(404, f"Checkpoint not found: {cp_id}")
    return cp


@router.post("/checkpoints/{cp_id}/restore")
async def restore_checkpoint(cp_id: str) -> dict:
    cp = _checkpoints.get(cp_id)
    if cp is None:
        raise HTTPException(404, f"Checkpoint not found: {cp_id}")
    ws  = cp["workspace"]
    tag = cp.get("git_tag", "")
    if tag:
        out, rc = _git(["checkout", tag], ws)
        if rc != 0:
            raise HTTPException(500, f"git checkout failed: {out}")
    return {"success": True, "checkpoint": cp_id, "label": cp["label"], "git_tag": tag}


@router.delete("/checkpoints/{cp_id}")
async def delete_checkpoint(cp_id: str) -> dict:
    cp = _checkpoints.pop(cp_id, None)
    if cp is None:
        raise HTTPException(404, f"Checkpoint not found: {cp_id}")
    # Remove git tag
    if cp.get("git_tag"):
        _git(["tag", "-d", cp["git_tag"]], cp.get("workspace", "."))
    _save()
    return {"success": True, "deleted": cp_id}
