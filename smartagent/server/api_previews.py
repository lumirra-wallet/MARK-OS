"""
Preview Detection & Registry — Task 19.

Auto-detects running dev-server ports, classifies the framework from HTTP
response heuristics, and exposes the registry via REST endpoints.  Every
lifecycle change is broadcast as a WebSocket event so the dashboard can
hot-reload embedded iframes without polling.

Preview records persist to ``.mark_previews.json`` following the same
pattern as ``.mark_jobs.json``.

Security model
--------------
All preview URLs must target loopback addresses (127.0.0.1 / localhost) on
``http`` only.  The proxy endpoint only forwards to validated local targets,
preventing Server-Side Request Forgery (SSRF).

Endpoints
---------
GET    /previews               — list all registered previews
GET    /previews/{id}          — single preview record
POST   /previews               — manually register a preview
DELETE /previews/{id}          — unregister / close a preview
POST   /previews/refresh       — trigger a full auto-detection scan
POST   /previews/{id}/refresh  — re-probe a single preview
POST   /previews/{id}/inspect  — self-inspect via Playwright (screenshot, console
                                  errors, accessibility) — see smartagent/preview/
GET    /previews/proxy/{id}/{path:path}  — proxy request to preview (iframe)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from smartagent.server.events import ServerEvents
from smartagent.preview.browser_agent import browser_agent

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Preview persistence file
# ---------------------------------------------------------------------------

_PREVIEWS_FILE = Path(".mark_previews.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Security: loopback-only URL validation
# ---------------------------------------------------------------------------

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_VALID_PORT_RANGE = range(1, 65536)


def _validate_local_url(url: str) -> str:
    """
    Validate that *url* targets a local loopback address over http.

    Returns the normalised ``http://127.0.0.1:<port>`` form, or raises
    ``ValueError`` with a user-friendly message.

    Rules
    -----
    - Scheme must be ``http`` (no https — local servers rarely have TLS).
    - Hostname must be ``127.0.0.1``, ``localhost``, or ``::1``.
    - Port must be in 1–65535.
    - No credentials, no path beyond what the caller supplied.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"Invalid URL: {exc}") from exc

    if parsed.scheme != "http":
        raise ValueError(
            f"Preview URL scheme must be 'http', got '{parsed.scheme}'. "
            "Dev-server previews only support plain HTTP on loopback."
        )
    hostname = parsed.hostname or ""
    if hostname not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"Preview URL host must be a loopback address "
            f"(127.0.0.1 / localhost), got '{hostname}'."
        )
    port = parsed.port
    if port is None or port not in _VALID_PORT_RANGE:
        raise ValueError(
            f"Preview URL must include a valid port (1-65535), got '{port}'."
        )
    # Return canonical form regardless of what the caller passed
    return f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# Candidate ports to probe during auto-detection
# ---------------------------------------------------------------------------

_CANDIDATE_PORTS: list[int] = [
    # Vite default
    5173, 5174, 5175,
    # React CRA / generic dev servers
    3000, 3001, 3002,
    # Next.js
    3000,
    # Angular
    4200, 4201,
    # Vue CLI / generic webpack
    8080, 8081,
    # Django
    8000, 8001,
    # Flask / FastAPI
    5000, 5001,
    # Storybook
    6006,
    # Streamlit
    8501,
    # Flutter web
    7357,
    # Electron devtools / Parcel
    1234,
    # Generic
    4000, 7000, 9000,
]
# Deduplicate while preserving order
_CANDIDATE_PORTS = list(dict.fromkeys(_CANDIDATE_PORTS))


# ---------------------------------------------------------------------------
# Framework detection heuristics
# ---------------------------------------------------------------------------

