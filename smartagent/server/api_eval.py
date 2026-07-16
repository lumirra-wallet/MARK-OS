"""
Evaluation Framework — Feature 17.

Automatically scores every MARK run on key quality metrics.
Scores are stored in memory and queryable via REST.

Metrics
-------
- planning_score   : tasks planned vs tasks in goal complexity estimate
- tool_efficiency  : tool calls that returned useful results / total tool calls
- test_pass_rate   : tests passed / tests run (0-1)
- code_quality     : heuristic (files created + modified, no failures)
- execution_time_s : wall-clock seconds
- context_ratio    : tokens used / context window (lower is better)
- overall          : weighted average

Endpoints
---------
GET  /evaluations              — list all run evaluations
GET  /evaluations/trends       — aggregated metrics over time
GET  /evaluations/{run_id}     — single run evaluation
POST /evaluations              — submit evaluation data (called internally)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_evaluations: list[dict] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Scoring helpers ───────────────────────────────────────────────────────────

def score_run(
    run_id: str,
    goal: str,
    success: bool,
    elapsed_s: float,
    files_created: int,
    files_modified: int,
    tests_passed: int,
    tests_failed: int,
    tool_calls: int,
    tool_successes: int,
    workers_completed: int,
    workers_failed: int,
    tokens_used: int = 0,
    context_window: int = 8192,
) -> dict:
    total_tests = tests_passed + tests_failed
    test_pass_rate = (tests_passed / total_tests) if total_tests > 0 else (1.0 if success else 0.5)

    tool_efficiency = (tool_successes / tool_calls) if tool_calls > 0 else 0.8

    total_workers = workers_completed + workers_failed
    planning_score = (workers_completed / total_workers) if total_workers > 0 else (0.9 if success else 0.3)

    code_quality = min(1.0, (files_created + files_modified * 0.5) / max(1, 5))
    if not success:
        code_quality *= 0.5

    # Time score: 0-300s is green, beyond that decays
    time_score = max(0.0, 1.0 - math.log1p(elapsed_s / 300) * 0.3)

    context_ratio = min(1.0, tokens_used / max(1, context_window)) if tokens_used else 0.2

    weights = {
        "planning_score":    0.25,
        "tool_efficiency":   0.15,
        "test_pass_rate":    0.30,
        "code_quality":      0.15,
        "time_score":        0.10,
        "context_ratio":     0.05,
    }
    scores = {
        "planning_score":    round(planning_score, 3),
        "tool_efficiency":   round(tool_efficiency, 3),
        "test_pass_rate":    round(test_pass_rate, 3),
        "code_quality":      round(code_quality, 3),
        "time_score":        round(time_score, 3),
        "context_ratio":     round(1.0 - context_ratio, 3),  # higher is better
    }
    overall = sum(scores[k] * w for k, w in weights.items())

    entry = {
        "run_id":           run_id,
        "goal":             goal[:200],
        "success":          success,
        "timestamp":        _now_iso(),
        "elapsed_s":        round(elapsed_s, 1),
        "files_created":    files_created,
        "files_modified":   files_modified,
        "tests_passed":     tests_passed,
        "tests_failed":     tests_failed,
        "tool_calls":       tool_calls,
        "workers_completed":workers_completed,
        "workers_failed":   workers_failed,
        "scores":           scores,
        "overall":          round(overall, 3),
        "grade":            _grade(overall),
    }
    _evaluations.append(entry)
    if len(_evaluations) > 500:
        _evaluations.pop(0)
    return entry


def _grade(score: float) -> str:
    if score >= 0.9: return "A"
    if score >= 0.8: return "B"
    if score >= 0.7: return "C"
    if score >= 0.6: return "D"
    return "F"


# ── Endpoints ─────────────────────────────────────────────────────────────────

class EvalSubmit(BaseModel):
    run_id:            str   = ""
    goal:              str   = ""
    success:           bool  = False
    elapsed_s:         float = 0
    files_created:     int   = 0
    files_modified:    int   = 0
    tests_passed:      int   = 0
    tests_failed:      int   = 0
    tool_calls:        int   = 0
    tool_successes:    int   = 0
    workers_completed: int   = 0
    workers_failed:    int   = 0
    tokens_used:       int   = 0


@router.get("/evaluations")
async def list_evaluations(limit: int = 50) -> dict:
    items = list(reversed(_evaluations[-limit:]))
    return {"evaluations": items, "total": len(_evaluations)}


@router.get("/evaluations/trends")
async def evaluation_trends() -> dict:
    if not _evaluations:
        return {"trends": [], "averages": {}}
    metrics = ["planning_score", "tool_efficiency", "test_pass_rate", "code_quality", "overall"]
    avgs = {}
    for m in metrics:
        vals = [e["scores"].get(m, e.get("overall", 0)) for e in _evaluations]
        avgs[m] = round(sum(vals) / len(vals), 3) if vals else 0
    # Group by day
    trends = []
    for ev in _evaluations[-30:]:
        trends.append({
            "timestamp": ev["timestamp"],
            "overall":   ev["overall"],
            "success":   ev["success"],
        })
    return {"trends": trends, "averages": avgs, "total_runs": len(_evaluations)}


@router.get("/evaluations/{run_id}")
async def get_evaluation(run_id: str) -> dict:
    for ev in reversed(_evaluations):
        if ev["run_id"] == run_id:
            return ev
    raise HTTPException(404, f"Evaluation not found: {run_id}")


@router.post("/evaluations")
async def submit_evaluation(req: EvalSubmit) -> dict:
    entry = score_run(
        run_id=req.run_id, goal=req.goal, success=req.success,
        elapsed_s=req.elapsed_s, files_created=req.files_created,
        files_modified=req.files_modified, tests_passed=req.tests_passed,
        tests_failed=req.tests_failed, tool_calls=req.tool_calls,
        tool_successes=req.tool_successes,
        workers_completed=req.workers_completed, workers_failed=req.workers_failed,
        tokens_used=req.tokens_used,
    )
    return entry
