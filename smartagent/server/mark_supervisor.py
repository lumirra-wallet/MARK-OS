"""
mark_supervisor.py — Two-process supervisor for MARK OS.

Manages two child processes:
1. LiveKit server (self-hosted open-source binary) — started first, health-checked
2. MARK server (uvicorn) — started after LiveKit is confirmed healthy

Either process crashing triggers an independent restart. Handles SIGTERM/SIGINT
cleanly, terminating both children before exiting.

Also fixes the "Address already in use" stale-port problem that plagued the old
watchdog: clears port 18949 before starting uvicorn so a lingering process from
a previous run can never block the new one.

Usage (replaces watchdog.py as the mark-api package.json entry point):
    python -m smartagent.server.mark_supervisor
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)

# ── Port configuration ─────────────────────────────────────────────────────────
MARK_PORT = int(os.environ.get("PORT", "18949"))

# ── Restart limits ──────────────────────────────────────────────────────────────
MAX_RESTARTS_PER_HOUR = 20
RESTART_WINDOW_SEC    = 3600
_restart_times: list[float] = []


def _under_restart_limit(name: str) -> bool:
    now = time.monotonic()
    _restart_times[:] = [t for t in _restart_times if now - t < RESTART_WINDOW_SEC]
    if len(_restart_times) >= MAX_RESTARTS_PER_HOUR:
        logger.critical("supervisor: restart limit hit for %s — giving up", name)
        return False
    _restart_times.append(now)
    return True


def _wait_port_free(port: int, timeout: float = 6.0) -> None:
    """Poll until the port is actually bindable (up to *timeout* seconds).

    `fuser -k` / `os.kill(SIGKILL)` guarantee the signal is *sent*, but the
    kernel TIME_WAIT state can keep the port busy for another second or two
    after the process exits.  Polling with a real bind() attempt is the only
    reliable way to know when it is safe to start uvicorn.
    """
    import socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("", port))
                return  # port is free
        except OSError:
            time.sleep(0.4)
    logger.warning("supervisor: port %d still busy after %.0f s — proceeding anyway", port, timeout)


def _kill_port(port: int) -> None:
    """Kill any process occupying *port* before we try to bind it."""
    killed = False
    try:
        result = subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            logger.info("supervisor: cleared stale process on port %d (fuser)", port)
            killed = True
    except FileNotFoundError:
        pass  # fuser not available — try lsof
    except Exception:
        pass

    if not killed:
        try:
            r = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=3,
            )
            pids = [p.strip() for p in r.stdout.split() if p.strip()]
            for pid_str in pids:
                try:
                    os.kill(int(pid_str), signal.SIGKILL)
                    logger.info("supervisor: killed PID %s (was holding port %d)", pid_str, port)
                    killed = True
                except Exception:
                    pass
        except Exception:
            pass

    if killed:
        # Poll until the port is actually free — a 0.5 s sleep was never
        # enough; kernel TIME_WAIT can hold it for 1-2 s after SIGKILL.
        _wait_port_free(port)


def _uvicorn_cmd() -> list[str]:
    port = os.environ.get("PORT", str(MARK_PORT))
    return [
        sys.executable, "-m", "uvicorn",
        "smartagent.server.app:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--log-level", "info",
    ]


# ── Per-process supervisor thread ──────────────────────────────────────────────

class _Child:
    """Supervises one child process; restarts on crash."""

    def __init__(self, name: str, cmd: list[str]) -> None:
        self._name    = name
        self._cmd     = cmd
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._stop    = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"sup-{self._name}"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            logger.info("supervisor: starting %s", self._name)
            try:
                self._proc = subprocess.Popen(self._cmd)
                self._proc.wait()
                rc = self._proc.returncode
            except Exception as exc:
                logger.error("supervisor: %s failed to launch: %s", self._name, exc)
                rc = -1

            if self._stop.is_set():
                break

            if not _under_restart_limit(self._name):
                break

            logger.warning(
                "supervisor: %s exited (rc=%s) — restarting in %.0fs",
                self._name, rc, backoff,
            )
            self._stop.wait(timeout=backoff)
            backoff = min(backoff * 1.5, 30)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    logger.info("MARK supervisor starting (uvicorn port %d)", MARK_PORT)

    # 1. Clear any stale process on MARK's port
    _kill_port(MARK_PORT)

    # 2. Start LiveKit (self-hosted mode only)
    lk_child: _Child | None = None
    try:
        from smartagent.server.livekit_process import (
            LiveKitProcess, LIVEKIT_PORT, wait_healthy, _is_self_hosted,
        )
        if _is_self_hosted():
            lk = LiveKitProcess()
            try:
                lk.start()
                logger.info("supervisor: waiting for LiveKit on port %d …", LIVEKIT_PORT)
                if wait_healthy(LIVEKIT_PORT, timeout=25):
                    logger.info("supervisor: ✓ LiveKit healthy")
                else:
                    logger.warning("supervisor: LiveKit not healthy after 25 s — voice unavailable")
            except Exception as exc:
                logger.warning("supervisor: LiveKit start failed (%s) — voice unavailable", exc)
        else:
            lk_url = os.environ.get("LIVEKIT_URL", "")
            logger.info("supervisor: cloud LiveKit mode (%s) — no local binary", lk_url)
    except ImportError:
        logger.info("supervisor: livekit_process not available — skipping LiveKit")

    # 3. Start and supervise uvicorn
    uv = _Child("uvicorn", _uvicorn_cmd())
    uv.start()

    # 4. Signal handling
    def _shutdown(sig: int, _frame: object) -> None:
        logger.info("supervisor: caught signal %d — shutting down", sig)
        uv.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    # 5. Keep main thread alive (watchdog)
    try:
        while True:
            time.sleep(5)
            if not uv.is_alive():
                logger.error("supervisor: uvicorn supervisor thread died — exiting")
                sys.exit(1)
    except KeyboardInterrupt:
        _shutdown(signal.SIGINT, None)


if __name__ == "__main__":
    main()
