"""
Logging setup.

Provides `configure_logging` and `get_logger` so the rest of SmartAgent
gets consistent, centrally-controlled logging instead of scattered
`print` calls or ad hoc `logging.getLogger` configuration.

Milestone 8 change: `get_logger` no longer implicitly triggers
`configure_logging`, so `main.py` (or any process entry point) can call
`configure_logging` first with full control over handlers (file-only,
console+file, or neither).  Tests that never call `configure_logging`
still work fine — Python routes unconfigured loggers to
`logging.lastResort` (stderr, WARNING+ only), which is the standard
library default.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def configure_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
    log_to_console: bool = True,
) -> None:
    """
    Configure the root logger for SmartAgent.

    Safe to call multiple times — only installs handlers once per process.

    Args:
        level: Root log level (e.g. ``logging.DEBUG``).
        log_file: Path to a log file.  Parent directories are created
            automatically.  ``None`` means no file handler is added.
        log_to_console: When ``True`` a ``StreamHandler`` (stderr) is
            included.  Set to ``False`` to silence the console — the
            interactive MARK console does this so log noise never appears
            on screen while the REPL is running.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = []

    if log_to_console:
        handlers.append(logging.StreamHandler())

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        handlers.append(fh)

    # NullHandler so the root logger is never left completely unconfigured
    # (avoids "No handlers could be found" warnings on Python 3.1).
    if not handlers:
        handlers.append(logging.NullHandler())

    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a module-scoped logger.

    Does **not** call ``configure_logging`` — callers are responsible for
    configuring the root logger before their first log line matters.
    """
    return logging.getLogger(name)
