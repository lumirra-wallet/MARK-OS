"""
WorkerToolMixin — Milestone 12: Tool Intelligence & Autonomous Execution.

Adds a ReAct-style (Reason + Act) tool-calling loop to any worker that
already inherits from ``OllamaWorkerMixin``.

Execution flow per task::

    Think (LLM response)
        ↓
    Parse for TOOL_CALL marker
        ↓ (if found)
    Validate against _allowed_tools allowlist
        ↓
    Execute via tool_engine (from context.metadata)
        ↓
    Append observation to message thread
        ↓
    Continue reasoning  (loop up to _max_tool_rounds)
        ↓
    Produce final answer (no TOOL_CALL in response)

When ``tool_engine`` is not injected in ``context.metadata``, the mixin
falls back to ``_execute_with_ollama()`` from the parent class so all
existing tests continue to pass without modification.

Tool call format (LLM must use this exact string pattern)::

    TOOL_CALL: {"tool": "file_read", "args": {"path": "/workspace/main.py"}}

Tool results are recorded in ``context.metadata["tool_calls"]`` as a list
of dicts with keys: ``task_id``, ``tool``, ``args``, ``result``,
``duration``, ``success``.

Architecture rules:
  - Workers NEVER call tools directly.  Always via ``tool_engine.run()``.
  - Workers MUST declare ``_allowed_tools`` — an empty tuple means no tools.
  - The mixin only executes tools that appear in ``_allowed_tools``.
    Requests for unlisted tools are declined and fed back as an observation.

Usage::

    class CodingWorker(WorkerToolMixin, OllamaWorkerMixin, BaseWorker):
        _allowed_tools = ("file_read", "file_write", "directory_list")
        _max_tool_rounds = 5

        def execute(self, task, context):
            return self._execute_with_tools(task, context)
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.executive.task import Task
    from smartagent.tools.base_tool import ToolContext
    from smartagent.tools.tool_engine import ToolEngine

logger = get_logger(__name__)

# Maximum ReAct loop iterations (think + tool per round)
_DEFAULT_MAX_TOOL_ROUNDS = 5
# Characters of a tool result to include in the observation message
_MAX_OBSERVATION_CHARS = 2000


class WorkerToolMixin:
    """
    Mixin that equips any ``OllamaWorkerMixin`` worker with ReAct tool-calling.

    Class-level attributes (set by subclasses):

    ``_allowed_tools`` — tuple of tool IDs this worker is permitted to invoke.
        Empty tuple means the worker runs without tool access (same as plain
        ``OllamaWorkerMixin`` execution).

    ``_max_tool_rounds`` — hard cap on think+act loop iterations.  Prevents
        infinite loops if the LLM keeps emitting tool calls.  Default: 5.
    """

    _allowed_tools: tuple[str, ...] = ()
    _max_tool_rounds: int = _DEFAULT_MAX_TOOL_ROUNDS

    # ------------------------------------------------------------------
    # Service accessors (rely on OllamaWorkerMixin helpers being in MRO)
    # ------------------------------------------------------------------

    def _get_tool_engine(self, context: "ExecutionContext") -> "ToolEngine | None":
        return context.metadata.get("tool_engine")

    def _build_tool_context(self, context: "ExecutionContext") -> "ToolContext | None":
        """
        Construct a ``ToolContext`` from what is available in the metadata.

        Returns ``None`` if the required ``Settings`` object is not present —
        most built-in tools tolerate a missing settings but it is safer to
        skip tool calls than to inject garbage.
        """
        from smartagent.tools.base_tool import ToolContext

        settings = context.metadata.get("settings")
        if settings is None:
            # Construct a lightweight stand-in so tools that don't need
            # settings (e.g. date_time, uuid) still work.
            try:
                from smartagent.config.settings import Settings
                settings = Settings()
            except Exception:  # noqa: BLE001
                return None

        workspace = getattr(settings, "workspace_path", ".") or "."
        events = context.metadata.get("event_bus")
        return ToolContext(settings=settings, workspace_path=workspace, events=events)

    # ------------------------------------------------------------------
    # Tool description (for system prompt injection)
    # ------------------------------------------------------------------

    def _describe_allowed_tools(self, context: "ExecutionContext") -> str:
        """
        Return a human-readable list of this worker's allowed tools with
        one-line descriptions.  Used to inform the LLM about available tools.
        """
        te = self._get_tool_engine(context)
        if te is None or not self._allowed_tools:
            return ""

        lines: list[str] = []
        for tool_id in self._allowed_tools:
            tool = te.registry.find(tool_id)
            if tool is not None:
                lines.append(f"  - {tool_id}: {tool.description}")
        return "\n".join(lines)

    def _tool_system_addendum(self, context: "ExecutionContext") -> str:
        """
        Build the tool-use addendum to append to the system prompt.

        Only appended when a tool_engine is available AND the worker has
        at least one registered allowed tool.
        """
        tool_desc = self._describe_allowed_tools(context)
        if not tool_desc:
            return ""
        return f"""

