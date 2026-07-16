"""
Enhanced Git Integration — Feature 12.

Extends the basic git endpoints with interactive staging, commits, branches,
stash, merge, and PR summary generation.

Endpoints
---------
GET  /git/branches        — list all branches
POST /git/branch          — create + optionally checkout a new branch
POST /git/checkout        — switch to an existing branch
GET  /git/staged          — show staged diff
POST /git/stage           — git add (stage files)
POST /git/unstage         — git restore --staged (unstage files)
POST /git/commit          — create a commit
GET  /git/stashes         — list stashes
POST /git/stash           — stash working changes
POST /git/stash/pop       — apply top stash
POST /git/merge           — merge a branch into HEAD
GET  /git/pr-summary      — generate PR description (heuristic)
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


def _git(args: list[str], cwd: str, timeout: int = 15) -> tuple[str, str, int]:
    try:
        r = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return r.stdout, r.stderr, r.returncode
    except FileNotFoundError:
        return "", "git not found", 127
    except subprocess.TimeoutExpired:
        return "", "timed out", 1
    except Exception as exc:
        return "", str(exc), 1


def _active_workspace() -> str:
    try:
        from smartagent.server.api import _state
        ws = _state.workspace
        if ws and ws != ".":
            return os.path.abspath(ws)
    except Exception:
        pass
    return os.path.abspath(os.getcwd())


# ── Models ────────────────────────────────────────────────────────────────────

class BranchRequest(BaseModel):
    name:      str
    checkout:  bool  = True
    workspace: str | None = None


class CheckoutRequest(BaseModel):
    branch:    str
    workspace: str | None = None


class StageRequest(BaseModel):
    files:     list[str] = ["."]    # "." = all
    workspace: str | None = None


class UnstageRequest(BaseModel):
    files:     list[str] = ["."]
    workspace: str | None = None


class CommitRequest(BaseModel):
    message:   str
    workspace: str | None = None


class StashRequest(BaseModel):
    message:   str        = ""
    workspace: str | None = None


class MergeRequest(BaseModel):
    branch:    str
    strategy:  str        = "--no-ff"   # --ff | --no-ff | --squash
    workspace: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ws(req_workspace: str | None) -> str:
    return os.path.abspath(req_workspace) if req_workspace else _active_workspace()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/git/branches")
async def list_branches(workspace: str | None = None, all: bool = False) -> dict:
    ws   = _ws(workspace)
    args = ["branch", "--format=%(refname:short) %(objectname:short) %(subject)"]
    if all:
        args.insert(1, "-a")
    out, err, rc = _git(args, ws)
    if rc != 0:
        return {"branches": [], "error": err.strip()}
    current_out, _, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], ws)
    current = current_out.strip()
    branches = []
    for line in out.strip().splitlines():
        parts = line.split(None, 2)
        name  = parts[0] if parts else line
        short = parts[1] if len(parts) > 1 else ""
        subj  = parts[2] if len(parts) > 2 else ""
        branches.append({"name": name, "hash": short, "subject": subj, "current": name == current})
    return {"branches": branches, "current": current}


@router.post("/git/branch")
async def create_branch(req: BranchRequest) -> dict:
    ws = _ws(req.workspace)
    args = ["checkout", "-b", req.name] if req.checkout else ["branch", req.name]
    out, err, rc = _git(args, ws)
    if rc != 0:
        raise HTTPException(400, err.strip() or "branch failed")
    return {"success": True, "branch": req.name, "checked_out": req.checkout}


@router.post("/git/checkout")
async def checkout_branch(req: CheckoutRequest) -> dict:
    ws = _ws(req.workspace)
    out, err, rc = _git(["checkout", req.branch], ws)
    if rc != 0:
        raise HTTPException(400, err.strip())
    return {"success": True, "branch": req.branch}


@router.get("/git/staged")
async def get_staged(workspace: str | None = None) -> dict:
    ws       = _ws(workspace)
    diff,  _, _ = _git(["diff", "--cached"], ws)
    stat,  _, _ = _git(["diff", "--cached", "--stat"], ws)
    names, _, _ = _git(["diff", "--cached", "--name-only"], ws)
    return {
        "diff":  diff,
        "stat":  stat,
        "files": [f for f in names.strip().splitlines() if f],
    }


@router.post("/git/stage")
async def stage_files(req: StageRequest) -> dict:
    ws   = _ws(req.workspace)
    args = ["add"] + (req.files if req.files else ["."])
    out, err, rc = _git(args, ws)
    if rc != 0:
        raise HTTPException(400, err.strip())
    stat, _, _ = _git(["diff", "--cached", "--stat"], ws)
    return {"success": True, "staged": req.files, "stat": stat}


@router.post("/git/unstage")
async def unstage_files(req: UnstageRequest) -> dict:
    ws   = _ws(req.workspace)
    args = ["restore", "--staged"] + (req.files if req.files else ["."])
    out, err, rc = _git(args, ws)
    if rc != 0:
        raise HTTPException(400, err.strip())
    return {"success": True, "unstaged": req.files}


@router.post("/git/commit")
async def git_commit(req: CommitRequest) -> dict:
    ws = _ws(req.workspace)
    if not req.message.strip():
        raise HTTPException(400, "Commit message cannot be empty")
    out, err, rc = _git(["commit", "-m", req.message], ws)
    if rc != 0:
        raise HTTPException(400, err.strip() or out.strip() or "commit failed")
    hash_out, _, _ = _git(["rev-parse", "--short", "HEAD"], ws)
    return {"success": True, "hash": hash_out.strip(), "message": req.message, "output": out.strip()}


@router.get("/git/stashes")
async def list_stashes(workspace: str | None = None) -> dict:
    ws  = _ws(workspace)
    out, err, rc = _git(["stash", "list", "--format=%gd %s %cr"], ws)
    if rc != 0:
        return {"stashes": []}
    stashes = []
    for line in out.strip().splitlines():
        parts = line.split(None, 2)
        stashes.append({
            "ref":     parts[0] if parts else "",
            "message": parts[1] if len(parts) > 1 else "",
            "when":    parts[2] if len(parts) > 2 else "",
        })
    return {"stashes": stashes}


@router.post("/git/stash")
async def git_stash(req: StashRequest) -> dict:
    ws   = _ws(req.workspace)
    args = ["stash", "push"] + (["-m", req.message] if req.message else [])
    out, err, rc = _git(args, ws)
    if rc != 0:
        raise HTTPException(400, err.strip())
    return {"success": True, "output": out.strip()}


@router.post("/git/stash/pop")
async def git_stash_pop(workspace: str | None = None) -> dict:
    ws = _ws(workspace)
    out, err, rc = _git(["stash", "pop"], ws)
    if rc != 0:
        raise HTTPException(400, err.strip())
    return {"success": True, "output": out.strip()}


@router.post("/git/merge")
async def git_merge(req: MergeRequest) -> dict:
    ws  = _ws(req.workspace)
    args = ["merge", req.strategy, req.branch] if req.strategy else ["merge", req.branch]
    out, err, rc = _git(args, ws)
    if rc != 0:
        raise HTTPException(400, err.strip() or out.strip() or "merge failed")
    return {"success": True, "branch": req.branch, "output": out.strip()}


@router.get("/git/pr-summary")
async def git_pr_summary(base: str = "main", workspace: str | None = None) -> dict:
    """Generate a PR description from recent commits."""
    ws      = _ws(workspace)
    sep     = "|||"
    fmt     = f"%h{sep}%s{sep}%an"
    out, _, _ = _git(["log", f"{base}..HEAD", f"--pretty=format:{fmt}"], ws)
    commits  = []
    for line in out.strip().splitlines():
        parts = line.split(sep)
        if len(parts) >= 2:
            commits.append({"hash": parts[0], "message": parts[1], "author": parts[2] if len(parts) > 2 else ""})

    branch_out, _, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], ws)
    branch = branch_out.strip()

    # Heuristic PR description
    if commits:
        changes = "\n".join(f"- {c['message']}" for c in commits[:20])
        summary = f"## Changes\n\n{changes}\n\n## Branch\n`{branch}` → `{base}`\n\n## Commits\n{len(commits)} commit(s)"
    else:
        summary = f"No new commits vs `{base}`."

    return {"branch": branch, "base": base, "commits": commits, "summary": summary}
