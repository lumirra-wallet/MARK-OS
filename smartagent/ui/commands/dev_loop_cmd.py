"""
Autonomous Development Loop console commands — Milestone 24.

Commands registered:
    dev-loop <goal>               — run the autonomous dev loop
    dev-loop --test <cmd> <goal>  — specify a custom test command
    dev-loop --commit <goal>      — auto-commit on success
    dev-loop help                 — show this listing
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


def handle_dev_loop(agent: "SmartAgent", args: list[str]) -> str:
    """
    Run the autonomous development loop: plan → code → test → debug → reflect → retry.

    Usage:
        dev-loop <goal>
        dev-loop --test <cmd> <goal>
        dev-loop --commit <goal>
        dev-loop --iterations <n> <goal>

    Examples:
        dev-loop Build a login system
        dev-loop --test "pytest tests/auth/" Build JWT authentication
        dev-loop --commit --test "pytest" Build a user CRUD API
        dev-loop --iterations 3 Fix the failing tests

    MARK autonomously cycles through planning, coding, testing, debugging,
    and reflection.  It retries up to 5 times (or --iterations) until all
    tests pass or it gives up.
    """
    if not args or args[0].lower() == "help":
        return _help()

    # Parse flags
    test_cmd    = "pytest"
    auto_commit = False
    max_iters   = 5
    remaining   = list(args)

    for flag in ["--test", "--iterations"]:
        while flag in remaining:
            idx = remaining.index(flag)
            if idx + 1 < len(remaining):
                val = remaining[idx + 1]
                if flag == "--test":
                    test_cmd = val
                elif flag == "--iterations":
                    try:
                        max_iters = int(val)
                    except ValueError:
                        return f"[error] --iterations expects an integer, got {val!r}"
                remaining = remaining[:idx] + remaining[idx + 2:]

    if "--commit" in remaining:
        auto_commit = True
        remaining.remove("--commit")

    if not remaining:
        return "Usage: dev-loop <goal>\nRun 'dev-loop help' for details."

    goal = " ".join(remaining)

    # Build or retrieve dev loop
    dev_loop = getattr(agent, "dev_loop", None)
    if dev_loop is None:
        try:
            from smartagent.dev_loop import DevLoop
            dev_loop = DevLoop.with_agent(agent, max_iterations=max_iters)
        except Exception as exc:
            return f"[error] Could not create DevLoop: {exc}"

    print(f"\n  Dev Loop starting: {goal[:72]}")
    print(f"  Test command: {test_cmd}")
    print(f"  Max iterations: {max_iters}")
    print("  Working autonomously...\n")

    try:
        result = dev_loop.run(
            goal=goal,
            test_cmd=test_cmd,
            auto_commit=auto_commit,
        )
    except Exception as exc:
        return f"[error] Dev loop failed: {exc}"

    return "\n" + "\n".join(result.as_display_lines())


def _help() -> str:
    return """\
  Autonomous Development Loop commands:

    dev-loop <goal>                   — plan → code → test → debug → retry
    dev-loop --test <cmd> <goal>      — custom test command (default: pytest)
    dev-loop --commit <goal>          — auto-commit to git on success
    dev-loop --iterations <n> <goal>  — max retries (default: 5)

  Examples:
    dev-loop Build a login system
    dev-loop --test "pytest tests/" Add password reset functionality
    dev-loop --commit --test "pytest" Implement user roles
    dev-loop --iterations 3 Fix the failing auth tests

  The loop runs until:
    · All tests pass (success)
    · Max iterations reached
    · Planning fails

  Use 'ceo <goal>' for a simpler run without the debug/retry loop.\
"""


def register(router: CommandRouter) -> None:
    """Register dev-loop commands with *router*."""
    router.register(
        "dev-loop", handle_dev_loop,
        "dev-loop <goal> — Autonomous Dev Loop (code → test → debug → reflect → retry)",
        "CEO", 6,
    )
