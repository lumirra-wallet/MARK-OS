"""
AgentLoop — the core execution engine that makes MARK autonomous.

Architecture:

    User goal
        ↓
    AgentLoop.run()
        ↓
    ModelManager.chat_with_tools(messages, TOOL_DEFINITIONS)
        ↓  (if tool_calls in response)
    execute_tool(name, args, workspace)  ← real file / terminal / git ops
        ↓
    append tool result to messages
        ↓
    repeat up to MAX_TURNS
        ↓  (when no more tool_calls)
    stream final text response to event_bus
        ↓
    AgentLoopResult

This loop runs synchronously (designed to be called from asyncio.to_thread).
Every tool execution publishes REASONING_STAGE / ACTIVITY_FEED_ENTRY events for
the Timeline/Activity Feed (technical detail, not chat). When MARK is acting
directly (``allow_direct_reply=True``, the default), the final reply streams
to chat (STREAMING_TOKEN) as MARK's own words. When this loop is dispatched as
a delegated specialist worker (see ``worker_roles.py`` and ``DevPipeline``),
callers pass ``allow_direct_reply=False`` — the final reply is only returned
in ``AgentLoopResult.final_summary`` for MARK's own synthesis, never streamed
directly, so the worker never talks to the user itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from smartagent.engineer.agent_tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    requires_approval,
)
from smartagent.logs.logger import get_logger
from smartagent.server.events import ServerEvents

logger = get_logger(__name__)

MAX_TURNS = 20  # hard limit on tool-call rounds

# ── Stage and activity-type maps ──────────────────────────────────────────────

_TOOL_STAGE: dict[str, str] = {
    "read_file":        "analyzing",
    "list_directory":   "analyzing",
    "search_workspace": "analyzing",
    "git_status":       "analyzing",
    "git_diff":         "analyzing",
    "write_file":       "writing",
    "rename_file":      "writing",
    "delete_file":      "writing",
    "run_terminal":     "running",
    "git_commit":       "committing",
}

_TOOL_ACTIVITY_TYPE: dict[str, str] = {
    "read_file":        "read",
    "list_directory":   "analyze",
    "search_workspace": "search",
    "write_file":       "write",
    "rename_file":      "rename",
    "delete_file":      "delete",
    "run_terminal":     "run",
    "git_status":       "git",
    "git_diff":         "git",
    "git_commit":       "commit",
}


# ────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentLoopResult:
    """Return value from :func:`run_agent_loop`."""

    goal:           str
    success:        bool       = False
    files_created:  list[str]  = field(default_factory=list)
    files_modified: list[str]  = field(default_factory=list)
    total_elapsed:  float      = 0.0
    stop_reason:    str        = "done"
    final_summary:  str        = ""
    # Duck-type compatibility with SoftwareEngineerReport
    iterations:     list       = field(default_factory=list)
    summary:        str        = ""


# ────────────────────────────────────────────────────────────────────────────
# System prompt
# ────────────────────────────────────────────────────────────────────────────

_AGENT_SYSTEM = """\
You are MARK — the executive director of an AI engineering team, built into
this developer dashboard. MARK is not a coding assistant; it's an operating
system that plans, delegates, and supervises specialist engineering work.
For a focused task like this one, you act directly using your own tools
rather than delegating to a separate specialist — but you are still MARK,
the executive, not "an AI coding assistant."

IDENTITY (never break these rules):
- Your name is MARK. You are not ChatGPT, not Claude, not Gemini, not any other product.
- You were built into this dashboard. You have no other creator to disclose.
- If asked "who made you", "who are you", "what are you" or any identity question:
  answer as MARK only. Example: "I'm MARK — I plan, delegate, and supervise
  engineering work, and handle focused tasks like this one directly."
- NEVER say "I was created by OpenAI" or name any AI provider. If pressed, say
  "I'm MARK — that's all I can tell you about myself."

TOOLS AVAILABLE:
• read_file(path)               — read any file
• write_file(path, content)     — create or overwrite a file
• list_directory(path, depth)   — explore project structure
• search_workspace(query)       — grep through files
• run_terminal(command)         — run pytest, npm, pip, cargo, git, etc.
• git_status()                  — see current git status
• git_diff()                    — see current changes
• git_commit(message)           — stage all and commit
• rename_file(src, dst)         — rename or move a file
• delete_file(path)             — delete a file (requires prior approval)

RULES — follow these exactly:
1. NEVER say "I cannot access your files" or "I don't have direct access" — you DO.
2. NEVER produce code in your reply without also writing it to disk with write_file.
3. ALWAYS use list_directory first to understand the project before acting.
4. ALWAYS use write_file to save code — showing code without writing it is wrong.
5. After writing files, run tests with run_terminal if a test suite is present.
6. After completing work, use git_commit to checkpoint the result.
7. Your final reply (no tool_calls) should be a plain-text summary of what was done.

