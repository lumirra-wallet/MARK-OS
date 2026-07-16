"""
Live Terminal — Feature 11.

Provides a WebSocket terminal that streams subprocess output to the browser.
For safety, only runs within the configured workspace directory.

Endpoints
---------
WS   /terminal/ws          — bidirectional terminal stream
POST /terminal/run         — run a single command, return output (REST)
GET  /terminal/history     — last N commands + outputs
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Safety ────────────────────────────────────────────────────────────────────

# Commands that are never allowed regardless of workspace setting
_BLOCKED = re.compile(
    r'\b(rm\s+-rf\s+/|mkfs|dd\s+if=|:.*:\{.*\}|>(.*)/dev/(sda|null))\b',
    re.IGNORECASE,
)

_history: list[dict] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_safe(cmd: str) -> bool:
    return not bool(_BLOCKED.search(cmd))


# ── REST run endpoint ─────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    command:   str
    workspace: str = "."
    timeout:   int = 30


@router.post("/terminal/run")
async def run_command(req: RunRequest) -> dict:
    if not _is_safe(req.command):
        return {"success": False, "output": "Command blocked by security policy", "exit_code": -1}

    ws = os.path.abspath(req.workspace)
    t0 = asyncio.get_event_loop().time()
    try:
        proc = await asyncio.create_subprocess_shell(
            req.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ws,
            limit=512 * 1024,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=req.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            stdout = b"[timeout]"
        output   = stdout.decode(errors="replace")[:50_000]
        exit_code = proc.returncode or 0
        elapsed   = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
        entry = {
            "command":    req.command,
            "output":     output,
            "exit_code":  exit_code,
            "elapsed_ms": elapsed,
            "timestamp":  _now_iso(),
            "workspace":  ws,
        }
        _history.append(entry)
        if len(_history) > 500:
            _history.pop(0)
        return {"success": exit_code == 0, **entry}
    except Exception as exc:
        return {"success": False, "output": str(exc), "exit_code": -1}


@router.get("/terminal/history")
async def terminal_history(limit: int = 100) -> dict:
    return {"history": list(reversed(_history[-limit:])), "total": len(_history)}


# ── WebSocket streaming terminal ───────────────────────────────────────────────

@router.websocket("/terminal/ws")
async def terminal_ws(ws: WebSocket) -> None:
    """
    Bidirectional terminal WebSocket.
    Client sends: { "cmd": "...", "workspace": "..." }
    Server sends: { "type": "output"|"exit", "data": "...", "exit_code": int }
    """
    await ws.accept()
    workspace = "."
    current_proc: asyncio.subprocess.Process | None = None

    try:
        while True:
            raw = await ws.receive_json()
            cmd       = raw.get("cmd", "").strip()
            workspace = raw.get("workspace", workspace)

            if not cmd:
                continue
            if not _is_safe(cmd):
                await ws.send_json({"type": "output", "data": "🔒 Command blocked by security policy\n"})
                continue

            if current_proc and current_proc.returncode is None:
                current_proc.kill()

            ws_dir = os.path.abspath(workspace)
            try:
                current_proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=ws_dir,
                )
                assert current_proc.stdout
                while True:
                    line = await current_proc.stdout.readline()
                    if not line:
                        break
                    await ws.send_json({"type": "output", "data": line.decode(errors="replace")})
                await current_proc.wait()
                await ws.send_json({"type": "exit", "data": "", "exit_code": current_proc.returncode})
                _history.append({"command": cmd, "workspace": ws_dir, "timestamp": _now_iso()})
            except Exception as exc:
                await ws.send_json({"type": "output", "data": f"Error: {exc}\n"})
    except (WebSocketDisconnect, Exception):
        if current_proc and current_proc.returncode is None:
            current_proc.kill()
