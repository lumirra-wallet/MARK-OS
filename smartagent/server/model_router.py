"""
Model Router — Feature 15.

Routes different worker types to different models.
Rules are configurable at runtime via the API.

Endpoints (mounted in api_system.py companion file)
---------------------------------------------------
GET  /models/router         — current routing config
POST /models/router         — update routing config
POST /models/router/reset   — reset to defaults
"""
from __future__ import annotations

import logging
import os
from typing import Any

from smartagent.llm.factory import NVIDIA_DEFAULT_MODEL

logger = logging.getLogger(__name__)

# ── Default routing rules ─────────────────────────────────────────────────────
# All workers default to the product's default model — Ollama is not
# supported. These names are legacy (smartagent.executive.workers.*), not
# MARK's live-dashboard worker roster (see smartagent.engineer.worker_roles).

_DEFAULT_ROUTES: dict[str, str] = {
    "ResearchWorker":       NVIDIA_DEFAULT_MODEL,
    "PlanningWorker":       NVIDIA_DEFAULT_MODEL,
    "CodingWorker":         NVIDIA_DEFAULT_MODEL,
    "TestingWorker":        NVIDIA_DEFAULT_MODEL,
    "QualityWorker":        NVIDIA_DEFAULT_MODEL,
    "ReviewWorker":         NVIDIA_DEFAULT_MODEL,
    "DocumentationWorker":  NVIDIA_DEFAULT_MODEL,
    "GitWorker":            NVIDIA_DEFAULT_MODEL,
    "DebugWorker":          NVIDIA_DEFAULT_MODEL,
    "MemoryWorker":         NVIDIA_DEFAULT_MODEL,
    "KnowledgeWorker":      NVIDIA_DEFAULT_MODEL,
    "DesignWorker":         NVIDIA_DEFAULT_MODEL,
    "default":              NVIDIA_DEFAULT_MODEL,
}

_routes: dict[str, str] = dict(_DEFAULT_ROUTES)


def get_model_for_worker(worker_name: str) -> str:
    """Return the model to use for a given worker class name."""
    # Check env override first
    env_key = f"MARK_MODEL_{worker_name.upper()}"
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val
    return _routes.get(worker_name, _routes.get("default", NVIDIA_DEFAULT_MODEL))


def get_all_routes() -> dict[str, str]:
    return dict(_routes)


def update_routes(new_routes: dict[str, str]) -> dict[str, str]:
    _routes.update(new_routes)
    logger.info("Model routes updated: %s", new_routes)
    return dict(_routes)


def reset_routes() -> dict[str, str]:
    global _routes
    _routes = dict(_DEFAULT_ROUTES)
    return dict(_routes)