---
## Tool Access

You have access to the following tools:
{tool_desc}

To use a tool, output EXACTLY this pattern on its own line:
  TOOL_CALL: {{"tool": "<tool_id>", "args": {{"<param>": "<value>"}}}}

Rules:
- Use tools only when they provide information you genuinely cannot infer.
- You may call at most one tool per response.
- After receiving a TOOL_RESULT, continue your analysis and produce the\
 final answer.
- If you do not need a tool, do NOT emit a TOOL_CALL line.
- Only use the tools listed above.\
"""

    # ------------------------------------------------------------------
    # Tool call parsing
    # ------------------------------------------------------------------

    def _parse_tool_call(self, text: str) -> dict | None:
        """
        Extract the first ``TOOL_CALL:`` JSON object from *text*.

        Handles nested JSON by counting brace depth.  Returns a dict with
        keys ``"tool"`` and ``"args"``, or ``None`` if no valid call is found.
        """
        idx = text.find("TOOL_CALL:")
        if idx == -1:
            return None

        start = text.find("{", idx)
        if start == -1:
            return None

        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payload = json.loads(text[start : i + 1])
                        if isinstance(payload, dict) and "tool" in payload:
                            return payload
                    except json.JSONDecodeError:
                        pass
                    return None
        return None

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(
        self,
        call: dict,
        task: "Task",
        context: "ExecutionContext",
    ) -> str:
        """
        Validate the tool call allowlist and execute via ``tool_engine.run()``.

        Returns an observation string (success or failure message) that is
        appended to the message thread so the LLM can incorporate the result.
        Records the call in ``context.metadata["tool_calls"]``.
        """
        tool_id: str = call.get("tool", "")
        args: dict = call.get("args", {}) or {}

        # Allowlist check
        if tool_id not in self._allowed_tools:
            msg = (
                f"Tool '{tool_id}' is not in your allowed tools list for this worker. "
                f"Allowed: {', '.join(self._allowed_tools) or 'none'}."
            )
            logger.info(
                "WorkerToolMixin [%s]: blocked tool '%s' (not in allowlist)",
                getattr(self, "name", "worker"), tool_id,
            )
            self._record_tool_call(task, context, tool_id, args, msg, 0.0, False)
            return f"TOOL_DENIED: {msg}"

        te = self._get_tool_engine(context)
        if te is None:
            msg = "Tool engine not available in this execution context."
            self._record_tool_call(task, context, tool_id, args, msg, 0.0, False)
            return f"TOOL_ERROR: {msg}"

        tool_ctx = self._build_tool_context(context)
        if tool_ctx is None:
            msg = "Could not construct a ToolContext — settings missing."
            self._record_tool_call(task, context, tool_id, args, msg, 0.0, False)
            return f"TOOL_ERROR: {msg}"

        self._print_tool_start(tool_id)
        t0 = time.monotonic()
        result = te.run(tool_id, tool_ctx, **args)
        elapsed = time.monotonic() - t0

        observation: str
        if result.success:
            raw = str(result.data if result.data is not None else result.message)
            observation = raw[:_MAX_OBSERVATION_CHARS]
            if len(raw) > _MAX_OBSERVATION_CHARS:
                observation += "\n…[truncated]"
            self._print_tool_result(tool_id, elapsed, success=True)
        else:
            observation = f"Tool failed: {result.message}"
            self._print_tool_result(tool_id, elapsed, success=False)

        self._record_tool_call(
            task, context, tool_id, args, observation, elapsed, result.success
        )
        return observation

    # ------------------------------------------------------------------
    # Context tracking
    # ------------------------------------------------------------------

    def _record_tool_call(
        self,
        task: "Task",
        context: "ExecutionContext",
        tool: str,
        args: dict,
        result: str,
        duration: float,
        success: bool,
    ) -> None:
        """Append a tool-call record to ``context.metadata["tool_calls"]``."""
        if "tool_calls" not in context.metadata:
            context.metadata["tool_calls"] = []
        context.metadata["tool_calls"].append(
            {
                "task_id": task.id,
                "tool": tool,
                "args": args,
                "result": result,
                "duration": round(duration, 4),
                "success": success,
            }
        )

    # ------------------------------------------------------------------
    # ReAct loop
    # ------------------------------------------------------------------

    def _execute_with_tools(
        self,
        task: "Task",
        context: "ExecutionContext",
    ) -> str:
        """
        Phase 12 ReAct loop: Think → Tool? → Execute → Observe → Continue.

        Falls back to ``_execute_with_ollama()`` from ``OllamaWorkerMixin``
        when no ``tool_engine`` is available in ``context.metadata``, so all
        existing tests continue to pass without any changes.

        Returns a plain ``str`` — same contract as ``_execute_with_ollama()``.
        """
        te = self._get_tool_engine(context)

        # No tool_engine → standard path (all existing tests stay green)
        if te is None or not self._allowed_tools:
            return self._execute_with_ollama(task, context)  # type: ignore[attr-defined]

        # Build the initial system message with tool instructions embedded
        system_content = getattr(self, "_system_prompt", "You are a helpful assistant.")
        system_content += self._tool_system_addendum(context)

        # Build the initial user turn (same as OllamaWorkerMixin._build_messages)
        user_messages = self._build_messages(task, context)  # type: ignore[attr-defined]

        # Full conversation thread, managed manually for the loop
        thread: list[dict[str, str]] = [
            {"role": "system", "content": system_content}
        ] + user_messages

        self._print_thinking()

        final_text: str | None = None

        for round_num in range(self._max_tool_rounds):
            # Stream a response
            text = self._stream_full(context, thread)  # type: ignore[attr-defined]

            if text is None:
                # LLM unavailable — fall back to stub
                break

            # Check for a tool call in the response
            call = self._parse_tool_call(text)

            if call is None:
                # No tool call → this is the final answer
                final_text = text
                break

            # Extract just the reasoning before the TOOL_CALL line
            tool_idx = text.find("TOOL_CALL:")
            reasoning = text[:tool_idx].strip()

            logger.debug(
                "WorkerToolMixin [%s]: round %d tool_call=%s",
                getattr(self, "name", "worker"), round_num + 1, call.get("tool"),
            )

            # Execute the tool
            observation = self._execute_tool(call, task, context)

            # Append assistant turn (what LLM said so far) + tool result
            thread.append({"role": "assistant", "content": text})
            thread.append({
                "role": "user",
                "content": (
                    f"TOOL_RESULT:\n{observation}\n\n"
                    "Continue your analysis and produce the final answer. "
                    "Do NOT emit another TOOL_CALL unless absolutely necessary."
                ),
            })
            self._print_continuing()

        # Generate a concluding response if the loop exhausted rounds
        if final_text is None and thread:
            thread.append({
                "role": "user",
                "content": (
                    "Summarise your findings and produce the final answer now."
                ),
            })
            final_text = self._stream_full(context, thread)  # type: ignore[attr-defined]

        if final_text is None:
            final_text = self._stub_result(task, context)  # type: ignore[attr-defined]

        # Store confidence the same way OllamaWorkerMixin does
        confidence = self._compute_confidence(final_text)  # type: ignore[attr-defined]
        if "task_confidence" not in context.metadata:
            context.metadata["task_confidence"] = {}
        context.metadata["task_confidence"][task.id] = confidence

        return final_text

    # ------------------------------------------------------------------
    # Console output
    # ------------------------------------------------------------------

    def _print_thinking(self) -> None:
        print("      Thinking…", flush=True)

    def _print_tool_start(self, tool_id: str) -> None:
        print(f"      Using Tool: {tool_id}", flush=True)
        print("      Running…", flush=True)

    def _print_tool_result(self, tool_id: str, elapsed: float, success: bool) -> None:
        icon = "✓" if success else "✗"
        print(f"      {icon} {'Success' if success else 'Failed'} ({elapsed:.2f}s)", flush=True)

    def _print_continuing(self) -> None:
        print("      Continuing…", flush=True)

    # ------------------------------------------------------------------
    # execute() — satisfies BaseWorker's abstract requirement
    # ------------------------------------------------------------------

    def execute(self, task: "Task", context: "ExecutionContext") -> str:
        """
        Default ``execute()`` implementation for tool-enabled workers.

        Workers that inherit :class:`~smartagent.executive.workers.file_edit_mixin.FileEditMixin`
        **must NOT** override ``execute()`` themselves.  The MRO chain is:

            FileEditMixin.execute()          ← called by Scheduler
            └─ super().execute()             ← dispatches here
               └─ _execute_with_tools()      ← ReAct loop → Ollama
            └─ _write_output_files()         ← writes fenced code blocks to disk

        Workers that do *not* use ``FileEditMixin`` (and currently define their
        own ``execute()``) continue to work unchanged because their definition
        takes precedence in the MRO.
        """
        return self._execute_with_tools(task, context)
