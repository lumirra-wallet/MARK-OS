"""
smartagent.debug — Milestone 20: Self Debugging.

MARK can run a test command, read the failure traceback, fix the offending
file, and loop until the tests go green — exactly like an experienced developer.

Key classes::

    TracebackParser   — parse Python tracebacks into structured data
    DebugLoop         — run → parse → fix → repeat loop
    DebugWorker       — AI-powered fixer (BaseWorker subclass)

Typical usage::

    from smartagent.debug import DebugLoop, DebugWorker

    worker = DebugWorker()
    loop   = DebugLoop(max_attempts=5, debug_worker=worker)
    result = loop.run("pytest tests/test_auth.py")
    print("\\n".join(result.as_display_lines()))
"""

from smartagent.debug.traceback_parser import (
    ParsedTraceback,
    TracebackFrame,
    TracebackParser,
)
from smartagent.debug.debug_loop import (
    DebugAttempt,
    DebugLoop,
    DebugResult,
)

__all__ = [
    "DebugAttempt",
    "DebugLoop",
    "DebugResult",
    "ParsedTraceback",
    "TracebackFrame",
    "TracebackParser",
]
