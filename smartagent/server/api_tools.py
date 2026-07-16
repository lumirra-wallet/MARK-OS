"""
Tool Calling Framework API — Feature 3, 18 (plugins), 19 (security).

Exposes the existing ToolRegistry + ToolEngine over REST so the dashboard
and any external client can list, inspect, enable/disable, and invoke tools.

Endpoints
---------
GET  /tools                    — list all registered tools
GET  /tools/health             — registry health check + stats
GET  /tools/{tool_id}          — single tool detail
POST /tools/{tool_id}/execute  — run a tool with params
POST /tools/{tool_id}/enable   — enable a disabled tool
POST /tools/{tool_id}/disable  — disable an enabled tool

GET  /plugins                  — list discovered plugin packages
POST /plugins/{name}/install   — (future) install a plugin
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Shared registry instance (lazy-loaded once) ───────────────────────────────

_registry = None
_engine   = None


def _get_registry():
    global _registry, _engine
    if _registry is not None:
        return _registry, _engine
    try:
        from smartagent.tools.tool_registry import ToolRegistry
        from smartagent.tools.tool_engine   import ToolEngine
        from smartagent.tools.loader        import load_all_tools
        _registry = ToolRegistry()
        load_all_tools(_registry)
        _engine = ToolEngine(_registry)
    except Exception as exc:
        logger.warning("Could not load tool registry: %s", exc)
        _registry = _FallbackRegistry()
        _engine   = None
    return _registry, _engine


class _FallbackRegistry:
    """Used when the real registry cannot be imported."""
    def list(self, **_): return []
    def find(self, _id): return None
    def enable(self, _): return False
    def disable(self, _): return False
    def health_check(self): return {"healthy": False, "tools": {}}
    def statistics(self): return {"total": 0, "enabled": 0, "disabled": 0, "execution_counts": {}}


# ── Audit log (Feature 19 — Security Layer) ───────────────────────────────────

_audit_log: list[dict] = []   # in-memory; write to disk in prod

def _audit(action: str, tool_id: str, params: dict, result: Any, elapsed_ms: float, allowed: bool) -> None:
    entry = {
        "ts":         _now_iso(),
        "action":     action,
        "tool_id":    tool_id,
        "params":     params,
        "result_ok":  allowed and bool(result),
        "elapsed_ms": round(elapsed_ms, 1),
        "allowed":    allowed,
    }
    _audit_log.append(entry)
    if len(_audit_log) > 2000:
        _audit_log.pop(0)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Security: workspace boundary check ───────────────────────────────────────

def _validate_path_param(path: str | None, workspace: str) -> bool:
    """Return True if path stays inside workspace. Feature 19."""
    if not path:
        return True
    try:
        resolved = Path(path).resolve()
        base     = Path(workspace).resolve()
        return resolved.is_relative_to(base)
    except Exception:
        return False


# ── Models ────────────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    params:    dict[str, Any] = {}
    workspace: str            = "."


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_tools(enabled_only: bool = True) -> dict:
    registry, _ = _get_registry()
    tools = registry.list(enabled_only=enabled_only)
    return {
        "tools": [_tool_dict(t) for t in tools],
        "count": len(tools),
        "stats": registry.statistics(),
    }


@router.get("/tools/health")
async def tools_health() -> dict:
    registry, _ = _get_registry()
    return registry.health_check()


@router.get("/tools/audit")
async def tools_audit(limit: int = 100) -> dict:
    """Feature 19 — Security audit log."""
    return {"entries": _audit_log[-limit:], "total": len(_audit_log)}


@router.get("/tools/{tool_id}")
async def get_tool(tool_id: str) -> dict:
    registry, _ = _get_registry()
    tool = registry.find(tool_id)
    if tool is None:
        raise HTTPException(404, f"Tool not found: {tool_id}")
    return _tool_dict(tool)


@router.post("/tools/{tool_id}/execute")
async def execute_tool(tool_id: str, req: ExecuteRequest) -> dict:
    """Run a tool. Applies security validation (Feature 19)."""
    registry, engine = _get_registry()
    tool = registry.find(tool_id)
    if tool is None:
        raise HTTPException(404, f"Tool not found: {tool_id}")

    # Security: validate any path param stays in workspace
    path_val = req.params.get("path") or req.params.get("file") or req.params.get("directory")
    if path_val and not _validate_path_param(path_val, req.workspace):
        _audit("execute", tool_id, req.params, None, 0, False)
        raise HTTPException(403, "Path escapes workspace boundary (Security Layer)")

    t0 = time.monotonic()
    try:
        if engine is not None:
            from smartagent.tools.base_tool import ToolContext
            ctx    = ToolContext(settings=None, event_bus=None, workspace=req.workspace)
            result = tool.execute(req.params, ctx)
            outcome = {"success": result.ok, "output": str(result.value or result.error or "")}
        else:
            # Fallback: call legacy run() if available
            outcome = {"success": False, "output": "Tool engine unavailable"}
        elapsed = (time.monotonic() - t0) * 1000
        registry.record_execution(tool_id)
        _audit("execute", tool_id, req.params, outcome, elapsed, True)
        return {**outcome, "tool_id": tool_id, "elapsed_ms": round(elapsed, 1)}
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        _audit("execute", tool_id, req.params, None, elapsed, True)
        raise HTTPException(500, str(exc))


@router.post("/tools/{tool_id}/enable")
async def enable_tool(tool_id: str) -> dict:
    registry, _ = _get_registry()
    ok = registry.enable(tool_id)
    if not ok:
        raise HTTPException(404, f"Tool not found: {tool_id}")
    return {"success": True, "tool_id": tool_id, "status": "enabled"}


@router.post("/tools/{tool_id}/disable")
async def disable_tool(tool_id: str) -> dict:
    registry, _ = _get_registry()
    ok = registry.disable(tool_id)
    if not ok:
        raise HTTPException(404, f"Tool not found: {tool_id}")
    return {"success": True, "tool_id": tool_id, "status": "disabled"}


# ── Plugins (Feature 18) ──────────────────────────────────────────────────────

@router.get("/plugins")
async def list_plugins(workspace: str = ".") -> dict:
    """Discover plugin packages in <workspace>/plugins/."""
    plugins_dir = Path(workspace) / "plugins"
    plugins = []
    if plugins_dir.is_dir():
        for entry in sorted(plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    plugins.append({
                        "name":        entry.name,
                        "version":     manifest.get("version", "0.0.1"),
                        "description": manifest.get("description", ""),
                        "tools":       manifest.get("tools", []),
                        "permissions": manifest.get("permissions", []),
                        "has_ui":      manifest.get("ui_panel", False),
                        "status":      "installed",
                    })
                except Exception:
                    plugins.append({"name": entry.name, "status": "invalid_manifest"})
    return {"plugins": plugins, "plugins_dir": str(plugins_dir), "count": len(plugins)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tool_dict(tool) -> dict:
    try:
        meta = tool.metadata()
        return {
            "id":          meta.id,
            "name":        meta.name,
            "description": meta.description,
            "version":     meta.version,
            "author":      meta.author,
            "category":    meta.category.value if hasattr(meta.category, "value") else str(meta.category),
            "permissions": [p.value if hasattr(p, "value") else str(p) for p in meta.permissions],
            "status":      "enabled",
        }
    except Exception:
        return {
            "id":          getattr(tool, "id", str(tool)),
            "name":        getattr(tool, "name", "unknown"),
            "description": getattr(tool, "description", ""),
            "version":     getattr(tool, "version", "0.0.1"),
            "category":    "unknown",
            "status":      "enabled",
        }
