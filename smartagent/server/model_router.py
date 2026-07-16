"""
Model Router — Feature 15.

Routes different worker types to different Ollama models.
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

logger = logging.getLogger(__name__)

# ── Default routing rules ─────────────────────────────────────────────────────

_DEFAULT_ROUTES: dict[str, str] = {
    "ResearchWorker":       "llama3.1:8b",
    "PlanningWorker":       "llama3.1:8b",
    "CodingWorker":         "qwen2.5-coder:7b",
    "TestingWorker":        "qwen2.5-coder:7b",
    "QualityWorker":        "llama3.1:8b",
    "ReviewWorker":         "llama3.1:8b",
    "DocumentationWorker":  "llama3.1:8b",
    "GitWorker":            "llama3.1:8b",
    "DebugWorker":          "qwen2.5-coder:7b",
    "MemoryWorker":         "llama3.1:8b",
    "KnowledgeWorker":      "llama3.1:8b",
    "DesignWorker":         "llama3.1:8b",
    "default":              "llama3.1:8b",
}

_routes: dict[str, str] = dict(_DEFAULT_ROUTES)


def get_model_for_worker(worker_name: str) -> str:
    """Return the model to use for a given worker class name."""
    # Check env override first
    env_key = f"MARK_MODEL_{worker_name.upper()}"
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val
    return _routes.get(worker_name, _routes.get("default", "llama3.1:8b"))


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
