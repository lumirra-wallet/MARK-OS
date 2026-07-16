"""
Autonomous Development Loop — Milestone 24.

MARK autonomously cycles through: Receive Goal → Plan → Code → Test →
Debug → Reflect → Retry → Success.  No human intervention required.

Usage::

    from smartagent.dev_loop import DevLoop

    loop   = DevLoop.with_agent(agent)
    result = loop.run("Build a login system")
    print("\\n".join(result.as_display_lines()))
"""

from smartagent.dev_loop.dev_loop import DevLoop
from smartagent.dev_loop.loop_result import LoopResult, LoopIteration

__all__ = ["DevLoop", "LoopResult", "LoopIteration"]
