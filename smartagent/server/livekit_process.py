"""
livekit_process.py — Self-hosted LiveKit server binary management.

Downloads the LiveKit open-source server binary from GitHub releases on
first use, generates a minimal config.yaml from env vars, and provides a
LiveKitProcess class that supervises the binary as a child subprocess.

No LiveKit Cloud account is required. API keys are locally generated strings
that MARK owns entirely. The binary is cached in .mark_storage/livekit/ and
never re-downloaded unless deleted.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Optional

import yaml  # pyyaml — already in requirements.minimal.txt

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
LIVEKIT_VERSION    = os.environ.get("LIVEKIT_VERSION", "v1.13.4")
LIVEKIT_PORT       = int(os.environ.get("LIVEKIT_PORT", "7880"))
LIVEKIT_TCP_PORT   = int(os.environ.get("LIVEKIT_TCP_PORT", "7881"))
LIVEKIT_RTC_START  = int(os.environ.get("LIVEKIT_RTC_PORT_START", "50000"))
LIVEKIT_RTC_END    = int(os.environ.get("LIVEKIT_RTC_PORT_END",   "60000"))

_CACHE_DIR    = Path(os.environ.get("MARK_LIVEKIT_CACHE",
                                    str(Path.home() / ".cache" / "mark-livekit")))
_BINARY_PATH  = _CACHE_DIR / "livekit-server"
_CONFIG_PATH  = _CACHE_DIR / "config.yaml"
def _make_download_url(version: str) -> str:
    # Since v1.x the release asset embeds the version in the filename:
    # livekit_1.13.4_linux_amd64.tar.gz  (strip leading 'v' for the filename)
    # Older builds used: livekit_linux_amd64.tar.gz (no version in name)
    ver_bare = version.lstrip("v")       # e.g. "1.13.4"
    ver_major = int(ver_bare.split(".")[0])
    ver_minor = int(ver_bare.split(".")[1]) if ver_bare.count(".") >= 1 else 0
    # Versioned filename format introduced in v1.8+
    if ver_major > 1 or (ver_major == 1 and ver_minor >= 8):
        filename = f"livekit_{ver_bare}_linux_amd64.tar.gz"
    else:
        filename = "livekit_linux_amd64.tar.gz"
    return f"https://github.com/livekit/livekit/releases/download/{version}/{filename}"


_DOWNLOAD_URL = _make_download_url(LIVEKIT_VERSION)


def _is_self_hosted() -> bool:
    """True when LIVEKIT_URL is absent or points at localhost — self-hosted mode."""
    url = os.environ.get("LIVEKIT_URL", "")
    if not url:
        return True
    host = url.replace("ws://", "").replace("wss://", "").split("/")[0].split(":")[0]
    return host in ("localhost", "127.0.0.1", "::1")


def _ensure_binary() -> Path:
    """Download and cache the LiveKit server binary. Idempotent."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if _BINARY_PATH.exists() and _BINARY_PATH.stat().st_size > 0:
        logger.debug("livekit_process: binary cache hit at %s", _BINARY_PATH)
        return _BINARY_PATH

    logger.info(
        "livekit_process: downloading LiveKit %s (first run — cached after this)",
        LIVEKIT_VERSION,
    )
    tar_path = _CACHE_DIR / "livekit.tar.gz"
    try:
        urllib.request.urlretrieve(_DOWNLOAD_URL, tar_path)
    except Exception as exc:
        raise RuntimeError(
            f"livekit_process: failed to download binary from {_DOWNLOAD_URL}: {exc}\n"
            "Set LIVEKIT_VERSION to a valid release tag, or download manually and place\n"
            f"the 'livekit-server' binary at {_BINARY_PATH}"
        ) from exc

    with tarfile.open(tar_path, "r:gz") as tf:
        # The tar may contain 'livekit-server' or 'livekit' depending on version
        members = tf.getnames()
        target = next(
            (m for m in members if m in ("livekit-server", "livekit")),
            members[0] if members else None,
        )
        if not target:
            raise RuntimeError("livekit_process: tar archive is empty — bad download?")
        member = tf.getmember(target)
        member.name = "livekit-server"  # normalise name
        tf.extract(member, _CACHE_DIR, set_attrs=False)

    tar_path.unlink(missing_ok=True)
    _BINARY_PATH.chmod(0o755)
    logger.info("livekit_process: binary ready at %s", _BINARY_PATH)
    return _BINARY_PATH


def _write_config() -> Path:
    """Write a fresh config.yaml from the current environment. Called each start."""
    api_key    = os.environ.get("LIVEKIT_API_KEY", "mark-local-key")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "mark-local-secret-change-me")

    config: dict = {
        "port": LIVEKIT_PORT,
        "rtc": {
            "port_range_start": LIVEKIT_RTC_START,
            "port_range_end":   LIVEKIT_RTC_END,
            "tcp_port":         LIVEKIT_TCP_PORT,
            "use_external_ip":  True,   # so ICE candidates include the host's public IP
        },
        "keys": {api_key: api_secret},
        "logging": {"level": "warn", "json": False},
    }

    # TURN relay over TCP — helps in environments that block UDP (e.g. some proxies)
    turn_udp = int(os.environ.get("LIVEKIT_TURN_UDP_PORT", "0"))
    if turn_udp:
        config["turn"] = {
            "enabled":  True,
            "udp_port": turn_udp,
            "tcp_port": int(os.environ.get("LIVEKIT_TURN_TCP_PORT", "3478")),
        }

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(yaml.dump(config, default_flow_style=False))
    logger.debug("livekit_process: config written to %s", _CONFIG_PATH)
    return _CONFIG_PATH


def wait_healthy(port: int = LIVEKIT_PORT, timeout: float = 20.0) -> bool:
    """Poll TCP port until LiveKit is accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                logger.info("livekit_process: LiveKit healthy on port %d", port)
                return True
        except OSError:
            time.sleep(0.25)
    return False


class LiveKitProcess:
    """Manages the LiveKit server binary as a child subprocess."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None  # type: ignore[type-arg]

    def start(self) -> None:
        if not _is_self_hosted():
            logger.info("livekit_process: cloud mode — not starting local binary")
            return

        binary  = _ensure_binary()
        config  = _write_config()
        cmd     = [str(binary), "--config", str(config)]

        logger.info("livekit_process: starting LiveKit server (port %d)", LIVEKIT_PORT)
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            logger.info("livekit_process: stopping LiveKit server")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def returncode(self) -> Optional[int]:
        if self._proc is None:
            return None
        return self._proc.poll()
