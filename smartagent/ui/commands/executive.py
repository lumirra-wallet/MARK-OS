"""
Executive console commands — Phase 2 & 3 (Milestone 11).

Phase 1 commands (unchanged):
    plan <goal>     — decompose a goal into a task plan and display it
    tasks           — show the task list from the most recent plan

Phase 2 commands (new):
    workers         — list all registered worker types
    worker info <type>  — detailed info about a specific worker

Phase 3 commands (new):
    queue           — show the current task queue state
    run             — execute the current queued plan
    cancel          — cancel the running or queued plan
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Phase 1: plan, tasks
# ---------------------------------------------------------------------------

def handle_plan(agent: "SmartAgent", args: list[str]) -> str:
    """
    Decompose a goal and display the task graph.

    Usage:  plan <goal>
    Example: plan Build a REST API for task management
    """
    if not args:
        return (
            "Usage: plan <goal>\n"
            "Example: plan Build a REST API for task management\n"
            "\n"
            "Creates a task plan and displays the execution graph.\n"
            "Use 'tasks' to see task details, 'run' to execute."
        )

    goal = " ".join(args)
    try:
        context = agent.executive.plan(goal)
    except ValueError as exc:
        return f"[error] {exc}"
    except Exception as exc:
        return f"[error] Could not create plan: {exc}"

    lines = [
        f"Plan for: {goal}",
        "─" * min(60, len(goal) + 10),
        "",
    ]
    lines.extend(context.task_graph.as_display_lines())
    lines += [
        "",
        f"  {context.task_count} task(s) planned  |  state: {context.state.value}",
        "  Use 'tasks' for details  |  'run' to execute  |  'cancel' to discard",
    ]
    return "\n".join(lines)


def handle_tasks(agent: "SmartAgent", args: list[str]) -> str:
    """
    Display the task list from the most recently created plan.

    Usage:  tasks
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
        dep_str = f"  (after task {i - 1})" if task.dependencies else ""
        lines.append(
            f"  {i}. {icon}  {task.title}  [{task.task_type.value}]{dep_str}"
        )
        if task.description:
            desc = task.description[:72] + "…" if len(task.description) > 72 else task.description
            lines.append(f"       {desc}")
        if task.result:
            result_preview = task.result[:80] + "…" if len(task.result) > 80 else task.result
            lines.append(f"       → {result_preview}")
        if task.error:
            lines.append(f"       ✗ {task.error}")

    lines.append("")
    lines.append(f"  Plan id: {ctx.plan_id[:8]}…")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 2: workers, worker info
# ---------------------------------------------------------------------------

def handle_workers(agent: "SmartAgent", args: list[str]) -> str:
    """
    List all registered worker types.

    Usage:  workers

    Shows the worker name, task types it handles, and implementation phase.
    """
    try:
        rows = agent.executive.worker_registry.list_workers()
    except Exception as exc:
        return f"[error] Could not list workers: {exc}"

    if not rows:
        return "No workers are registered."

    unique = agent.executive.worker_registry.unique_worker_count()
    lines = [
        f"Workers ({unique} registered)",
        "",
    ]

    for row in rows:
        phase_badge = " [AI]" if row.get("phase") == "ollama" else " [stub]"
        lines.append(f"  {row['name']}{phase_badge}")
        lines.append(f"    Task type : {row['task_type']}")
        lines.append(f"    Class     : {row['worker']}")
        lines.append(f"    {row.get('description', '—')}")
        lines.append("")

    lines.append(
        "  [stub] = Phase 2 stub (returns placeholder output)\n"
        "  [AI]   = Phase 4 (connected to Ollama)"
    )
    return "\n".join(lines)


def handle_worker(agent: "SmartAgent", args: list[str]) -> str:
    """
    Worker subcommands.

        worker info <type>  — detailed info about a worker
        worker list         — alias for 'workers'
    """
    sub = args[0].lower() if args else ""

    if sub == "info":
        return _handle_worker_info(agent, args[1:])
    if sub == "list":
        return handle_workers(agent, [])

    return (
        "Worker subcommands:\n"
        "  worker info <type>   — info about a worker (e.g. worker info research)\n"
        "  worker list          — list all workers"
    )


def _handle_worker_info(agent: "SmartAgent", args: list[str]) -> str:
    """Detailed info about the worker registered for *task_type*."""
    if not args:
        return (
            "Usage: worker info <task-type>\n"
            "Example: worker info research\n"
            "Available types: research, planning, design, coding, "
            "testing, review, documentation, report, analysis, generic"
        )

    type_key = args[0].lower()
    reg = agent.executive.worker_registry
    worker_class = reg.get(type_key)

    if worker_class is None:
        return (
            f"No worker registered for task type {type_key!r}.\n"
            "Use 'workers' to see all registered workers."
        )

    try:
        w = worker_class()
        lines = [
            f"Worker: {w.name}",
            "",
            f"  Class       : {worker_class.__name__}",
            f"  Task types  : {', '.join(t.value for t in w.task_types)}",
            f"  Phase       : {w.phase}",
            f"  Description : {w.description}",
        ]
        if w.phase == "stub":
            lines.append(
                "\n  This worker is a Phase 2 stub — it returns placeholder output.\n"
                "  Phase 4 will connect it to Ollama with a specialist system prompt."
            )
    except Exception as exc:
        lines = [f"[error] Could not inspect worker: {exc}"]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 3: queue, run, cancel
# ---------------------------------------------------------------------------

