"""
MARK FastAPI application.

Creates the FastAPI app, wires up CORS, includes all routers, and
sets up a startup/shutdown lifespan that logs the server URL.

Start::

    uvicorn smartagent.server.app:app --reload --port 8000

Or via pnpm::

    pnpm run mark:server
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from smartagent.server.api              import router
from smartagent.server.api_system       import router as system_router
from smartagent.server.api_tools        import router as tools_router
from smartagent.server.api_timeline     import router as timeline_router
from smartagent.server.api_checkpoints  import router as checkpoints_router
from smartagent.server.api_eval         import router as eval_router
from smartagent.server.api_jobs         import router as jobs_router
from smartagent.server.api_task_graph   import router as task_graph_router
from smartagent.server.api_code         import router as code_router
from smartagent.server.api_terminal     import router as terminal_router
from smartagent.server.api_git_enhanced import router as git_enhanced_router
from smartagent.server.api_providers    import router as providers_router
from smartagent.server.api_diagnostics  import router as diagnostics_router
from smartagent.server.api_previews     import router as previews_router, preview_manager
from smartagent.server.voice_manager    import voice_manager
from smartagent.server.websocket        import connection_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    import asyncio
    port = os.environ.get("PORT", "8000")
    logger.info("MARK server starting on port %s", port)
    # Use configurable URL for startup log — avoids localhost assumption in cloud deployments
    base_url = os.environ.get("API_BASE_URL", f"http://localhost:{port}")
    print(f"  [server] MARK API ready  →  {base_url}")
    print(f"  [server] WebSocket stream →  {base_url.replace('http', 'ws')}/ws")

    # Auto-detect workspace from git if not already set
    try:
        import subprocess
        from smartagent.server import api as _api  # type: ignore[attr-defined]
        if not getattr(_api, "_state", None):
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                detected = result.stdout.strip()
                if detected:
                    _api._state = type("_WS", (), {"workspace": detected, "cwd": detected})()
                    logger.info("Auto-detected workspace: %s", detected)
    except Exception:
        pass  # workspace detection is best-effort

    # Wire the VoiceManager to the live connection_manager so voice events
    # can broadcast over WebSocket even between build runs.
    loop = asyncio.get_running_loop()
    voice_manager.install(None, connection_manager, loop)

    # Start the preview auto-detection loop
    import os as _os
    _scan_interval = float(_os.environ.get("PREVIEW_SCAN_INTERVAL", "15"))
    preview_manager.start_detection(loop, connection_manager, interval=_scan_interval)

    yield
    logger.info("MARK server shutting down")
    preview_manager.stop_detection()
    if voice_manager.running:
        voice_manager.stop()


app = FastAPI(
    title="MARK AI OS — Web API",
    description=(
        "REST + WebSocket layer over the MARK backend.\n\n"
        "All intelligence stays in the existing Python subsystems; "
        "this API is a thin presentation bridge."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow all origins in development so the React dashboard (running on
# a different port) can connect without proxy config.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(router)
app.include_router(system_router)
app.include_router(tools_router)
app.include_router(timeline_router)
app.include_router(checkpoints_router)
app.include_router(eval_router)
app.include_router(jobs_router)
app.include_router(task_graph_router)
app.include_router(code_router)
app.include_router(terminal_router)
app.include_router(git_enhanced_router)
app.include_router(providers_router)
app.include_router(diagnostics_router)
app.include_router(previews_router)

# ---------------------------------------------------------------------------
# Combined server — serve the built dashboard from this same process/port.
#
# `pnpm --filter @workspace/mark-dashboard run build` outputs to
# artifacts/mark-dashboard/dist/public (see vite.config.ts). If that build
# exists, mount its static assets and add a SPA-fallback route so client-side
# routing (wouter) works on refresh/deep links. If it doesn't exist (e.g. a
# fresh checkout, or split dev mode via `pnpm dev:backend` + `dev:frontend`),
# this is a no-op — the API-only behaviour is unchanged.
# ---------------------------------------------------------------------------
_DASHBOARD_DIST = Path(__file__).resolve().parents[2] / "artifacts" / "mark-dashboard" / "dist" / "public"

if _DASHBOARD_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DASHBOARD_DIST / "assets"), name="dashboard-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _serve_dashboard(full_path: str) -> FileResponse:
        """Serve the built dashboard SPA; unmatched client-side routes fall back to index.html.

        Resolves and checks ``is_relative_to()`` (not ``startswith()``) so a
        path containing ``..`` segments can't escape ``_DASHBOARD_DIST``.
        """
        candidate = (_DASHBOARD_DIST / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(_DASHBOARD_DIST)
        ):
            return FileResponse(candidate)
        return FileResponse(_DASHBOARD_DIST / "index.html")

    logger.info("Serving built dashboard from %s (combined-server mode)", _DASHBOARD_DIST)
else:
    logger.info(
        "No dashboard build at %s — running API-only. "
        "Run `pnpm --filter @workspace/mark-dashboard build` for combined-server mode.",
        _DASHBOARD_DIST,
    )

# ---------------------------------------------------------------------------
# Path-prefix stripping — applied LAST so all add_middleware / include_router
# calls above finish on the real FastAPI instance first.
#
# Set ROOT_PATH_PREFIX=/mark-api when the reverse proxy does NOT strip the
# path prefix before forwarding (Replit's default behaviour).
# ---------------------------------------------------------------------------
_root_prefix: str = os.environ.get("ROOT_PATH_PREFIX", "").rstrip("/")

if _root_prefix:
    _fastapi_app = app  # keep a reference for tests that import `app`

    class _StripPrefixMiddleware:
        """Minimal ASGI wrapper: strips ROOT_PATH_PREFIX from every request."""
        __slots__ = ("_app", "_prefix")

        def __init__(self) -> None:
            self._app = _fastapi_app
            self._prefix = _root_prefix

        async def __call__(self, scope: dict, receive, send) -> None:  # type: ignore[type-arg]
            if scope.get("type") in ("http", "websocket"):
                path: str = scope.get("path", "")
                if path.startswith(self._prefix):
                    scope = dict(scope)
                    stripped = path[len(self._prefix):] or "/"
                    scope["path"] = stripped
                    scope["raw_path"] = stripped.encode()
            await self._app(scope, receive, send)

    app = _StripPrefixMiddleware()  # type: ignore[assignment]
