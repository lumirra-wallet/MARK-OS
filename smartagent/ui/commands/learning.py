"""
Learning & Analytics commands — Milestone 14.

New console commands for MARK's autonomous learning dashboard:

    learning      — high-level learning overview
    analytics     — detailed worker/tool performance table
    reflection    — last reflection report for the current plan
    history       — table of past executions
    improvements  — prompt version history
    evaluate      — MARK's structured self-assessment
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def handle_learning(agent, args: list[str]) -> str:
    """
    Show a high-level learning dashboard.

    Usage: learning
    """
    engine = _get_reflection_engine(agent)
    if engine is None:
        return (
            "Learning analytics are not available.\n"
            "Run 'plan <goal>'  then 'run' to start building a learning history."
        )
    return engine.learning_store.analytics_summary()


def handle_analytics(agent, args: list[str]) -> str:
    """
    Show detailed worker accuracy and tool reliability tables.

    Usage: analytics
    """
    engine = _get_reflection_engine(agent)
    if engine is None:
        return _no_engine_msg()

    store = engine.learning_store
    lines = [
        store.analytics_summary(),
        "",
        store.format_worker_analytics(),
    ]

    if store.tool_stats():
        lines += ["", "Tool usage:", store.format_worker_analytics()]

    return "\n".join(lines)


def handle_reflection(agent, args: list[str]) -> str:
    """
    Show the reflection report for the most recent execution.

    Usage: reflection
    """
    ctx = _get_context(agent)
    if ctx is None:
        return "No execution context.  Run 'plan <goal>' then 'run' first."

    engine = _get_reflection_engine(agent)
    if engine is None:
        return _no_engine_msg()

    store = engine.learning_store
    records = store.execution_history()
    if not records:
        return "No reflection data yet.  Complete an execution to generate a reflection."

    last = records[-1]
    critic_summary = getattr(last, "_critic_summary", "")
    lines = [
        f"Last Reflection: '{last.goal[:60]}'",
        f"  State        : {last.state}",
        f"  Tasks        : {last.completed_count}/{last.task_count}",
        f"  Avg Conf     : {last.avg_confidence:.0%}",
        f"  Score        : {last.overall_score:.0%}",
        f"  Tool Calls   : {last.tool_calls_count}",
        f"  Knowledge    : {last.knowledge_proposals} proposals",
        f"  Memory       : {last.reflection_done and 'saved' or 'pending'}",
    ]

    # Show what_did_i_learn if available
    lines += ["", engine.what_did_i_learn()]
    return "\n".join(lines)


def handle_history(agent, args: list[str]) -> str:
    """
    List the most recent execution history.

    Usage: history [limit]
    """
    engine = _get_reflection_engine(agent)
    if engine is None:
        return _no_engine_msg()

    limit = 10
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            pass

    return engine.learning_store.format_history_table(limit=limit)


def handle_improvements(agent, args: list[str]) -> str:
    """
    Show the prompt version history for all workers.

    Usage: improvements [worker-name]
    """
    engine = _get_reflection_engine(agent)
    if engine is None:
        return _no_engine_msg()

    registry = engine.prompt_registry
    if args:
        worker_name = " ".join(args)
        return registry.format_history(worker_name)
    return registry.format_all_histories()


def handle_evaluate(agent, args: list[str]) -> str:
    """
    MARK's structured self-evaluation.

    Usage: evaluate
           evaluate worker      — which worker performs best?
           evaluate tools       — which tools fail most often?
           evaluate knowledge   — what knowledge is missing?
           evaluate learn       — what did I learn?
    """
    engine = _get_reflection_engine(agent)
    if engine is None:
        return _no_engine_msg()

    sub = args[0].lower() if args else "all"

    if sub in ("worker", "workers"):
        return engine.best_worker()
    if sub in ("tool", "tools"):
        return engine.failing_tools()
    if sub in ("knowledge", "know"):
        return engine.missing_knowledge()
    if sub in ("learn", "learned"):
        return engine.what_did_i_learn()

    # Full self-evaluation
    return engine.learning_store.self_evaluation()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_reflection_engine(agent):
    """Extract the ReflectionEngine from the agent, or None."""
    return getattr(agent, "reflection_engine", None)


def _get_context(agent):
    """Return the current ExecutionContext from the executive controller."""
    executive = getattr(agent, "executive", None)
    if executive is not None:
        return getattr(executive, "current_context", None)
    return None


def _no_engine_msg() -> str:
    return (
        "Reflection engine not available.\n"
        "Attach a ReflectionEngine to agent.reflection_engine to enable learning."
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(router) -> None:
    """Register all learning & analytics commands with the CommandRouter."""
    router.register("learning",     handle_learning,    "Show learning analytics dashboard",     "learning", 50)
    router.register("analytics",    handle_analytics,   "Show detailed performance analytics",   "learning", 50)
    router.register("reflection",   handle_reflection,  "Show last execution reflection report", "learning", 50)
    router.register("history",      handle_history,     "List past execution history",           "learning", 50)
    router.register("improvements", handle_improvements,"Show prompt version history",           "learning", 50)
    router.register("evaluate",     handle_evaluate,    "MARK self-evaluation",                  "learning", 50)
