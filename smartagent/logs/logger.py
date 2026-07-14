"""
Logging setup.

Provides `configure_logging` and `get_logger` so the rest of SmartAgent
gets consistent, centrally-controlled logging instead of scattered
`print` calls or ad hoc `logging.getLogger` configuration.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure the root logging setup for SmartAgent.

    Safe to call multiple times — only configures handlers once per
    process. Currently just sets up a basic stream handler; will later
    grow to support log files, rotation, structured logging, etc.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger, configuring logging on first use."""
    configure_logging()
    return logging.getLogger(name)