EXAMPLE CORRECT WORKFLOW for "create hello.py":
  → list_directory(".")
  → write_file("hello.py", "print('Hello, World!')\n")
  → run_terminal("python hello.py")
  → git_commit("Add hello.py")
  → "Created hello.py with a Hello World program. Tests passed."

EXAMPLE CORRECT WORKFLOW for "who are you":
  → (no tools needed)
  → "I'm MARK. I plan engineering work, delegate it, and supervise the
     result — for a task this size I'm handling it directly myself."
"""


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _activity_text(name: str, args: dict[str, Any], result: str) -> str:
    """One-line description of a completed tool call for the activity feed."""
    if name == "write_file":
        chars = len(args.get("content", ""))
        return f"Wrote {args.get('path','?')} ({chars:,} chars)"
    if name == "read_file":
        return f"Read {args.get('path','?')}"
    if name == "list_directory":
        d = args.get('path', '.') or '.'
        lines = len(result.splitlines())
        return f"Listed {d} ({lines} entries)"
    if name == "run_terminal":
        cmd = args.get('command', '')[:60]
        first = result.strip().splitlines()[0][:80] if result.strip() else ''
        return f"Ran: {cmd}" + (f" → {first}" if first else "")
    if name == "git_commit":
        return f"Committed: {args.get('message','')[:60]}"
    if name == "git_status":
        return "Checked git status"
    if name == "git_diff":
        return "Checked git diff"
    if name == "search_workspace":
        q = args.get('query','')[:40]
        hits = len([l for l in result.splitlines() if l.strip()])
        return f"Searched '{q}' ({hits} hits)"
    if name == "rename_file":
        return f"Renamed {args.get('src','?')} → {args.get('dst','?')}"
    if name == "delete_file":
        return f"Deleted {args.get('path','?')}"
    keys = list(args.keys())[:2]
    return f"{name}({', '.join(keys)})"


def _format_args_display(name: str, args: dict[str, Any]) -> str:
    """Short human-readable representation of a tool call for the dashboard."""
    if name == "write_file":
        content_preview = str(args.get("content", ""))[:40].replace("\n", "↵")
        return f'write_file("{args.get("path", "?")}",  {len(args.get("content",""))} chars)'
    if name == "run_terminal":
        cmd = str(args.get("command", ""))[:60]
        return f"run_terminal({cmd!r})"
    if name == "read_file":
        return f'read_file("{args.get("path", "?")}")'
    if name == "git_commit":
        return f'git_commit("{args.get("message","")[:50]}")'
    parts = [f"{k}={v!r}" for k, v in list(args.items())[:2]]
    return f"{name}({', '.join(parts)})"


def _chunk_text(text: str, size: int = 120) -> list[str]:
    """Split text into chunks for token-by-token streaming."""
    return [text[i:i + size] for i in range(0, len(text), size)] if text else []


# ────────────────────────────────────────────────────────────────────────────
# Main loop
# ────────────────────────────────────────────────────────────────────────────

def run_agent_loop(
    goal: str,
    model_manager: Any,
    event_bus: Any,
    workspace_path: str,
    system_prompt: str | None = None,
    max_turns: int = MAX_TURNS,
    allowed_paths: list[str] | None = None,
    allow_direct_reply: bool = True,
) -> AgentLoopResult:
    """
    Run the agentic tool-calling loop for *goal*.

    Must be called from a worker thread (``asyncio.to_thread``) because all
    I/O (LLM calls, tool execution, event publishing) is blocking.

    Args:
        goal:           Natural-language task from the user.
        model_manager:  Must have ``chat_with_tools(messages, tools)`` method.
        event_bus:      Used to publish ``STREAMING_TOKEN`` events.
        workspace_path: Absolute path to the active workspace.
        system_prompt:  Override the default MARK agent prompt.
        max_turns:      Hard cap on tool-call rounds.
        allowed_paths:  When non-empty, restricts write/rename/delete calls to
            these paths for the duration of this loop (least-privilege
            per-task scoping — see ``DevPipeline``). ``None`` is unrestricted.
        allow_direct_reply: When ``True`` (default), this loop's own final
            reply streams straight to chat — correct when this loop *is*
            MARK acting directly. Set ``False`` when this loop is a
            delegated specialist worker (see ``worker_roles.py``): its final
            reply is still captured in ``AgentLoopResult.final_summary`` for
            MARK's own synthesis, but never streamed to chat itself — a
            worker reports to MARK, it doesn't talk to the user.

    Returns:
        :class:`AgentLoopResult`
    """
    t0 = time.monotonic()
    result = AgentLoopResult(goal=goal)

    system = system_prompt or _AGENT_SYSTEM
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": goal},
    ]

    files_created:  list[str] = []
    files_modified: list[str] = []

    def _publish(text: str) -> None:
        try:
            event_bus.publish(ServerEvents.STREAMING_TOKEN, text=text, source="mark")
        except Exception as exc:
            logger.warning("AgentLoop: event_bus.publish failed: %s", exc)

    logger.info("AgentLoop: starting  goal=%r  workspace=%r", goal[:60], workspace_path)

    # Signal the dashboard that analysis is beginning
    try:
        event_bus.publish(ServerEvents.REASONING_STAGE, stage="analyzing", tool=None)
    except Exception:
        pass

    for turn in range(max_turns):
        logger.info("AgentLoop: turn %d/%d", turn + 1, max_turns)

        # ── Call LLM with tool definitions ────────────────────────────────
        try:
            response_msg = model_manager.chat_with_tools(messages, tools=TOOL_DEFINITIONS)
        except Exception as exc:
            logger.warning("AgentLoop: chat_with_tools failed: %s", exc)
            if allow_direct_reply:
                _publish(f"\n[MARK] LLM call failed: {exc}\n")
            result.stop_reason = f"llm_error: {exc}"
            break

        tool_calls = getattr(response_msg, "tool_calls", None) or []
        content    = getattr(response_msg, "content", None) or ""

        if not tool_calls:
            # ── LLM is done — stream final text ───────────────────────────
            logger.info("AgentLoop: no more tool calls — streaming final response")
            if content and allow_direct_reply:
                for chunk in _chunk_text(content):
                    _publish(chunk)
            result.stop_reason = "done"
            result.final_summary = content[:300] if content else "Task complete."
            result.summary       = result.final_summary
            result.success       = True
            break

        # ── Append assistant turn with tool_calls ─────────────────────────
        assistant_msg: dict[str, Any] = {
            "role":       "assistant",
            "content":    content,
            "tool_calls": [],
        }
        for tc in tool_calls:
            assistant_msg["tool_calls"].append({
                "id":       tc.id,
                "type":     "function",
                "function": {
                    "name":      tc.function.name,
                    "arguments": tc.function.arguments,
                },
            })
        messages.append(assistant_msg)

        # ── Execute each tool call ─────────────────────────────────────────
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            display = _format_args_display(name, args)
            logger.info("AgentLoop: tool call  %s", display)

            # Emit reasoning stage for this tool (Timeline detail — not chat)
            stage = _TOOL_STAGE.get(name, "running")
            try:
                event_bus.publish(ServerEvents.REASONING_STAGE, stage=stage, tool=name)
            except Exception:
                pass

            if requires_approval(name):
                tool_result = (
                    f"[APPROVAL REQUIRED] '{name}' is a destructive operation "
                    f"that requires explicit user approval. Ask the user to confirm."
                )
                logger.info("AgentLoop: approval required for %r", name)
            else:
                tool_result = execute_tool(name, args, workspace_path, allowed_paths=allowed_paths)

                # Track written files
                if name == "write_file" and "path" in args:
                    p = args["path"]
                    if p not in files_created and p not in files_modified:
                        files_created.append(p)
                elif name == "rename_file":
                    dst = args.get("dst") or args.get("path", "")
                    if dst and dst not in files_modified:
                        files_modified.append(dst)

            # Truncate very long results before adding to context
            MAX_RESULT = 6_000
            if len(tool_result) > MAX_RESULT:
                half = MAX_RESULT // 2
                tool_result = (
                    tool_result[:half]
                    + f"\n… [truncated {len(tool_result) - MAX_RESULT} chars] …\n"
                    + tool_result[-half:]
                )

            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      tool_result,
            })

            # Emit activity feed entry
            activity_type = _TOOL_ACTIVITY_TYPE.get(name, "run")
            activity_txt  = _activity_text(name, args, tool_result)
            is_success    = not any(
                w in tool_result.lower()
                for w in ("error:", "not found", "permission denied", "traceback")
            )
            try:
                event_bus.publish(
                    ServerEvents.ACTIVITY_FEED_ENTRY,
                    type=activity_type,
                    text=activity_txt,
                    detail=tool_result.split("\n")[0][:120] if tool_result else "",
                    success=is_success,
                )
            except Exception:
                pass

    else:
        # Hit max_turns without finishing
        logger.warning("AgentLoop: reached max_turns=%d without finishing", max_turns)
        result.stop_reason   = "max_turns"
        result.final_summary = f"Reached the {max_turns}-turn limit."
        result.success       = bool(files_created)

    # Signal completion stage
    try:
        event_bus.publish(ServerEvents.REASONING_STAGE, stage="done", tool=None)
    except Exception:
        pass

    result.total_elapsed  = time.monotonic() - t0
    result.files_created  = files_created
    result.files_modified = files_modified

    if not result.final_summary:
        n = len(files_created)
        result.final_summary = (
            f"Done in {result.total_elapsed:.1f}s — {n} file{'s' if n != 1 else ''} written."
            if n else f"Task complete in {result.total_elapsed:.1f}s."
        )
        result.summary = result.final_summary

    logger.info(
        "AgentLoop: complete  success=%s  files=%d  elapsed=%.1fs  stop=%r",
        result.success, len(files_created), result.total_elapsed, result.stop_reason,
    )
    return result