def handle_queue(agent: "SmartAgent", args: list[str]) -> str:
    """
    Show the current task queue state.

    Usage:  queue

    Displays which tasks are waiting to run, which have run, and the
    overall execution state of the current plan.
    """
    ctx = agent.executive.current_context
    if ctx is None:
        return (
            "No plan is active.\n"
            "Use 'plan <goal>' to create one, then 'run' to execute."
        )

    tasks = ctx.task_graph.all_tasks()
    queued = ctx.task_queue.all_tasks()

    status_counts: dict[str, int] = {}
    for task in tasks:
        s = task.status.value
        status_counts[s] = status_counts.get(s, 0) + 1

    lines = [
        f"Queue — {ctx.goal!r}",
        f"  Execution state : {ctx.state.value}",
        f"  Queue depth     : {ctx.task_queue.size()} task(s) waiting",
        f"  Total tasks     : {ctx.task_count}",
        "",
        "  Status breakdown:",
    ]

    status_order = ["ready", "running", "pending", "completed", "blocked", "failed"]
    icons = {
        "ready": "◎", "running": "◉", "pending": "○",
        "completed": "✓", "blocked": "✗", "failed": "✗",
    }
    for s in status_order:
        count = status_counts.get(s, 0)
        if count > 0 or s in ("completed", "failed"):
            lines.append(f"    {icons.get(s, '?')}  {s:12s} {count}")

    if queued:
        lines.append("")
        lines.append("  Next up:")
        for i, task in enumerate(queued[:5], start=1):
            lines.append(f"    {i}. {task.title}  [{task.task_type.value}]")
        if len(queued) > 5:
            lines.append(f"    … and {len(queued) - 5} more")

    lines.append("")
    if ctx.state.value in ("ready", "planning"):
        lines.append("  Run with: run")
    elif ctx.state.value == "running":
        lines.append("  Execution in progress.  Cancel with: cancel")
    elif ctx.state.is_terminal:
        lines.append("  Execution finished.  Start a new plan with: plan <goal>")

    return "\n".join(lines)


def handle_run(agent: "SmartAgent", args: list[str]) -> str:
    """
    Execute the current plan.

    Usage:  run

    Runs all tasks in the plan in dependency order using the registered
    worker agents.  Prints a summary when complete.
    """
    ctx = agent.executive.current_context
    if ctx is None:
        return (
            "No plan to run.\n"
            "Use 'plan <goal>' first, then 'run'.\n"
            "Example: plan Build a calculator"
        )

    if ctx.state.is_terminal:
        state = ctx.state.value
        return (
            f"The current plan already finished (state: {state}).\n"
            f"Use 'plan <goal>' to start a new one."
        )

    try:
        result_ctx = agent.executive.run()
    except RuntimeError as exc:
        return f"[error] {exc}"
    except Exception as exc:
        return f"[error] Execution failed: {exc}"

    # Build result summary.
    all_tasks = result_ctx.task_graph.all_tasks()
    state = result_ctx.state.value

    lines = [
        f"Execution {'complete' if state == 'completed' else state}",
        f"  Goal      : {result_ctx.goal}",
        f"  State     : {state}",
        f"  Tasks     : {result_ctx.completed_count}/{result_ctx.task_count} completed",
        "",
        "  Results:",
    ]

    for i, task in enumerate(all_tasks, start=1):
        icon = "✓" if task.status.value == "completed" else "✗"
        lines.append(f"  {i}. {icon}  {task.title}")
        if task.result:
            preview = task.result.split("\n")[0][:70]
            lines.append(f"       {preview}")
        if task.error:
            lines.append(f"       ✗ {task.error}")

    if result_ctx.has_failures:
        lines.append("\n  Some tasks failed.  Use 'tasks' for details.")
    else:
        lines.append(
            "\n  All tasks completed successfully.  "
            "Use 'tasks' for full output."
        )

    return "\n".join(lines)


def handle_cancel(agent: "SmartAgent", args: list[str]) -> str:
    """
    Cancel the current plan.

    Usage:  cancel

    Marks all pending/ready tasks as blocked and sets the plan state
    to CANCELLED.  A new plan can be created with 'plan <goal>'.
    """
    ctx = agent.executive.current_context
    if ctx is None:
        return "No plan is active.  Nothing to cancel."

    if ctx.state.is_terminal:
        return (
            f"The plan is already in a final state ({ctx.state.value}).  "
            "Use 'plan <goal>' to start a new one."
        )

    cancelled = agent.executive.cancel()
    if not cancelled:
        return "Could not cancel the current plan."

    return (
        f"Plan cancelled: {ctx.goal!r}\n"
        f"  {ctx.task_count} task(s) marked as blocked.\n"
        "Use 'plan <goal>' to start a new plan."
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(router: CommandRouter) -> None:
    """Register all executive commands with *router*."""
    # Phase 1
    router.register("plan",   handle_plan,    "plan <goal> — decompose a goal into a task plan", "EXECUTIVE", 0)
    router.register("tasks",  handle_tasks,   "show tasks from the current plan",                 "EXECUTIVE", 1)
    # Phase 2
    router.register("workers", handle_workers, "list all registered worker agents",               "EXECUTIVE", 2)
    router.register("worker",  handle_worker,  "worker info <type> — worker details",             "EXECUTIVE", 3)
    # Phase 3
    router.register("queue",  handle_queue,   "show the current task queue state",                "EXECUTIVE", 4)
    router.register("run",    handle_run,     "execute the current plan",                         "EXECUTIVE", 5)
    router.register("cancel", handle_cancel,  "cancel the current plan",                          "EXECUTIVE", 6)