class FrameworkHeuristics:
    """
    Classify the framework running on a port from HTTP response signals.

    Order of rules matters — more specific rules first.
    """

    @staticmethod
    def classify(
        url: str,
        status: int,
        headers: dict[str, str],
        body: str,
    ) -> str:
        """Return a framework label like 'vite', 'nextjs', 'storybook', etc."""
        h = {k.lower(): v.lower() for k, v in headers.items()}
        b = body.lower()

        # ── Next.js ───────────────────────────────────────────────────────
        if "x-powered-by" in h and "next.js" in h["x-powered-by"]:
            return "nextjs"
        if "__next_data__" in b or "_next/static" in b:
            return "nextjs"

        # ── Storybook ────────────────────────────────────────────────────
        if "storybook" in b and ("stories" in b or "addons" in b):
            return "storybook"

        # ── Vite ─────────────────────────────────────────────────────────
        if "/@vite/client" in body or "/@vite/env" in body:
            return "vite"
        if "vite" in h.get("server", "") or "vite" in h.get("x-powered-by", ""):
            return "vite"
        if 'type="module"' in b and ("vite" in b or "/@react-refresh" in body):
            return "vite"

        # ── FastAPI / OpenAPI docs ────────────────────────────────────────
        if status == 200 and (
            "swagger-ui" in b
            or "redoc" in b
            or '"openapi"' in b
        ):
            return "fastapi"

        # ── Flask ────────────────────────────────────────────────────────
        if "werkzeug" in h.get("server", ""):
            return "flask"

        # ── Django ───────────────────────────────────────────────────────
        if "django" in b or "csrfmiddlewaretoken" in b:
            return "django"

        # ── Streamlit ────────────────────────────────────────────────────
        if "streamlit" in b or "streamlit" in h.get("server", ""):
            return "streamlit"

        # ── Angular ──────────────────────────────────────────────────────
        if "ng-version" in b or "angular" in b:
            return "angular"

        # ── Vue ──────────────────────────────────────────────────────────
        if "vue" in b and ("<div id=" in b or "__vue" in b):
            return "vue"

        # ── Flutter Web ────────────────────────────────────────────────────
        if "flutter.js" in b or "flutter_service_worker" in b or "flt-glass-pane" in b:
            return "flutter"

        # ── Electron (remote-debugging / devtools endpoint) ────────────────
        if "electron" in h.get("user-agent", "") or "electron" in b:
            return "electron"

        # ── React Native Web ────────────────────────────────────────────────
        if "react-native-web" in b or "data-rnw" in b:
            return "react-native-web"

        # ── React (CRA / generic) ─────────────────────────────────────────
        if "react-dom" in b or "react.development" in b or "react.production" in b:
            return "react"

        # ── Generic ──────────────────────────────────────────────────────
        if status == 200:
            return "unknown"
        return "unknown"

    @staticmethod
    def title_for(framework: str, port: int) -> str:
        _names = {
            "vite":      "Vite Dev Server",
            "nextjs":    "Next.js",
            "react":     "React App",
            "angular":   "Angular App",
            "vue":       "Vue App",
            "storybook": "Storybook",
            "fastapi":   "FastAPI Docs",
            "flask":     "Flask App",
            "django":    "Django App",
            "streamlit": "Streamlit App",
            "flutter":   "Flutter Web App",
            "electron":  "Electron App",
            "react-native-web": "React Native Web App",
            "unknown":   "Dev Server",
        }
        name = _names.get(framework, "Dev Server")
        return f"{name} :{port}"


# ---------------------------------------------------------------------------
# Preview Registry
# ---------------------------------------------------------------------------

class PreviewRecord:
    """Plain-dict wrapper with typed helpers."""

    @staticmethod
    def make(
        port: int,
        url: str,
        framework: str = "unknown",
        title: str = "",
        status: str = "active",
        preview_id: str = "",
        proxy_url: str = "",
        registered_by: str = "auto",
    ) -> dict[str, Any]:
        pid = preview_id or str(uuid.uuid4())
        return {
            "id":            pid,
            "port":          port,
            "url":           url,
            "proxy_url":     proxy_url or f"/previews/proxy/{pid}",
            "framework":     framework,
            "title":         title or FrameworkHeuristics.title_for(framework, port),
            "status":        status,       # active | unreachable | closed
            "registered_by": registered_by,  # "auto" | "manual"
            "registered_at": _now_iso(),
            "updated_at":    _now_iso(),
        }


