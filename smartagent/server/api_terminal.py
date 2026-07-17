"""
Live Terminal — Feature 11.

Provides a WebSocket terminal that streams subprocess output to the browser.
For safety, only runs within the configured workspace directory.

Dev-server detection
--------------------
When a command looks like a dev-server launch (npm run dev, vite, flask run,
etc.) the terminal monitors stdout for port-announcement lines and immediately
registers the detected port with ``preview_manager.notify_dev_server_started``
so the preview shows up in the dashboard without waiting for the next
detection scan cycle.

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


# ── Dev-server detection ───────────────────────────────────────────────────────

# Patterns for commands that are likely to start a dev server
_DEV_SERVER_CMD = re.compile(
    r'\b(vite|webpack(?:[-\s]dev-server)?|next\s+dev|nuxt\s+dev|'
    r'npm\s+run\s+dev|yarn\s+dev|pnpm\s+(?:run\s+)?dev|'
    r'ng\s+serve|vue-cli-service\s+serve|'
    r'flask\s+run|uvicorn|gunicorn|'
    r'streamlit\s+run|storybook\s+dev|start-storybook|'
    r'react-scripts\s+start)\b',
    re.IGNORECASE,
)

# Ordered list of port-announcement patterns — tried in sequence.
# Most-specific first so a URL like http://127.0.0.1:5000 is not clobbered
# by a greedy keyword match that grabs "127" as the port number.
_PORT_PATTERNS: list[re.Pattern[str]] = [
    # Explicit URL: http(s)://host:PORT  (covers Flask, uvicorn, Vite, etc.)
    re.compile(
        r'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})',
        re.IGNORECASE,
    ),
    # "Local: http://localhost:PORT" style (Vite, CRA)
    re.compile(
        r'(?:local|network):\s+https?://\S+:(\d{2,5})',
        re.IGNORECASE,
    ),
    # "Listening on port PORT" / "running on port PORT"
    re.compile(
        r'(?:listening|running|serving|started|ready)\s+on\s+(?:port\s+)?(\d{2,5})',
        re.IGNORECASE,
    ),
    # "port PORT" fallback
    re.compile(r'\bport\s+(\d{2,5})\b', re.IGNORECASE),
    # Bare ":PORT" at end of a URL-like segment
    re.compile(r':(\d{4,5})\b'),
]

# Framework heuristics from command text
_CMD_FRAMEWORK_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bvite\b',              re.I), "vite"),
    (re.compile(r'\bnext\b',              re.I), "nextjs"),
    (re.compile(r'\bnuxt\b',              re.I), "vue"),
    (re.compile(r'\bng\s+serve\b',        re.I), "angular"),
    (re.compile(r'\bvue-cli\b',           re.I), "vue"),
    (re.compile(r'\bstorybook\b',         re.I), "storybook"),
    (re.compile(r'\bflask\b',             re.I), "flask"),
    (re.compile(r'\buvicorn\b',           re.I), "fastapi"),
    (re.compile(r'\bstreamlit\b',         re.I), "streamlit"),
    (re.compile(r'\breact-scripts\b',     re.I), "react"),
    (re.compile(r'\bwebpack\b',           re.I), "react"),
]


def _looks_like_dev_server(cmd: str) -> bool:
    """Return True if the command looks like it will start a dev server."""
    return bool(_DEV_SERVER_CMD.search(cmd))


def _framework_from_cmd(cmd: str) -> str:
    """Infer framework label from the command string."""
    for pattern, label in _CMD_FRAMEWORK_MAP:
        if pattern.search(cmd):
            return label
    return "unknown"


def _extract_port(line: str) -> int | None:
    """
    Extract a port number from a dev-server output line.

    Tries each pattern in ``_PORT_PATTERNS`` in order (most-specific first)
    and returns the first match whose port is in the valid dev-server range
    (1024–65535).  Returns ``None`` if no match is found.
    """
    for pattern in _PORT_PATTERNS:
        m = pattern.search(line)
        if m:
            try:
                port = int(m.group(1))
                if 1024 <= port <= 65535:
                    return port
            except (ValueError, IndexError):
                continue
    return None


def _register_dev_server(cmd: str, port: int) -> None:
    """Notify the preview manager that a dev server has started on *port*."""
    try:
        from smartagent.server.api_previews import preview_manager
        framework = _framework_from_cmd(cmd)
        preview_manager.notify_dev_server_started(port=port, framework=framework)
        logger.info("Dev-server hook: registered port %d (%s)", port, framework)
    except Exception as exc:
        logger.debug("Dev-server hook failed: %s", exc)


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
    is_dev_server = _looks_like_dev_server(req.command)
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

        # Dev-server hook: scan captured output for port announcements
        if is_dev_server:
            for line in output.splitlines():
                port = _extract_port(line)
                if port:
                    _register_dev_server(req.command, port)
                    break

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

    Dev-server detection: when the command looks like a dev-server launch,
    each output line is scanned for port-announcement patterns and the
    preview manager is notified immediately on the first match.
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

            is_dev_server = _looks_like_dev_server(cmd)
            port_registered = False
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
                    decoded = line.decode(errors="replace")
                    await ws.send_json({"type": "output", "data": decoded})

                    # Hook: scan for dev-server port announcement
                    if is_dev_server and not port_registered:
                        port = _extract_port(decoded)
                        if port:
                            _register_dev_server(cmd, port)
                            port_registered = True

                await current_proc.wait()
                await ws.send_json({"type": "exit", "data": "", "exit_code": current_proc.returncode})
                _history.append({"command": cmd, "workspace": ws_dir, "timestamp": _now_iso()})
            except Exception as exc:
                await ws.send_json({"type": "output", "data": f"Error: {exc}\n"})
    except (WebSocketDisconnect, Exception):
        if current_proc and current_proc.returncode is None:
            current_proc.kill()
