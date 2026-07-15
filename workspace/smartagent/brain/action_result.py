"""
ActionResult — the common return type for every Brain v2 module.

Every module the `ModuleRegistry` knows about (memory, skills, tools,
planning, research, models, voice, vision, automation, ...) must return an
`ActionResult` from its handler. Standardizing on one shape is what lets
`BrainRouter` treat every module identically — it never needs to know
*how* a module produced its answer, only whether it succeeded and what to
do with the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ActionResult:
    """
    The outcome of a single module handling a request.

    Attributes:
        success: Whether the module was able to meaningfully handle the
            request. `BrainRouter` uses this to decide whether to stop
            (this module answered) or fall through to the next candidate
            module in priority order.
        message: Human-readable response text.
        data: Optional structured payload behind `message` (e.g. the list
            of `MemoryEntry` objects a memory search matched). Useful for
            callers that want more than the rendered text.
        source: Name of the module that produced this result (matches the
            name it registered under in `ModuleRegistry`).
        execution_time: Seconds the module took to produce this result.
        confidence: How confident the module is in this result, from 0.0
            (no confidence / could not help) to 1.0 (certain). Modules that
            set `success=False` should generally also report `0.0`.
    """

    success: bool
    message: str
    data: Any = None
    source: str = ""
    execution_time: float = 0.0
    confidence: float = 0.0