class PreviewManager:
    """
    Singleton that owns the in-memory preview registry and the detection loop.

    Detection loop
    ~~~~~~~~~~~~~~
    ``start_detection(loop, connection_manager)`` launches a background task
    that repeatedly probes candidate ports, registers newly-found previews,
    and marks unreachable ones as such.  The interval is configurable via the
    ``PREVIEW_SCAN_INTERVAL`` env var (default: 15 s).

    Thread/async safety
    ~~~~~~~~~~~~~~~~~~~
    All mutations go through ``asyncio.run_coroutine_threadsafe`` when called
    from sync code, or directly via ``await`` in async contexts.
    """

    def __init__(self) -> None:
        self._previews: dict[str, dict] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager: Any = None
        self._detect_task: asyncio.Task | None = None
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        if _PREVIEWS_FILE.exists():
            try:
                raw = json.loads(_PREVIEWS_FILE.read_text())
                # Discard previews stored in /tmp workspaces (test artefacts)
                self._previews = {
                    k: v for k, v in raw.items()
                    if not str(v.get("url", "")).startswith("http://localhost:0")
                }
            except Exception:
                self._previews = {}

    def _save(self) -> None:
        try:
            _PREVIEWS_FILE.write_text(json.dumps(self._previews, indent=2))
        except Exception as exc:
            logger.warning("Could not save previews: %s", exc)

    # ── Internal broadcast helper ─────────────────────────────────────────────

    def _broadcast_sync(self, event_name: str, payload: dict) -> None:
        """Broadcast a WebSocket event from sync or async context."""
        if self._loop is None or self._manager is None:
            return
        msg = {
            "type":    "event",
            "name":    event_name,
            "payload": payload,
            "timestamp": _now_iso(),
        }
        try:
            asyncio.run_coroutine_threadsafe(
                self._manager.broadcast(msg),
                self._loop,
            )
        except RuntimeError:
            pass  # loop closed (test teardown)

    async def _broadcast_async(self, event_name: str, payload: dict) -> None:
        """Broadcast a WebSocket event from an async context."""
        if self._manager is None:
            return
        msg = {
            "type":    "event",
            "name":    event_name,
            "payload": payload,
            "timestamp": _now_iso(),
        }
        await self._manager.broadcast(msg)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def all_previews(self) -> list[dict]:
        return sorted(
            self._previews.values(),
            key=lambda x: x.get("registered_at", ""),
            reverse=True,
        )

    def get(self, preview_id: str) -> dict | None:
        return self._previews.get(preview_id)

    def register(self, record: dict) -> dict:
        """Add or update a preview record; broadcast PreviewRegistered."""
        pid = record["id"]
        is_new = pid not in self._previews
        self._previews[pid] = record
        self._save()
        event_name = ServerEvents.PREVIEW_REGISTERED if is_new else ServerEvents.PREVIEW_UPDATED
        self._broadcast_sync(event_name, record)
        return record

    def update(self, preview_id: str, **kwargs: Any) -> dict | None:
        """Patch a preview record fields; broadcast PreviewUpdated."""
        rec = self._previews.get(preview_id)
        if rec is None:
            return None
        rec.update(kwargs)
        rec["updated_at"] = _now_iso()
        self._save()
        self._broadcast_sync(ServerEvents.PREVIEW_UPDATED, rec)
        return rec

    def unregister(self, preview_id: str) -> dict | None:
        """Remove a preview; broadcast PreviewClosed."""
        rec = self._previews.pop(preview_id, None)
        if rec is None:
            return None
        rec["status"] = "closed"
        rec["updated_at"] = _now_iso()
        self._save()
        self._broadcast_sync(ServerEvents.PREVIEW_CLOSED, rec)
        return rec

    # ── Port probe ────────────────────────────────────────────────────────────

    @staticmethod
    def _port_open(port: int, timeout: float = 0.3) -> bool:
        """Return True if *port* is accepting connections on localhost."""
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    async def _probe_port(port: int, timeout: float = 3.0) -> dict | None:
        """
        HTTP GET localhost:{port}/ and extract status + framework.
        Returns a partial preview record dict or None if unreachable.
        """
        url = f"http://127.0.0.1:{port}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=1.0, read=timeout, write=1.0, pool=1.0),
                follow_redirects=True,
                verify=False,
            ) as client:
                resp = await client.get(url + "/")
                body = resp.text[:8192]
                headers = dict(resp.headers)
                framework = FrameworkHeuristics.classify(
                    url, resp.status_code, headers, body
                )
                return {
                    "port":      port,
                    "url":       url,
                    "framework": framework,
                    "status":    "active",
                    "http_status": resp.status_code,
                }
        except Exception:
            return None

    # ── Detection loop ────────────────────────────────────────────────────────

    def start_detection(
        self,
        loop: asyncio.AbstractEventLoop,
        connection_manager: Any,
        interval: float = 15.0,
    ) -> None:
        """
        Launch the background port-scan task.  Safe to call multiple times —
        an existing task is cancelled first.
        """
        self._loop    = loop
        self._manager = connection_manager
        if self._detect_task and not self._detect_task.done():
            self._detect_task.cancel()
        self._detect_task = loop.create_task(
            self._detection_loop(interval),
            name="preview-detection",
        )
        logger.info("Preview detection loop started (interval=%ss)", interval)

    def stop_detection(self) -> None:
        if self._detect_task and not self._detect_task.done():
            self._detect_task.cancel()
            self._detect_task = None

    async def _detection_loop(self, interval: float) -> None:
        """Scan candidate ports repeatedly and sync the registry."""
        while True:
            try:
                await self.scan_ports()
            except Exception as exc:
                logger.debug("Preview scan error: %s", exc)
            await asyncio.sleep(interval)

    async def scan_ports(self) -> list[dict]:
        """
        Probe all candidate ports in parallel.  New ports are registered;
        previously-known ports that became unreachable are updated to
        'unreachable'; ports that come back online are updated to 'active'.

        Returns the list of previews whose status changed.
        """
        # Exclude only this server's own port at runtime — do not hard-code
        # any other ports so legitimate dev servers (e.g. Vue on 8080) are
        # not silently skipped.
        own_port = int(os.environ.get("PORT", 8000))
        skip: set[int] = {own_port}

        # ── Quick TCP check first (cheap) ────────────────────────────────────
        open_ports = [
            p for p in _CANDIDATE_PORTS
            if p not in skip and self._port_open(p)
        ]

        # ── HTTP probe open ports in parallel ─────────────────────────────────
        tasks = {port: asyncio.create_task(self._probe_port(port)) for port in open_ports}
        results: dict[int, dict | None] = {}
        if tasks:
            done = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for port, res in zip(tasks.keys(), done):
                results[port] = res if isinstance(res, dict) else None

        changed: list[dict] = []

        # ── Reconcile with registry ───────────────────────────────────────────
        # Port → existing preview id
        port_to_id = {v["port"]: k for k, v in self._previews.items()}

        # New or re-activated
        for port, probe in results.items():
            if probe is None:
                continue
            if port in port_to_id:
                pid = port_to_id[port]
                rec = self._previews[pid]
                if rec["status"] != "active":
                    rec["status"]     = "active"
                    rec["updated_at"] = _now_iso()
                    self._save()
                    await self._broadcast_async(ServerEvents.PREVIEW_UPDATED, rec)
                    changed.append(rec)
            else:
                rec = PreviewRecord.make(
                    port=port,
                    url=probe["url"],
                    framework=probe["framework"],
                    status="active",
                )
                self._previews[rec["id"]] = rec
                self._save()
                await self._broadcast_async(ServerEvents.PREVIEW_REGISTERED, rec)
                changed.append(rec)

        # Mark previously-active previews as unreachable if port is now closed
        for port, pid in list(port_to_id.items()):
            if port in skip:
                continue
            rec = self._previews.get(pid)
            if rec is None:
                continue
            if rec["status"] == "active" and port not in results:
                rec["status"]     = "unreachable"
                rec["updated_at"] = _now_iso()
                self._save()
                await self._broadcast_async(ServerEvents.PREVIEW_UPDATED, rec)
                changed.append(rec)

        return changed

    # ── Dev-server hook ────────────────────────────────────────────────────────

    def notify_dev_server_started(
        self,
        port: int,
        framework: str = "unknown",
        title: str = "",
    ) -> dict:
        """
        Called by terminal / worker hooks when a dev-server subprocess is
        detected.  Immediately registers the preview without waiting for the
        next detection cycle.
        """
        # Check if we already know about this port
        port_to_id = {v["port"]: k for k, v in self._previews.items()}
        if port in port_to_id:
            rec = self.update(port_to_id[port], status="active", framework=framework)
            return rec  # type: ignore[return-value]
        url = f"http://127.0.0.1:{port}"
        rec = PreviewRecord.make(
            port=port,
            url=url,
            framework=framework,
            title=title or FrameworkHeuristics.title_for(framework, port),
            registered_by="auto",
        )
        return self.register(rec)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

