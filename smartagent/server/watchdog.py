"""
watchdog.py — MARK's process supervisor.

Runs uvicorn as a child process and automatically restarts it if it crashes.
MARK's server never stays down — if uvicorn exits for any reason other than
a deliberate SIGTERM/SIGINT to this parent process, it comes back within 3s.

Usage (called by artifacts/mark-api/package.json):
    python -m smartagent.server.watchdog

Environment variables:
    PORT          — port to bind uvicorn (default 18949)
    MARK_WATCHDOG_MAX_RESTARTS  — safety ceiling on restarts per hour (default 20)
    MARK_WATCHDOG_BACKOFF       — seconds to wait between restarts (default 3)
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PORT = os.environ.get("PORT", "18949")
BACKOFF = float(os.environ.get("MARK_WATCHDOG_BACKOFF", "3"))
MAX_RESTARTS_PER_HOUR = int(os.environ.get("MARK_WATCHDOG_MAX_RESTARTS", "20"))

_stop = False


def _on_signal(signum, _frame):
    global _stop
    logger.info("Received signal %s — shutting down cleanly", signum)
    _stop = True


signal.signal(signal.SIGTERM, _on_signal)
signal.signal(signal.SIGINT, _on_signal)


def _uvicorn_cmd() -> list[str]:
    return [
        sys.executable, "-m", "uvicorn",
        "smartagent.server.app:app",
        "--host", "0.0.0.0",
        "--port", PORT,
        "--reload",
        "--reload-dir", "smartagent",
    ]


def run() -> None:
    restarts: list[float] = []
    attempt = 0

    while not _stop:
        attempt += 1
        now = time.time()

        # Prune restart timestamps older than 1 hour
        restarts = [t for t in restarts if now - t < 3600]
        if len(restarts) >= MAX_RESTARTS_PER_HOUR:
            logger.error(
                "MARK server has restarted %d times in the last hour — "
                "something is repeatedly crashing. Pausing 60s before next attempt.",
                len(restarts),
            )
            time.sleep(60)
            restarts.clear()

        logger.info("Starting MARK server (attempt #%d) on port %s", attempt, PORT)
        try:
            proc = subprocess.Popen(
                _uvicorn_cmd(),
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            )
        except Exception as exc:
            logger.error("Failed to start uvicorn: %s — retrying in %.0fs", exc, BACKOFF)
            time.sleep(BACKOFF)
            continue

        restarts.append(time.time())

        # Wait for the child to exit
        while not _stop:
            try:
                rc = proc.wait(timeout=1)
                # Child exited
                if _stop:
                    break
                if rc == 0:
                    logger.info("MARK server exited cleanly (rc=0) — restarting")
                else:
                    logger.warning(
                        "MARK server exited with rc=%d — restarting in %.0fs",
                        rc, BACKOFF,
                    )
                    time.sleep(BACKOFF)
                break
            except subprocess.TimeoutExpired:
                continue  # still running, keep polling

        if _stop and proc.poll() is None:
            logger.info("Watchdog stopping — terminating child process")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    logger.info("MARK watchdog exited")


if __name__ == "__main__":
    run()
