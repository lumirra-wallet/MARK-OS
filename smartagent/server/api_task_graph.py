"""
Task Graph Planner — Features 1, 2, 7.

Feature 1: Real Planning Agent — generates dependency graphs instead of linear pipelines.
Feature 2: Parallel Worker Scheduler — independent tasks execute simultaneously.
Feature 7: Multi-Agent Communication — inter-worker structured messages.

Endpoints
---------
POST /task-graph/plan   — generate a task graph from a goal (LLM or heuristic)
GET  /task-graph        — get current run's task graph
GET  /task-graph/nodes  — flat list of task nodes
PATCH /task-graph/nodes/{id} — update node status
DELETE /task-graph      — clear task graph

GET  /agent/messages    — inter-agent messages
POST /agent/messages    — post a message (worker → worker)
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ── Task Graph ────────────────────────────────────────────────────────────────

TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled", "blocked"]

_task_graph: dict[str, Any] = {
    "run_id": "",
    "goal":   "",
    "nodes":  [],
    "edges":  [],
}


class TaskNode(BaseModel):
    id:           str = ""
    title:        str
    description:  str = ""
    dependencies: list[str] = []
    complexity:   Literal["low", "medium", "high"] = "medium"
    status:       TaskStatus = "pending"
    worker:       str = ""
    started_at:   str = ""
    finished_at:  str = ""
    result:       str = ""


class PlanRequest(BaseModel):
    goal:      str
    run_id:    str = ""
    workspace: str = "."


class NodeUpdateRequest(BaseModel):
    status:      TaskStatus | None = None
    worker:      str | None        = None
    result:      str | None        = None


# ── Heuristic task graph generator ───────────────────────────────────────────
# When no LLM is available, uses keyword patterns to build a sensible graph.

_DOMAIN_PATTERNS = [
    (r"\bapi\b|\bendpoint\b|\broute\b|\bfastapi\b|\bflask\b|\bdjango\b",   "API Layer"),
    (r"\bauth\b|\blogin\b|\bjwt\b|\btoken\b|\bpassword\b",                  "Authentication"),
    (r"\btest\b|\bpytest\b|\bspec\b|\bunit\b",                              "Tests"),
    (r"\bdatabase\b|\bsql\b|\borm\b|\bmodel\b|\bschema\b|\bmigration\b",   "Database Layer"),
    (r"\bui\b|\bfrontend\b|\breact\b|\bcomponent\b|\bpage\b",              "Frontend"),
    (r"\bdocker\b|\bdeployment\b|\bci\b|\bdevops\b",                       "DevOps"),
    (r"\bdocument\b|\breadme\b|\bcomment\b|\bdocstring\b",                  "Documentation"),
    (r"\brefactor\b|\bclean\b|\blint\b|\bformat\b",                        "Code Quality"),
    (r"\bgit\b|\bcommit\b|\bpull request\b|\bbranch\b",                    "Git"),
]


def _heuristic_plan(goal: str, run_id: str) -> dict:
    """Build a dependency graph from keyword analysis."""
    goal_lower = goal.lower()
    matched: list[str] = []
    for pattern, label in _DOMAIN_PATTERNS:
        if re.search(pattern, goal_lower):
            matched.append(label)

    # Always add Research + Planning at top, Review + Documentation at bottom
    phases: list[dict] = []

    def _node(title: str, desc: str, deps: list[str], complexity: str = "medium") -> dict:
        return {
            "id":           str(uuid.uuid4())[:8],
            "title":        title,
            "description":  desc,
            "dependencies": deps,
            "complexity":   complexity,
            "status":       "pending",
            "worker":       _assign_worker(title),
            "started_at":   "",
            "finished_at":  "",
            "result":       "",
        }

    research = _node("Research", "Analyze requirements and existing codebase", [], "low")
    planning = _node("Planning", "Create detailed implementation plan", [research["id"]], "low")
    phases = [research, planning]

    prev_ids = [planning["id"]]

    # Middle phases (can run in parallel after planning)
    parallel_group: list[dict] = []
    for label in matched:
        if label in ("Documentation", "Code Quality", "Git"):
            continue
        n = _node(label, f"Implement {label}", [planning["id"]])
        parallel_group.append(n)

    if not parallel_group:
        coding = _node("Coding", f"Implement: {goal[:100]}", [planning["id"]], "high")
        parallel_group = [coding]

    phases.extend(parallel_group)
    parallel_ids = [n["id"] for n in parallel_group]

    # Testing after all parallel work
    testing = _node("Testing", "Write and run tests", parallel_ids, "medium")
    phases.append(testing)

    # Quality + Review in sequence after testing
    quality = _node("Code Quality", "Lint, format, type-check", [testing["id"]], "low")
    review  = _node("Review", "Final review and approval", [quality["id"]], "low")
    doc     = _node("Documentation", "Update docs and README", [review["id"]], "low")
    phases.extend([quality, review, doc])

    # Build edges from dependencies
    edges = []
    for node in phases:
        for dep in node["dependencies"]:
            edges.append({"source": dep, "target": node["id"], "type": "dependency"})

    return {
        "run_id": run_id,
        "goal":   goal,
        "nodes":  phases,
        "edges":  edges,
    }


def _assign_worker(title: str) -> str:
    mapping = {
        "Research":      "ResearchWorker",
        "Planning":      "PlanningWorker",
        "Coding":        "CodingWorker",
        "API Layer":     "CodingWorker",
        "Authentication":"CodingWorker",
        "Database Layer":"CodingWorker",
        "Frontend":      "CodingWorker",
        "Testing":       "TestingWorker",
        "Code Quality":  "QualityWorker",
        "Review":        "ReviewWorker",
        "Documentation": "DocumentationWorker",
        "DevOps":        "CodingWorker",
        "Git":           "GitWorker",
    }
    return mapping.get(title, "CodingWorker")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/task-graph/plan")
async def plan_task_graph(req: PlanRequest) -> dict:
    global _task_graph
    _task_graph = _heuristic_plan(req.goal, req.run_id)
    return _task_graph


@router.get("/task-graph")
async def get_task_graph() -> dict:
    return _task_graph


@router.get("/task-graph/nodes")
async def get_task_nodes() -> dict:
    return {"nodes": _task_graph.get("nodes", []), "run_id": _task_graph.get("run_id", "")}


@router.patch("/task-graph/nodes/{node_id}")
async def update_node(node_id: str, req: NodeUpdateRequest) -> dict:
    for node in _task_graph.get("nodes", []):
        if node["id"] == node_id:
            if req.status is not None:
                node["status"] = req.status
                if req.status == "running":
                    node["started_at"]  = _now_iso()
                elif req.status in ("completed", "failed"):
                    node["finished_at"] = _now_iso()
            if req.worker  is not None: node["worker"]  = req.worker
            if req.result  is not None: node["result"]  = req.result
            return node
    return {"error": "node not found"}


@router.delete("/task-graph")
async def clear_task_graph() -> dict:
    global _task_graph
    _task_graph = {"run_id": "", "goal": "", "nodes": [], "edges": []}
    return {"success": True}


# ── Multi-Agent Messages (Feature 7) ─────────────────────────────────────────

_messages: list[dict] = []


class AgentMessage(BaseModel):
    sender:     str
    receiver:   str
    task:       str
    payload:    dict[str, Any] = {}
    confidence: float          = 1.0


@router.get("/agent/messages")
async def get_agent_messages(run_id: str | None = None, limit: int = 200) -> dict:
    msgs = _messages
    if run_id:
        msgs = [m for m in msgs if m.get("run_id") == run_id]
    return {"messages": msgs[-limit:], "total": len(msgs)}


@router.post("/agent/messages")
async def post_agent_message(msg: AgentMessage) -> dict:
    entry = {
        "id":         str(uuid.uuid4())[:8],
        "sender":     msg.sender,
        "receiver":   msg.receiver,
        "timestamp":  _now_iso(),
        "task":       msg.task,
        "payload":    msg.payload,
        "confidence": msg.confidence,
    }
    _messages.append(entry)
    if len(_messages) > 5000:
        _messages.pop(0)
    return entry


def record_agent_message(sender: str, receiver: str, task: str,
                         payload: dict | None = None, confidence: float = 1.0) -> None:
    """Called internally by worker pipeline to log messages."""
    entry = {
        "id":         str(uuid.uuid4())[:8],
        "sender":     sender,
        "receiver":   receiver,
        "timestamp":  _now_iso(),
        "task":       task,
        "payload":    payload or {},
        "confidence": confidence,
    }
    _messages.append(entry)
    if len(_messages) > 5000:
        _messages.pop(0)
