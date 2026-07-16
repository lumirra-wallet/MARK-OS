"""
Long Running Execution console commands — Milestone 23.

Commands registered:
    long-run <goal>           — run the full CEO pipeline and show a completion report
    long-run --project <name> — inject project context before running
    long-run help             — show this listing
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


def handle_long_run(agent: "SmartAgent", args: list[str]) -> str:
    """
    Run a long-running CEO execution and display a structured completion report.

    Usage:
        long-run <goal>
        long-run --project <name> <goal>

    Example:
        long-run Build a SaaS backend with FastAPI, pytest, and PostgreSQL
        long-run --project my-api Add JWT authentication

    MARK works through the full multi-agent pipeline (research → engineering →
    testing → documentation) and returns a report showing what was completed,
    what failed, and what remains.
    """
    if not args or args[0].lower() == "help":
        return _help()

    # Parse --project flag
    project_name = ""
    remaining = list(args)
    if "--project" in remaining:
        idx = remaining.index("--project")
        if idx + 1 < len(remaining):
            project_name = remaining[idx + 1]
            remaining = remaining[:idx] + remaining[idx + 2:]

    if not remaining:
        return "Usage: long-run <goal>\nRun 'long-run help' for details."

    goal = " ".join(remaining)

    engine = getattr(agent, "long_running_engine", None)
    if engine is None:
        # Build on-demand
        try:
            from smartagent.long_running import LongRunningEngine
            engine = LongRunningEngine.with_agent(agent)
        except Exception as exc:
            return f"[error] Could not create LongRunningEngine: {exc}"

    print(f"\n  Starting long-run: {goal[:72]}")
    if project_name:
        print(f"  Project context: {project_name}")
    print("  Working...\n")

    def on_phase(phase, report):
        print(f"  {phase.icon} {phase.name}  ({phase.elapsed:.1f}s)")

    try:
        report = engine.run(goal, on_phase_done=on_phase, project_name=project_name)
    except Exception as exc:
        return f"[error] Long-run failed: {exc}"

    return "\n" + "\n".join(report.as_display_lines())


def _help() -> str:
    return """\
  Long Running Execution commands:

    long-run <goal>                      — run the full multi-agent pipeline
    long-run --project <name> <goal>     — include project memory context

  Examples:
    long-run Build a SaaS backend with FastAPI and PostgreSQL
    long-run --project my-api Add rate limiting to the API
    long-run Build a React dashboard with authentication and payments

  MARK runs the research → engineering → QA → documentation pipeline and
  returns a structured report showing completed phases, failures, and what
  remains.  Use 'ceo <goal>' for a leaner run without the report structure.\
"""


def register(router: CommandRouter) -> None:
    """Register long-run commands with *router*."""
    router.register(
        "long-run", handle_long_run,
        "long-run <goal> — Long Running Execution with structured completion report",
        "CEO", 5,
    )
