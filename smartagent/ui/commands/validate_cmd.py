"""
Validate command — Phase 9: Validation.

Demonstrates MARK completing a set of standard engineering tasks end-to-end.

Commands registered:
    validate                   — run the full Phase 9 validation suite
    validate list              — list all validation scenarios
    validate run <name>        — run a single scenario by name
    validate help              — show this listing

Each scenario is a short, self-contained goal passed to the SoftwareEngineer
pipeline.  The command records which scenarios pass/fail and prints a
structured report.

Note: Scenarios require a running agent with DevLoop, QualityRunner, and
workspace access.  In CI / offline mode (no Ollama), planning succeeds but
the AI coding step is skipped — the report still shows the full pipeline
execution trace.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Validation scenarios
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    goal: str
    test_cmd: str = "pytest"
    description: str = ""


_SCENARIOS: list[Scenario] = [
    Scenario(
        name="calculator-cli",
        goal="Build a Calculator CLI with add, subtract, multiply, divide operations",
        test_cmd="pytest",
        description="Basic CLI with arithmetic operations and pytest tests",
    ),
    Scenario(
        name="rest-api",
        goal="Build a REST API with CRUD endpoints for a Todo resource using FastAPI",
        test_cmd="pytest",
        description="FastAPI Todo API with GET, POST, PUT, DELETE endpoints",
    ),
    Scenario(
        name="flask-blog",
        goal="Build a Flask Blog with posts, categories, and a simple SQLite database",
        test_cmd="pytest",
        description="Flask blog application with database persistence",
    ),
    Scenario(
        name="markdown-parser",
        goal="Build a Markdown Parser that converts headers, bold, italic, and links to HTML",
        test_cmd="pytest",
        description="Pure Python Markdown→HTML parser with comprehensive tests",
    ),
    Scenario(
        name="jwt-auth",
        goal="Add JWT Authentication to an existing Python API with login, refresh, and protected routes",
        test_cmd="pytest",
        description="JWT token auth: login endpoint, refresh, and middleware guard",
    ),
]


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_validate(agent: "SmartAgent", args: list[str]) -> str:
    """
    Run Phase 9 validation — demonstrate MARK completing standard engineering tasks.

    Usage:
        validate              — run all scenarios sequentially
        validate list         — list available scenarios
        validate run <name>   — run a single scenario by name
        validate help         — show this help

    Each scenario is a real engineer goal passed through the full pipeline:
    analyze → clarify → plan → code → test → debug → summarize.
    """
    if not args or args[0].lower() == "help":
        return _help()

    sub = args[0].lower()

    if sub == "list":
        return _list_scenarios()

    if sub == "run":
        if len(args) < 2:
            return "Usage: validate run <scenario-name>\nRun 'validate list' to see names."
        name = args[1].lower()
        scenario = _find_scenario(name)
        if scenario is None:
            names = ", ".join(s.name for s in _SCENARIOS)
            return f"[error] Unknown scenario {name!r}.\nAvailable: {names}"
        return _run_scenario(agent, scenario)

    # Default: run all
    return _run_all(agent)


def _list_scenarios() -> str:
    lines = ["  Phase 9 Validation Scenarios:", ""]
    for s in _SCENARIOS:
        lines.append(f"  {s.name:<20} {s.description}")
    lines.append("")
    lines.append("Run: validate run <name>  or  validate  (all)")
    return "\n".join(lines)


def _find_scenario(name: str) -> Scenario | None:
    for s in _SCENARIOS:
        if s.name == name or s.name.startswith(name):
            return s
    return None


def _run_all(agent: "SmartAgent") -> str:
    lines = [
        "",
        "  ╔══════════════════════════════════════════════════════════╗",
        "  ║          MARK  ·  Phase 9 Validation Suite              ║",
        "  ╚══════════════════════════════════════════════════════════╝",
        "",
        f"  Running {len(_SCENARIOS)} scenarios…",
        "",
    ]
    results: list[tuple[Scenario, bool, float, str]] = []

    for scenario in _SCENARIOS:
        lines.append(f"  ► {scenario.name}")
        t0 = time.monotonic()
        try:
            ok, detail = _execute_scenario(agent, scenario)
        except Exception as exc:
            ok, detail = False, str(exc)
        elapsed = time.monotonic() - t0
        results.append((scenario, ok, elapsed, detail))
        icon = "✓" if ok else "✗"
        lines.append(f"    {icon} {detail[:80]}  ({elapsed:.1f}s)")
        lines.append("")

    # Summary table
    passed = sum(1 for _, ok, _, _ in results if ok)
    total  = len(results)
    lines += [
        "  ─" * 30,
        f"  Results: {passed}/{total} scenarios passed",
        "",
    ]
    for scenario, ok, elapsed, detail in results:
        icon = "✓" if ok else "✗"
        lines.append(f"  {icon} {scenario.name:<22} {elapsed:.1f}s")
    lines.append("")

    return "\n".join(lines)


def _run_scenario(agent: "SmartAgent", scenario: Scenario) -> str:
    lines = [
        "",
        f"  Scenario : {scenario.name}",
        f"  Goal     : {scenario.goal[:72]}",
        "",
    ]
    t0 = time.monotonic()
    try:
        ok, detail = _execute_scenario(agent, scenario)
    except Exception as exc:
        ok, detail = False, str(exc)
    elapsed = time.monotonic() - t0
    icon = "✓" if ok else "✗"
    lines.append(f"  {icon} {detail}")
    lines.append(f"  Elapsed  : {elapsed:.1f}s")
    return "\n".join(lines)


def _execute_scenario(
    agent: "SmartAgent",
    scenario: Scenario,
) -> tuple[bool, str]:
    """
    Execute one scenario through the SoftwareEngineer pipeline.

    Returns ``(success, detail_string)``.
    """
    eng = getattr(agent, "software_engineer", None)
    if eng is None:
        try:
            from smartagent.engineer.software_engineer import SoftwareEngineer
            eng = SoftwareEngineer.with_agent(agent)
        except Exception as exc:
            return False, f"Could not create SoftwareEngineer: {exc}"

    try:
        report = eng.build(
            goal=scenario.goal,
            test_cmd=scenario.test_cmd,
            auto_commit=False,
            interactive=False,
            max_iterations=3,
        )
        detail = report.summary[:120] if report.summary else (
            "Completed" if report.success else "Did not fully complete"
        )
        return report.success, detail
    except Exception as exc:
        return False, f"Pipeline error: {exc}"


def _help() -> str:
    return """\
  Phase 9 Validation commands:

    validate              — run all 5 standard engineering scenarios
    validate list         — list available scenarios
    validate run <name>   — run a single scenario

  Scenarios:
    calculator-cli        Build a Calculator CLI
    rest-api              Build a FastAPI REST API
    flask-blog            Build a Flask Blog
    markdown-parser       Build a Markdown Parser
    jwt-auth              Add JWT Authentication

  Each scenario exercises the full MARK pipeline:
    analyze → clarify → plan → code → test → debug → summarize\
"""


def register(router: CommandRouter) -> None:
    """Register validate commands with *router*."""
    router.register(
        "validate", handle_validate,
        "validate — Phase 9 validation suite (5 standard engineering scenarios)",
        "CEO", 9,
    )
