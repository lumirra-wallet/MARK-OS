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

    Progressive execution — complexity is auto-detected:
      · Trivial / simple  → fast path (1 LLM call, < 10 s)
      · Medium            → lean pipeline (plan → code → test, max 2 iterations)
      · Large / enterprise→ full pipeline (research → arch → code → test → docs → quality)

    Usage:
        engineer <goal>
        engineer --interactive <goal>
        engineer --test <cmd> <goal>
        engineer --commit <goal>
        engineer --project <name> <goal>
        engineer --timing <goal>          — print per-worker timing report
        engineer analyze <goal>
        engineer clarify <goal>

    Examples:
        engineer create hello.py
        engineer Build a calculator CLI
        engineer --commit Build a FastAPI auth service with JWT
        engineer --interactive --test "pytest" Build a SaaS billing system
        engineer --timing Build a REST API with CRUD endpoints
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
    show_timing = False
    test_cmd    = "pytest"
    project     = ""
    remaining   = list(args)

    if "--interactive" in remaining:
        interactive = True
        remaining.remove("--interactive")
    if "--commit" in remaining:
        auto_commit = True
        remaining.remove("--commit")
    if "--timing" in remaining:
        show_timing = True
        remaining.remove("--timing")
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

    # ── Classify complexity so we can show the right banner BEFORE build() ──
    try:
        from smartagent.performance.complexity import classify_complexity
        detected = classify_complexity(goal)
        complexity_label = detected.value
    except Exception:
        complexity_label = "unknown"

    _tier_label = {
        "trivial":    "Fast path  (< 10 s, single LLM call)",
        "small":      "Fast path  (< 10 s, single LLM call)",
        "medium":     "Lean pipeline  (plan → code → test, no research)",
        "large":      "Full pipeline  (research → arch → code → test → docs)",
        "enterprise": "Full pipeline  (research → arch → code → test → docs → quality)",
    }.get(complexity_label, "Full pipeline")

    print(f"\n  ── Engineer ────────────────────────────────────")
    print(f"  Goal       : {goal[:70]}")
    print(f"  Complexity : {complexity_label}")
    print(f"  Tier       : {_tier_label}")
    if interactive:
        print(f"  Interactive: yes")
    if test_cmd != "pytest":
        print(f"  Test cmd   : {test_cmd}")
    if project:
        print(f"  Project    : {project}")
    print(f"  ────────────────────────────────────────────────\n")

    eng = getattr(agent, "software_engineer", None)
    if eng is None:
        try:
            from smartagent.engineer import SoftwareEngineer
            eng = SoftwareEngineer.with_agent(agent, interactive=interactive)
        except Exception as exc:
            return f"[error] Could not create SoftwareEngineer: {exc}"

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

    # Persist the report on the agent so follow-up queries like
    # "Where is hello.py?" can return the absolute path instead of
    # falling through to the chat model which has no knowledge of the build.
    try:
        agent.last_engineer_report = report
    except Exception:
        pass

    output_lines = ["\n"] + report.as_display_lines()

    # ── Optional timing report ───────────────────────────────────────────
    if show_timing:
        timing_lines = _build_timing_report(eng, report)
        if timing_lines:
            output_lines.append("")
            output_lines.extend(timing_lines)

    return "\n".join(output_lines)


def _build_timing_report(eng: object, report: object) -> list[str]:
    """
    Extract per-worker timing from the ExecutiveController's execution context
    and format it using ``format_timing_table``.

    Returns a list of display lines (empty list if no timing data is available).
    """
    try:
        from smartagent.performance.worker_timer import format_timing_table, WorkerTiming

        # Walk the chain: eng._dev_loop._executive.current_context.metadata
        dev_loop  = getattr(eng, "_dev_loop", None)
        ctrl      = getattr(dev_loop, "_executive", None) if dev_loop else None
        ctx       = getattr(ctrl, "current_context", None) if ctrl else None
        meta      = getattr(ctx, "metadata", {}) if ctx else {}
        timings   = meta.get("worker_timings", [])

        if not timings:
            return ["  (no per-worker timing data — Ollama workers record timing automatically)"]

        return format_timing_table(timings).splitlines()

    except Exception:
        return []


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
  Full Software Engineer commands (progressive execution):

    engineer <goal>                   — auto-detect complexity → right tier
    engineer --interactive <goal>     — ask clarification questions before starting
    engineer --commit <goal>          — auto-commit to git on success
    engineer --test <cmd> <goal>      — custom test command (default: pytest)
    engineer --project <name> <goal>  — inject project memory context
    engineer --timing <goal>          — include per-worker LLM timing report
    engineer analyze <goal>           — analyze requirements only
    engineer clarify <goal>           — show clarification questions without running

  Execution tiers (auto-detected from complexity):

    Trivial / Simple  → Fast path  — 1 LLM call, no pipeline, < 10 seconds
                        create hello.py · add a function · fix a typo
                        create index.html · add CSS file · update one test

    Medium            → Lean pipeline  — plan → code → test (max 2 iterations)
                        calculator CLI · REST API · Flask app · CRUD app

    Large / Enterprise→ Full pipeline  — research → arch → code → test → docs
                        SaaS · AI platform · IDE · enterprise application

  Examples:
    engineer create hello.py
    engineer Build a calculator CLI
    engineer --commit Build a FastAPI auth service with JWT and PostgreSQL
    engineer --interactive Build a SaaS billing system with Stripe
    engineer --timing Build a REST API with CRUD endpoints
    engineer analyze Build a real-time chat application with WebSockets
    engineer clarify Build an e-commerce platform

  MARK acts as a professional coding agent:
    · Auto-routes simple tasks to a fast path (no wasted pipeline overhead)
    · Analyzes requirements and estimates complexity
    · Asks only necessary clarifications (--interactive)
    · Plans work and assigns to specialist workers
    · Writes code, runs tests, fixes bugs autonomously
    · Documents the project (large tasks only)
    · Commits changes (--commit)
    · Summarizes results with a per-worker timing report (--timing)\
"""


def register(router: CommandRouter) -> None:
    """Register engineer commands with *router*."""
    router.register(
        "engineer", handle_engineer,
        "engineer <goal> — Full Software Engineer (analyze → code → test → debug → commit)",
        "CEO", 7,
    )
