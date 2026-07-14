"""
Model Framework v1 — base contract.

Exposes `BaseModel`, the abstract contract every model provider (mock or
real) implements, plus its supporting metadata/status types. See
`base_model.py` for the full contract.
"""

from smartagent.models.base.base_model import BaseModel, ModelHealth, ModelMetadata, ModelStatus

__all__ = ["BaseModel", "ModelHealth", "ModelMetadata", "ModelStatus"]
