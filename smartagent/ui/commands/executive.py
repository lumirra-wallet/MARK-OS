"""
Executive console commands — Phase 1 (Milestone 11).

Commands registered:
    plan <goal>     — decompose a goal into a task plan and display it
    tasks           — show the task list from the most recent plan

Phase 2 will add:
    workers         — list registered worker types
    worker info <type>

Phase 3 will add:
    queue           — show the current task queue
    run             — execute the current queued plan
    cancel          — cancel execution
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# plan — decompose a goal and display the task graph
# ---------------------------------------------------------------------------


def handle_plan(agent: "SmartAgent", args: list[str]) -> str:
    """
    Decompose a goal into a plan and display the task graph.

    Usage:  plan <goal>

    Example:
        mark> plan Build a calculator

    Creates a plan and stores it on ``agent.executive`` so ``tasks`` can
    display it later.  Does NOT execute the plan — use ``run`` (Phase 3)
    for that.
    """
    if not args:
        return (
            "Usage: plan <goal>\n"
            "Example: plan Build a REST API for task management\n"
            "\n"
            "Creates a task plan for the goal and displays the execution graph.\n"
            "Use 'tasks' to see the full task list after planning."
        )

    goal = " ".join(args)

    try:
        context = agent.executive.plan(goal)
    except ValueError as exc:
        return f"[error] {exc}"
    except Exception as exc:
        return f"[error] Could not create plan: {exc}"

    # Build the display
    lines = [
        f"Plan for: {goal}",
        f"{'─' * min(60, len(goal) + 10)}",
        "",
    ]

    display_lines = context.task_graph.as_display_lines()
    lines.extend(display_lines)

    lines.extend([
        "",
        f"  {context.task_count} task(s) planned.",
        "  Use 'tasks' to see details.",
        # Phase 3 note: "  Use 'run' to execute."  — add when Phase 3 ships
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# tasks — show the task list from the current plan
# ---------------------------------------------------------------------------


def handle_tasks(agent: "SmartAgent", args: list[str]) -> str:
    """
    Display the tasks from the most recently created plan.

    Usage:  tasks

    Shows each task with its status, type, and description.
    """
    ctx = agent.executive.current_context
    if ctx is None:
        return (
            "No plan has been created yet.\n"
            "Use 'plan <goal>' to create one.\n"
            "Example: plan Build a calculator"
        )

    tasks = ctx.task_graph.all_tasks()
    if not tasks:
        return "The current plan has no tasks."

    status_icons = {
        "pending":   "○",
        "ready":     "◎",
        "running":   "◉",
        "blocked":   "✗",
        "completed": "✓",
        "failed":    "✗",
    }

    lines = [
        f"Tasks — {ctx.goal!r}",
        f"  State: {ctx.state.value}  |  "
        f"Completed: {ctx.completed_count}/{ctx.task_count}",
        "",
    ]

    for i, task in enumerate(tasks, start=1):
        icon = status_icons.get(task.status.value, "?")
        dep_str = ""
        if task.dependencies:
            dep_str = f"  (after task {i - 1})"
        lines.append(f"  {i}. {icon}  {task.title}  [{task.task_type.value}]{dep_str}")
        if task.description:
            # Truncate long descriptions for console readability.
            desc = task.description
            if len(desc) > 72:
                desc = desc[:69] + "…"
            lines.append(f"       {desc}")
        if task.result:
            lines.append(f"       → {task.result}")
        if task.error:
            lines.append(f"       ✗ {task.error}")

    lines.append("")
    lines.append(f"  Plan id: {ctx.plan_id[:8]}…")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(router: CommandRouter) -> None:
    """Register executive commands with *router*."""
    router.register("plan",  handle_plan,  "plan <goal> — decompose a goal into a task plan", "EXECUTIVE", 0)
    router.register("tasks", handle_tasks, "show tasks from the current plan",                 "EXECUTIVE", 1)
