"""
Debug console commands — Milestone 20: Self Debugging.

Commands registered:
    debug <command>   — run a test command and autonomously fix failures
    debug-parse <cmd> — run a command and parse tracebacks only (no fixes)

Example usage::

    debug pytest tests/test_auth.py
    debug pytest tests/ -x
    debug python -m pytest --tb=short
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# debug — full run+fix loop
# ---------------------------------------------------------------------------

def handle_debug(agent: "SmartAgent", args: list[str]) -> str:
    """
    Run a test command and automatically fix any failures.

    Usage:  debug <command>
    Examples:
        debug pytest tests/test_auth.py
        debug pytest tests/ --tb=short
        debug python -m pytest -x

    MARK will:
      1. Run the command as a subprocess.
      2. Parse any Python tracebacks from the output.
      3. Pass each failing file to the Debug Worker for an AI fix.
      4. Write the corrected file and re-run.
      5. Repeat up to 5 times or until tests pass.

    Notes:
      - An active Ollama model is needed for AI-powered fixes.
      - Without a model, MARK still runs the command and reports failures.
      - Use 'debug-parse <command>' to see only the traceback analysis.
    """
    from smartagent.debug.debug_loop import DebugLoop
    from smartagent.executive.workers.debug_worker import DebugWorker

    if not args:
        return (
            "Usage: debug <command>\n"
            "Example: debug pytest tests/\n"
            "         debug pytest tests/test_auth.py -x\n\n"
            "Runs the command, parses failures, and attempts autonomous fixes.\n"
            "Use 'debug-parse <command>' to analyse tracebacks without fixing."
        )

    command = " ".join(args)

    # Build the debug worker with the agent's model manager if available
    mm = getattr(agent, "model_manager", None)
    worker = DebugWorker(model_manager=mm)

    # Build a file editor scoped to the active workspace output dir if available
    file_editor = None
    ws_mgr = getattr(agent, "workspace_manager", None)
    if ws_mgr is not None and ws_mgr.active is not None:
        try:
            from smartagent.workspace.file_editor import FileEditor
            file_editor = FileEditor(ws_mgr.active.output_path)
        except Exception:  # noqa: BLE001
            pass

    loop = DebugLoop(
        max_attempts=5,
        debug_worker=worker,
        file_editor=file_editor,
    )

    print(f"  Running: {command}", flush=True)
    try:
        result = loop.run(command)
    except Exception as exc:  # noqa: BLE001
        return f"[error] Debug loop failed: {exc}"

    lines = result.as_display_lines()

    # Show what files were written when a file editor was used
    if file_editor is not None:
        written = file_editor.written_files()
        if written:
            lines += ["", "  Files created/modified:"]
            for f in written:
                lines.append(f"    {f}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# debug-parse — parse tracebacks only, no fixes
# ---------------------------------------------------------------------------

def handle_debug_parse(agent: "SmartAgent", args: list[str]) -> str:
    """
    Run a command and analyse any tracebacks without applying fixes.

    Usage:  debug-parse <command>
    Example: debug-parse pytest tests/test_auth.py

    Useful for understanding what's failing before committing to automated fixes.
    """
    from smartagent.debug.debug_loop import DebugLoop

    if not args:
        return (
            "Usage: debug-parse <command>\n"
            "Example: debug-parse pytest tests/\n\n"
            "Runs the command once and analyses any tracebacks.\n"
            "Does not modify any files."
        )

    command = " ".join(args)
    loop = DebugLoop(max_attempts=1, debug_worker=None)

    print(f"  Running: {command}", flush=True)
    try:
        result = loop.run(command)
    except Exception as exc:  # noqa: BLE001
        return f"[error] {exc}"

    if not result.attempts:
        return "[error] No attempts recorded."

    attempt = result.attempts[0]
    lines: list[str] = []

    if attempt.passed:
        lines.append(f"✓ Command passed (exit code 0)  ({attempt.elapsed:.1f}s)")
        return "\n".join(lines)

    lines.append(f"✗ Command failed (exit code {attempt.exit_code})  ({attempt.elapsed:.1f}s)")

    if not attempt.tracebacks:
        lines.append("  No tracebacks detected.")
        lines.append("")
        lines.append("  Last output:")
        for line in attempt.output.splitlines()[-20:]:
            lines.append(f"    {line}")
        return "\n".join(lines)

    lines.append(f"  Tracebacks found: {len(attempt.tracebacks)}")
    for i, tb in enumerate(attempt.tracebacks, 1):
        lines.append("")
        lines.append(f"  [{i}] {tb.one_line()}")
        for tb_line in tb.as_display_lines():
            lines.append(f"  {tb_line}")

    lines += [
        "",
        "  Use 'debug <command>' to run with automatic fixing.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(router: CommandRouter) -> None:
    """Register debug commands with *router*."""
    router.register(
        "debug", handle_debug,
        "debug <command> — run tests and autonomously fix failures",
        "DEBUG", 0,
    )
    router.register(
        "debug-parse", handle_debug_parse,
        "debug-parse <command> — parse tracebacks without applying fixes",
        "DEBUG", 1,
    )
