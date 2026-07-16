"""
benchmark_cmd — v2.0 Phase 7: Benchmark Command.

Measures planning overhead and complexity classification for standard
engineering scenarios without requiring Ollama.  Timing covers the
deterministic phases: complexity detection, plan generation, and context
setup.

Commands::

    mark> benchmark              # run all 4 scenarios
    mark> benchmark hello-world  # run one scenario
    mark> benchmark list         # show available scenarios
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from smartagent.ui.command_router import CommandRouter


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkScenario:
    name: str
    goal: str
    expected_complexity: str
    expected_tasks: int   # expected task count from the planner


_SCENARIOS: list[BenchmarkScenario] = [
    BenchmarkScenario(
        name="hello-world",
        goal="Create hello.py that prints Hello World",
        expected_complexity="trivial",
        expected_tasks=2,
    ),
    BenchmarkScenario(
        name="calculator",
        goal="Write a calculator CLI that supports add, subtract, multiply, divide",
        expected_complexity="trivial",
        expected_tasks=2,
    ),
    BenchmarkScenario(
        name="rest-api",
        goal="Build a FastAPI REST API with CRUD endpoints for a Todo list",
        expected_complexity="small",
        expected_tasks=2,
    ),
    BenchmarkScenario(
        name="bug-fix",
        goal="Fix the off-by-one error in the binary search function",
        expected_complexity="trivial",
        expected_tasks=2,
    ),
]


def _find_scenario(name: str) -> BenchmarkScenario | None:
    for s in _SCENARIOS:
        if s.name == name:
            return s
    return None


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def _run_scenario(scenario: BenchmarkScenario, agent: Any) -> dict:
    """
    Time the deterministic (non-AI) phases for one scenario.

    Returns a dict with phase timings and plan metadata.
    """
    result: dict = {
        "name": scenario.name,
        "goal": scenario.goal,
        "complexity": None,
        "task_count": None,
        "planning_ms": 0.0,
        "complexity_ms": 0.0,
        "total_ms": 0.0,
        "error": None,
    }

    wall_start = time.perf_counter()

    # Phase A — Complexity classification
    t0 = time.perf_counter()
    try:
        from smartagent.performance.complexity import classify_complexity
        complexity = classify_complexity(scenario.goal)
        result["complexity"] = complexity.value
    except Exception as exc:
        result["complexity"] = "unknown"
        result["error"] = str(exc)
    result["complexity_ms"] = (time.perf_counter() - t0) * 1000

    # Phase B — Plan generation
    t0 = time.perf_counter()
    try:
        from smartagent.executive.planner import Planner
        planner = Planner()
        complexity_str = result.get("complexity") or "medium"
        tasks = planner.create_plan(scenario.goal, complexity=complexity_str)
        result["task_count"] = len(tasks)
        result["task_names"] = [t.title for t in tasks]
    except Exception as exc:
        result["task_count"] = 0
        result["error"] = str(exc)
    result["planning_ms"] = (time.perf_counter() - t0) * 1000

    result["total_ms"] = (time.perf_counter() - wall_start) * 1000
    return result


def _format_result(r: dict) -> list[str]:
    """Format one benchmark result for display."""
    status = "✓" if not r.get("error") else "✗"
    lines = [
        f"  {status}  {r['name']}",
        f"       Goal       : {r['goal'][:60]}",
        f"       Complexity : {r['complexity']}",
        f"       Tasks      : {r['task_count']} ({', '.join(r.get('task_names', []))})",
        f"       Complexity : {r['complexity_ms']:.2f} ms",
        f"       Planning   : {r['planning_ms']:.2f} ms",
        f"       Total      : {r['total_ms']:.2f} ms (deterministic phases only)",
    ]
    if r.get("error"):
        lines.append(f"       Error      : {r['error']}")
    return lines


def _run_benchmark(args: list[str], agent: Any) -> str:
    """Run benchmark scenarios and return a display string."""
    if args and args[0] == "list":
        lines = ["Available benchmark scenarios:", ""]
        for s in _SCENARIOS:
            lines.append(f"  {s.name:<20} {s.goal[:55]}")
        return "\n".join(lines)

    if args and args[0] not in ("list",):
        # Run single scenario
        scenario = _find_scenario(args[0])
        if scenario is None:
            names = ", ".join(s.name for s in _SCENARIOS)
            return f"Unknown scenario '{args[0]}'. Available: {names}"
        scenarios_to_run = [scenario]
    else:
        scenarios_to_run = _SCENARIOS

    lines = [
        "── MARK Benchmark ────────────────────────────────",
        "  (Times shown are planning overhead only — no AI calls)",
        "",
    ]

    total_wall = 0.0
    for s in scenarios_to_run:
        r = _run_scenario(s, agent)
        lines.extend(_format_result(r))
        lines.append("")
        total_wall += r["total_ms"]

    if len(scenarios_to_run) > 1:
        lines.append("──────────────────────────────────────────────────")
        lines.append(f"  Scenarios: {len(scenarios_to_run)}   Total overhead: {total_wall:.2f} ms")
        lines.append("")
        lines.append("  Note: Add 'engineer' AI call times on top of planning overhead.")
        lines.append("  Trivial tasks: 2 AI calls  Small: 2 calls  Medium: 4 calls  Large: 5+")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def handle_benchmark(args: list[str], agent: Any) -> str:
    return _run_benchmark(args, agent)


def register(router: CommandRouter) -> None:
    router.register(
        name="benchmark",
        handler=handle_benchmark,
        description="Benchmark planning overhead for standard scenarios (no AI required)",
        group="Performance",
        order=80,
    )