preview_manager = PreviewManager()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegisterPreviewRequest(BaseModel):
    port: int
    url: str
    framework: str = "unknown"
    title: str = ""


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@router.get("/previews")
async def list_previews() -> dict:
    """List all registered previews."""
    items = preview_manager.all_previews()
    return {"previews": items, "count": len(items)}


@router.get("/previews/scan")
async def trigger_scan() -> dict:
    """Alias for POST /previews/refresh (GET-friendly for quick testing)."""
    changed = await preview_manager.scan_ports()
    return {
        "success":    True,
        "changed":    len(changed),
        "previews":   preview_manager.all_previews(),
    }


@router.post("/previews/refresh")
async def refresh_previews() -> dict:
    """Trigger an immediate auto-detection scan of all candidate ports."""
    changed = await preview_manager.scan_ports()
    return {
        "success":  True,
        "changed":  len(changed),
        "previews": preview_manager.all_previews(),
    }


@router.get("/previews/{preview_id}")
async def get_preview(preview_id: str) -> dict:
    rec = preview_manager.get(preview_id)
    if rec is None:
        raise HTTPException(404, f"Preview not found: {preview_id}")
    return rec


@router.post("/previews", status_code=201)
async def register_preview(req: RegisterPreviewRequest) -> dict:
    """
    Manually register a preview (e.g. from a terminal hook).

    The ``url`` field must target a loopback address (127.0.0.1 / localhost)
    over http — arbitrary remote URLs are rejected to prevent SSRF.
    """
    try:
        canonical_url = _validate_local_url(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rec = PreviewRecord.make(
        port=req.port,
        url=canonical_url,
        framework=req.framework,
        title=req.title,
        registered_by="manual",
    )
    preview_manager.register(rec)
    return {"success": True, "preview": rec}


@router.delete("/previews/{preview_id}")
async def unregister_preview(preview_id: str) -> dict:
    rec = preview_manager.unregister(preview_id)
    if rec is None:
        raise HTTPException(404, f"Preview not found: {preview_id}")
    return {"success": True, "closed": preview_id}


class InspectPreviewRequest(BaseModel):
    actions:              list[dict[str, Any]] | None = None
    check_accessibility:  bool = True
    check_responsiveness: bool = False


def _screenshot_url(path: str | None) -> str | None:
    """Map a local screenshot file path to the URL app.py serves it under."""
    if not path:
        return None
    return f"/screenshots/{Path(path).name}"


@router.post("/previews/{preview_id}/inspect")
async def inspect_preview(preview_id: str, req: InspectPreviewRequest | None = None) -> dict:
    """
    Self-inspect a running preview via Playwright: navigate, optionally
    click/fill, screenshot, and collect console errors + accessibility
    findings. Runs the (blocking) Playwright call in a worker thread so it
    doesn't block the event loop.
    """
    rec = preview_manager.get(preview_id)
    if rec is None:
        raise HTTPException(404, f"Preview not found: {preview_id}")
    if not browser_agent.available:
        raise HTTPException(
            503,
            "Browser automation is unavailable — Playwright or a Chromium "
            "executable was not found on this machine.",
        )

    req = req or InspectPreviewRequest()
    report = await asyncio.to_thread(
        browser_agent.inspect,
        rec["url"],
        actions=req.actions,
        check_accessibility=req.check_accessibility,
        check_responsiveness=req.check_responsiveness,
    )
    return {
        "success":                report.success,
        "error":                  report.error,
        "url":                    report.url,
        "screenshot_url":         _screenshot_url(report.screenshot_path),
        "console_errors":         report.console_errors,
        "findings":               [f.__dict__ for f in report.findings],
        "responsive_screenshots": {
            device: _screenshot_url(p) for device, p in report.responsive_screenshots.items()
        },
        "summary": report.summary_text(),
    }


@router.post("/previews/{preview_id}/refresh")
async def refresh_preview(preview_id: str) -> dict:
    """Re-probe a single preview and update its status / framework."""
    rec = preview_manager.get(preview_id)
    if rec is None:
        raise HTTPException(404, f"Preview not found: {preview_id}")
    probe = await preview_manager._probe_port(rec["port"])
    if probe is None:
        updated = preview_manager.update(preview_id, status="unreachable")
    else:
        updated = preview_manager.update(
            preview_id,
            status="active",
            framework=probe["framework"],
        )
    return {"success": True, "preview": updated}


# ---------------------------------------------------------------------------
# Proxy endpoint — lets the dashboard iframe load the preview via same origin
# ---------------------------------------------------------------------------

@router.get("/previews/proxy/{preview_id}/{path:path}")
@router.get("/previews/proxy/{preview_id}")
async def proxy_preview(
    preview_id: str,
    request: Request,
    path: str = "",
) -> Response:
    """
    Proxy requests to a registered preview so they load inside an iframe
    on the dashboard origin.

    Strips X-Frame-Options and Content-Security-Policy headers from the
    upstream response so the iframe is not blocked.

    Security: only forwards to loopback addresses — re-validates the stored
    URL before every request so a race-condition edit cannot introduce SSRF.
    """
    rec = preview_manager.get(preview_id)
    if rec is None:
        raise HTTPException(404, f"Preview not found: {preview_id}")
    if rec["status"] == "closed":
        raise HTTPException(410, "Preview is closed")

    # Re-validate the stored URL — defence-in-depth against stale/corrupt state
    try:
        canonical = _validate_local_url(rec["url"])
    except ValueError as exc:
        raise HTTPException(400, f"Invalid preview URL: {exc}")

    upstream_url = canonical.rstrip("/") + "/" + path.lstrip("/")
    # Forward query string
    if request.url.query:
        upstream_url += "?" + request.url.query

    # Forward safe request headers
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in (
            "host", "origin", "referer", "x-forwarded-for",
            "x-forwarded-proto", "x-forwarded-host",
        )
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=30.0, write=5.0, pool=2.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            upstream = await client.request(
                method=request.method,
                url=upstream_url,
                headers=forward_headers,
                content=await request.body(),
            )
    except httpx.ConnectError:
        raise HTTPException(502, "Preview server unreachable")
    except Exception as exc:
        raise HTTPException(502, f"Proxy error: {exc}")

    # Strip headers that block iframing
    skip_headers = {
        "x-frame-options",
        "content-security-policy",
        "content-security-policy-report-only",
        "transfer-encoding",  # avoid double chunking
        "connection",
    }
    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in skip_headers
    }
    # Allow embedding from any origin
    resp_headers["x-frame-options"] = "ALLOWALL"

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("content-type"),
    )
