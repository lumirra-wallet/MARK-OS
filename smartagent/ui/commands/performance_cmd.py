"""
performance_cmd — v2.0 Phase 12: Performance Metrics Command.

Shows per-worker timing, prompt audit, and cache stats from the most recent
engineer/CEO run.  Data is stored in ExecutionContext.metadata by the
OllamaWorkerMixin instrumentation added in v2.0.

Commands::

    mark> performance            # show last run metrics
    mark> performance cache      # show cache stats
    mark> performance clear      # clear the worker cache
"""

from __future__ import annotations

from typing import Any

from smartagent.ui.command_router import CommandRouter


def _show_last_run(agent: Any) -> str:
    """Display timing and prompt audit from the last execution context."""
    # The last context is stored in agent.executive.last_context (if available)
    ctx = None
    try:
        exec_ctrl = getattr(agent, "executive", None)
        if exec_ctrl is not None:
            ctx = getattr(exec_ctrl, "last_context", None)
    except Exception:
        pass

    if ctx is None:
        return (
            "No execution context found.\n"
            "Run 'engineer <goal>' first, then call 'performance'."
        )

    lines: list[str] = ["── MARK Performance Report ───────────────────────"]

    # --- Worker timings ---
    timings = ctx.metadata.get("worker_timings", [])
    if timings:
        try:
            from smartagent.performance.worker_timer import format_timing_table
            lines.append(format_timing_table(timings))
        except Exception as exc:
            lines.append(f"  (timing unavailable: {exc})")
    else:
        lines.append("  No worker timing data for this run.")

    lines.append("")

    # --- Prompt audits ---
    audits: dict = ctx.metadata.get("prompt_audits", {})
    if audits:
        lines.append("── Prompt Audit per Worker ───────────────────────")
        for worker_name, audit in audits.items():
            lines.append(f"  {worker_name}:")
            try:
                for line in audit.as_display_lines():
                    lines.append("  " + line)
            except Exception:
                lines.append(f"    total ≈ {getattr(audit, 'total_tokens', '?')} tokens")
        lines.append("")

    # --- Cache stats ---
    try:
        from smartagent.performance.worker_cache import get_global_cache
        cache = get_global_cache()
        lines.append("── Worker Cache ──────────────────────────────────")
        lines.append(cache.stats.as_display())
        lines.append(f"  Entries     : {len(cache)}")
    except Exception:
        pass

    # --- Complexity ---
    complexity = getattr(ctx, "complexity", None) or ctx.metadata.get("complexity")
    if complexity:
        lines.append("")
        lines.append(f"  Complexity  : {complexity}")
        lines.append(f"  Tasks       : {ctx.task_count}")
        lines.append(f"  Completed   : {ctx.completed_count}")

    lines.append("──────────────────────────────────────────────────")
    return "\n".join(lines)


def _show_cache_stats(_agent: Any) -> str:
    """Display worker cache stats."""
    try:
        from smartagent.performance.worker_cache import get_global_cache
        cache = get_global_cache()
        lines = [
            "── Worker Cache Stats ────────────────────────────",
            cache.stats.as_display(),
            f"  Entries stored : {len(cache)}",
            f"  Max capacity   : {cache._max_size}",
            "──────────────────────────────────────────────────",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Cache unavailable: {exc}"


def _clear_cache(_agent: Any) -> str:
    """Clear the worker cache."""
    try:
        from smartagent.performance.worker_cache import get_global_cache
        cache = get_global_cache()
        size = len(cache)
        cache.clear()
        return f"Worker cache cleared ({size} entries removed)."
    except Exception as exc:
        return f"Could not clear cache: {exc}"


def handle_performance(agent: Any, args: list[str]) -> str:
    """Display per-worker timing, prompt audit, and cache stats."""
    if not args:
        return _show_last_run(agent)
    sub = args[0].lower()
    if sub == "cache":
        return _show_cache_stats(agent)
    if sub == "clear":
        return _clear_cache(agent)
    return f"Unknown sub-command '{args[0]}'. Usage: performance [cache | clear]"


def register(router: CommandRouter) -> None:
    router.register(
        name="performance",
        handler=handle_performance,
        description="Show per-worker timing, prompt audit, and cache stats from the last run",
        group="Performance",
        order=81,
    )
