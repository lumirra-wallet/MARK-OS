"""
Full Software Engineer console commands — Milestone 25.

Commands registered:
    engineer <goal>               — full engineer pipeline (analyze → code → test → commit)
    engineer --interactive <goal> — ask clarification questions before starting
    engineer analyze <goal>       — analyze requirements only, no execution
    engineer clarify <goal>       — show clarification questions for a goal
    engineer help                 — show this listing
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


def handle_engineer(agent: "SmartAgent", args: list[str]) -> str:
    """
    Full Software Engineer: analyze → clarify → plan → code → test → debug → commit → summarize.

    Usage:
        engineer <goal>
        engineer --interactive <goal>
        engineer --test <cmd> <goal>
        engineer --commit <goal>
        engineer --project <name> <goal>
        engineer analyze <goal>
        engineer clarify <goal>

    Examples:
        engineer Build me a Trello clone
        engineer --commit Build a FastAPI auth service with JWT
        engineer --interactive --test "pytest" Build a SaaS billing system
        engineer analyze Build a real-time chat application
        engineer clarify Build an e-commerce platform

    MARK acts as a professional coding agent: it analyzes requirements, asks
    only necessary clarifications, divides into teams, writes code, runs tests,
    fixes bugs, documents the project, commits changes, and summarizes results.
    """
    if not args or args[0].lower() == "help":
        return _help()

    sub = args[0].lower()
    rest = args[1:]

    if sub == "analyze":
        return _sub_analyze(agent, rest)
    if sub == "clarify":
        return _sub_clarify(agent, rest)

    # Main build flow — parse flags
    interactive = False
    auto_commit = False
    test_cmd    = "pytest"
    project     = ""
    remaining   = list(args)

    if "--interactive" in remaining:
        interactive = True
        remaining.remove("--interactive")
    if "--commit" in remaining:
        auto_commit = True
        remaining.remove("--commit")
    for flag in ["--test", "--project"]:
        while flag in remaining:
            idx = remaining.index(flag)
            if idx + 1 < len(remaining):
                val = remaining[idx + 1]
                if flag == "--test":
                    test_cmd = val
                elif flag == "--project":
                    project = val
                remaining = remaining[:idx] + remaining[idx + 2:]

    if not remaining:
        return "Usage: engineer <goal>\nRun 'engineer help' for details."

    goal = " ".join(remaining)

    eng = getattr(agent, "software_engineer", None)
    if eng is None:
        try:
            from smartagent.engineer import SoftwareEngineer
            eng = SoftwareEngineer.with_agent(agent, interactive=interactive)
        except Exception as exc:
            return f"[error] Could not create SoftwareEngineer: {exc}"

    print(f"\n  Engineer starting: {goal[:72]}")
    print(f"  Interactive: {'yes' if interactive else 'no'}")
    print(f"  Test command: {test_cmd}")
    if project:
        print(f"  Project context: {project}")
    print("  Analyzing requirements...\n")

    try:
        report = eng.build(
            goal=goal,
            test_cmd=test_cmd,
            auto_commit=auto_commit,
            interactive=interactive,
            project_name=project,
        )
    except Exception as exc:
        return f"[error] Engineer pipeline failed: {exc}"

    return "\n" + "\n".join(report.as_display_lines())


def _sub_analyze(agent: "SmartAgent", args: list[str]) -> str:
    """Analyze requirements only — no execution."""
    if not args:
        return "Usage: engineer analyze <goal>"
    goal = " ".join(args)
    try:
        from smartagent.engineer.requirement_analyzer import RequirementAnalyzer
        analyzer = RequirementAnalyzer(
            model_manager=getattr(agent, "model_manager", None),
        )
        report = analyzer.analyze(goal)
        lines = ["  Requirement Analysis:", ""] + report.as_display_lines()
        return "\n".join(lines)
    except Exception as exc:
        return f"[error] Analysis failed: {exc}"


def _sub_clarify(agent: "SmartAgent", args: list[str]) -> str:
    """Show what clarification questions MARK would ask."""
    if not args:
        return "Usage: engineer clarify <goal>"
    goal = " ".join(args)
    try:
        from smartagent.engineer.requirement_analyzer import RequirementAnalyzer
        from smartagent.engineer.clarification_engine import ClarificationEngine
        req = RequirementAnalyzer().analyze(goal)
        cset = ClarificationEngine().from_report(req)
        return "\n".join(cset.as_display_lines())
    except Exception as exc:
        return f"[error] Clarification engine failed: {exc}"


def _help() -> str:
    return """\
  Full Software Engineer commands:

    engineer <goal>                   — full pipeline: analyze→code→test→debug→summarize
    engineer --interactive <goal>     — ask clarification questions before starting
    engineer --commit <goal>          — auto-commit to git on success
    engineer --test <cmd> <goal>      — custom test command (default: pytest)
    engineer --project <name> <goal>  — inject project memory context
    engineer analyze <goal>           — analyze requirements only
    engineer clarify <goal>           — show clarification questions without running

  Examples:
    engineer Build me a Trello clone
    engineer --commit Build a FastAPI auth service with JWT and PostgreSQL
    engineer --interactive Build a SaaS billing system with Stripe
    engineer analyze Build a real-time chat application with WebSockets
    engineer clarify Build an e-commerce platform

  MARK acts as a professional coding agent:
    · Analyzes requirements and estimates complexity
    · Asks only necessary clarifications (--interactive)
    · Plans work using multi-agent teams
    · Writes code, runs tests, fixes bugs autonomously
    · Documents the project
    · Commits changes (--commit)
    · Summarizes results\
"""


def register(router: CommandRouter) -> None:
    """Register engineer commands with *router*."""
    router.register(
        "engineer", handle_engineer,
        "engineer <goal> — Full Software Engineer (analyze → code → test → debug → commit)",
        "CEO", 7,
    )
