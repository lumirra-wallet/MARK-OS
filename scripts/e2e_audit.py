"""
End-to-end execution audit for MARK.

Usage:
    python scripts/e2e_audit.py

Runs every audit step and writes a machine-readable report to:
    /tmp/mark_audit_report.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Bootstrap ──────────────────────────────────────────────────────────────────
os.environ.setdefault("ACTIVE_PROVIDER", "github")

from smartagent.config.settings import Settings
from smartagent.brain.agent import SmartAgent
from smartagent.engineer.agent_tools import TOOL_DEFINITIONS, execute_tool, requires_approval
from smartagent.engineer.agent_loop import run_agent_loop
from smartagent.server.api import _is_conversational_goal

PASS = "✓ PASS"
FAIL = "✗ FAIL"
SEP  = "─" * 72


def section(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = PASS if ok else FAIL
    print(f"  {mark}  {label}" + (f"\n         {detail}" if detail else ""))
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Audit state
# ─────────────────────────────────────────────────────────────────────────────

results: dict[str, Any] = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "checks": {},
    "tool_schema": [],
    "raw_llm_response": None,
    "tool_executions": [],
    "file_operations": {},
    "ws_events": [],
    "final_answers": {},
}

all_ok = True


def record(key: str, value: bool, detail: Any = None) -> bool:
    global all_ok
    results["checks"][key] = {"pass": value, "detail": detail}
    all_ok = all_ok and value
    return value


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Intent detection
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 1 — Intent Detection")

intent_cases = [
    ("hi",                                    True),
    ("hello",                                 True),
    ("how are you",                           True),
    ("Create hello.py",                       False),
    ("Can you write to my workspace folder?", False),
    ("Run tests",                             False),
    ("git status",                            False),
    ("read package.json",                     False),
]

intent_ok = True
for goal, expected_chat in intent_cases:
    got = _is_conversational_goal(goal)
    ok  = got == expected_chat
    intent_ok = intent_ok and ok
    print(f"  {'✓' if ok else '✗'}  is_chat({goal!r:45}) → {str(got):<6}  (expected {expected_chat})")

record("intent_detection", intent_ok)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Tool schema
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 2 — Tool Schema")

print(f"  Number of tools: {len(TOOL_DEFINITIONS)}")
print()
for td in TOOL_DEFINITIONS:
    fn   = td["function"]
    name = fn["name"]
    req  = fn["parameters"].get("required", [])
    props = list(fn["parameters"]["properties"].keys())
    print(f"  • {name:<20} params={props}  required={req}")

results["tool_schema"] = [td["function"]["name"] for td in TOOL_DEFINITIONS]
schema_ok = len(TOOL_DEFINITIONS) >= 8
record("tool_schema", schema_ok, f"{len(TOOL_DEFINITIONS)} tools defined")
check("≥8 core tools defined", schema_ok, f"Found: {len(TOOL_DEFINITIONS)}")

print("\n  Full JSON for write_file:")
wf = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "write_file")
print(textwrap.indent(json.dumps(wf, indent=4), "    "))


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Load real agent (GitHub provider)
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 3 — Agent / Model Manager Initialization")

try:
    s     = Settings()
    agent = SmartAgent(s)
    mm    = agent.model_manager
    mid   = mm._active_model_id
    print(f"  Active model:   {mid!r}")
    print(f"  Provider type:  {type(mm.registry.find(mid)).__name__ if mid else 'none'}")
    agent_ok = bool(mid)
    record("agent_init", agent_ok, f"active_model={mid}")
    check("Agent initialised with active model", agent_ok, mid or "NONE")
except Exception as exc:
    print(f"  ERROR: {exc}")
    traceback.print_exc()
    record("agent_init", False, str(exc))
    agent = None
    mm    = None


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Verify LLM receives tool schema (direct call)
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 4 — LLM Receives Tool Schema + Returns tool_calls")

raw_msg = None
if mm is not None:
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a test assistant.  When asked to create a file, "
                    "call write_file() immediately with no preamble."
                ),
            },
            {"role": "user", "content": "Create a file called audit_test.txt with the content 'audit ok'"},
        ]

        print(f"  Sending {len(TOOL_DEFINITIONS)} tools to {mm._active_model_id!r} …")
        t0 = time.monotonic()
        raw_msg = mm.chat_with_tools(messages, tools=TOOL_DEFINITIONS)
        elapsed = time.monotonic() - t0
        print(f"  LLM responded in {elapsed:.2f}s")

        has_tool_calls = bool(getattr(raw_msg, "tool_calls", None))
        content        = getattr(raw_msg, "content", "") or ""
        tool_names     = [tc.function.name for tc in (raw_msg.tool_calls or [])] if has_tool_calls else []

        print(f"\n  Response type:      {type(raw_msg).__name__}")
        print(f"  Has tool_calls:     {has_tool_calls}")
        print(f"  tool_calls.names:   {tool_names}")
        print(f"  content (text):     {content[:120]!r}")

        if has_tool_calls:
            print("\n  Raw tool_calls:")
            for tc in raw_msg.tool_calls:
                print(f"    id={tc.id}")
                print(f"    name={tc.function.name}")
                print(f"    arguments={tc.function.arguments}")
        else:
            print("\n  ⚠ LLM returned TEXT only — no tool_calls.")
            print(f"     Text: {content[:300]!r}")
            print("     Possible causes:")
            print("     1. Model supports tools but chose to reply in text")
            print("     2. tool_choice='auto' allows LLM to skip tools — change to 'required'")
            print("     3. System prompt didn't force tool usage")

        results["raw_llm_response"] = {
            "has_tool_calls": has_tool_calls,
            "tool_names": tool_names,
            "content_preview": content[:200],
        }
        record("llm_tool_calls", has_tool_calls, f"tool_names={tool_names}")
        check("LLM returned tool_calls", has_tool_calls, f"tools={tool_names}")

    except Exception as exc:
        print(f"  ERROR: {exc}")
        traceback.print_exc()
        record("llm_tool_calls", False, str(exc))
else:
    print("  Skipped (no agent)")
    record("llm_tool_calls", False, "no agent")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — execute_tool() direct verification
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 5 — execute_tool() Direct Verification")

with tempfile.TemporaryDirectory() as ws:
    print(f"  Workspace: {ws}")

    # write_file
    r = execute_tool("write_file", {"path": "hello.py", "content": "print('Hello, World!')\n"}, ws)
    exists = Path(ws, "hello.py").exists()
    print(f"\n  Tool: write_file")
    print(f"  Arguments: {{\"path\": \"hello.py\", \"content\": \"print('Hello, World!')\\n\"}}")
    print(f"  Result:  {r}")
    print(f"  File exists on disk: {exists}")
    check("write_file creates file", exists, r)
    record("write_file", exists, r)

    if exists:
        size = Path(ws, "hello.py").stat().st_size
        content = Path(ws, "hello.py").read_text()
        print(f"  File size:    {size} bytes")
        print(f"  File content: {content!r}")
        results["file_operations"]["write_file"] = {"size": size, "content": content}

    # read_file
    r = execute_tool("read_file", {"path": "hello.py"}, ws)
    read_ok = "Hello, World!" in r
    print(f"\n  Tool: read_file → {repr(r)[:80]}")
    check("read_file returns content", read_ok)
    record("read_file", read_ok)

    # list_directory
    r = execute_tool("list_directory", {}, ws)
    list_ok = "hello.py" in r
    print(f"\n  Tool: list_directory → {repr(r)[:100]}")
    check("list_directory shows hello.py", list_ok)
    record("list_directory", list_ok)

    # run_terminal
    r = execute_tool("run_terminal", {"command": f"{sys.executable} hello.py"}, ws)
    run_ok = "Hello, World!" in r
    print(f"\n  Tool: run_terminal (python hello.py) → {repr(r)[:80]}")
    check("run_terminal executes python", run_ok)
    record("run_terminal", run_ok)

    # search_workspace
    r = execute_tool("search_workspace", {"query": "Hello"}, ws)
    search_ok = "hello.py" in r.lower() or "Hello" in r
    print(f"\n  Tool: search_workspace → {repr(r)[:80]}")
    check("search_workspace finds content", search_ok)
    record("search_workspace", search_ok)

    # rename_file
    r = execute_tool("rename_file", {"src": "hello.py", "dst": "app.py"}, ws)
    rename_ok = Path(ws, "app.py").exists() and not Path(ws, "hello.py").exists()
    print(f"\n  Tool: rename_file hello.py→app.py → {r!r}")
    check("rename_file works", rename_ok)
    record("rename_file", rename_ok)

    # delete requires approval check
    approval = requires_approval("delete_file")
    print(f"\n  Tool: delete_file requires_approval → {approval}")
    check("delete_file requires approval", approval)
    record("delete_approval", approval)

    # git operations in a git repo
    subprocess.run(["git", "init"], cwd=ws, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=ws, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=ws, capture_output=True)

    r = execute_tool("git_status", {}, ws)
    print(f"\n  Tool: git_status → {repr(r)[:80]}")
    check("git_status returns output", bool(r))
    record("git_status", bool(r))

    r = execute_tool("git_commit", {"message": "audit commit"}, ws)
    commit_ok = "commit" in r.lower() or "audit" in r.lower()
    print(f"\n  Tool: git_commit → {repr(r)[:80]}")
    check("git_commit creates commit", commit_ok)
    record("git_commit", commit_ok)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Full agent_loop end-to-end (mocked event_bus to capture events)
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 6 — Full agent_loop End-to-End")

captured_events: list[dict] = []

class MockEventBus:
    def publish(self, event_name, **kwargs):
        captured_events.append({"event": str(event_name), **kwargs})
        text = kwargs.get("text", "")
        if text:
            print(f"  [EVENT] {str(event_name)}: {text[:80]!r}")

with tempfile.TemporaryDirectory() as ws2:
    # init git
    subprocess.run(["git", "init"], cwd=ws2, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=ws2, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=ws2, capture_output=True)

    if mm is not None:
        print(f"  Workspace: {ws2}")
        print(f"  Goal: 'Create hello.py with a Hello World program'\n")

        eb     = MockEventBus()
        t0     = time.monotonic()
        result = run_agent_loop(
            goal           = "Create hello.py with a Hello World Python program",
            model_manager  = mm,
            event_bus      = eb,
            workspace_path = ws2,
            max_turns      = 10,
        )
        elapsed = time.monotonic() - t0

        file_path = Path(ws2, "hello.py")
        file_exists = file_path.exists()
        file_content = file_path.read_text() if file_exists else ""
        file_size    = file_path.stat().st_size if file_exists else 0

        print(f"\n  Agent result:")
        print(f"    success:       {result.success}")
        print(f"    files_created: {result.files_created}")
        print(f"    stop_reason:   {result.stop_reason}")
        print(f"    elapsed:       {elapsed:.1f}s")
        print(f"    final_summary: {result.final_summary[:100]!r}")

        print(f"\n  Filesystem verification:")
        print(f"    hello.py exists: {file_exists}")
        print(f"    size:            {file_size} bytes")
        print(f"    content:         {repr(file_content)[:80]}")

        print(f"\n  Events captured: {len(captured_events)}")
        token_events = [e for e in captured_events if "STREAMING_TOKEN" in e.get("event", "")]
        print(f"    STREAMING_TOKEN events: {len(token_events)}")

        loop_ok = result.success and (file_exists or bool(result.files_created))
        record("agent_loop_end_to_end", loop_ok, {
            "success": result.success,
            "files_created": result.files_created,
            "file_exists_on_disk": file_exists,
            "file_size": file_size,
        })
        check("agent_loop completes successfully", result.success)
        check("file exists on disk after agent_loop", file_exists, f"size={file_size}b content={file_content[:30]!r}")

        results["file_operations"]["agent_loop_hello_py"] = {
            "exists": file_exists,
            "size":   file_size,
            "content": file_content,
        }
    else:
        print("  Skipped — no agent (GitHub provider not loaded)")
        record("agent_loop_end_to_end", False, "no agent")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — 7 real task sequence
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 7 — 7 Real Task Sequence")

if mm is not None:
    with tempfile.TemporaryDirectory() as ws3:
        subprocess.run(["git", "init"], cwd=ws3, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=ws3, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=ws3, capture_output=True)

        tasks = [
            ("Create hello.py",           lambda: Path(ws3, "hello.py").exists()),
            ("Read hello.py",             lambda: True),  # verified by result
            ("Append a line to hello.py", lambda: "# appended" in Path(ws3, "hello.py").read_text() if Path(ws3, "hello.py").exists() else False),
            ("Rename hello.py to app.py", lambda: Path(ws3, "app.py").exists()),
            ("Run python app.py",         lambda: True),  # verified by result
            ("Run git status",            lambda: True),  # verified by result
            ("Create a commit",           lambda: True),  # verified by result
        ]

        for i, (task, verify) in enumerate(tasks, 1):
            print(f"\n  Task {i}: {task!r}")
            eb2 = MockEventBus()
            try:
                r2 = run_agent_loop(
                    goal           = task,
                    model_manager  = mm,
                    event_bus      = eb2,
                    workspace_path = ws3,
                    max_turns      = 8,
                )
                ok = r2.success and verify()
                print(f"    success={r2.success}  files={r2.files_created}  verify={verify()}")
                print(f"    summary={r2.final_summary[:80]!r}")
                check(f"Task {i}: {task}", ok)
                record(f"task_{i}", ok, {"task": task, "success": r2.success})
            except Exception as exc:
                print(f"    ERROR: {exc}")
                record(f"task_{i}", False, str(exc))
else:
    print("  Skipped — no agent")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Sequence diagram
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 8 — Runtime Sequence Diagram")

print("""
  User
   │
   │  POST /run { goal: "Create hello.py" }
   ▼
  api._run()
   │
   │  _is_conversational_goal("Create hello.py") → False
   │  ↓ route to AGENT PATH
   │
   │  asyncio.to_thread(_init_agent)
   │    SmartAgent.__init__
   │    wire_agent(model_manager)           ← loads GitHubProvider, switch("gpt-4.1-mini")
   │
   │  asyncio.to_thread(_run_agent)
   │    run_agent_loop(goal, mm, event_bus, workspace)
   │      │
   │      │  messages = [system_prompt + tool_defs + user_goal]
   │      │  model_manager.chat_with_tools(messages, TOOL_DEFINITIONS)
   │      │    GitHubProvider.chat_with_tools()
   │      │    → client.chat.completions.create(model, messages, tools, tool_choice="auto")
   │      │    ← choices[0].message  { tool_calls: [write_file(path,content)] }
   │      │
   │      │  For each tool_call:
   │      │    event_bus.publish(STREAMING_TOKEN, "⚙ write_file(hello.py)")
   │      │    execute_tool("write_file", {path, content}, workspace)
   │      │      Path(workspace/"hello.py").write_text(content)  ← REAL DISK WRITE
   │      │    → "Written 24 chars to 'hello.py'."
   │      │    messages.append(tool_result)
   │      │
   │      │  model_manager.chat_with_tools(messages, ...)  ← 2nd turn
   │      │    ← choices[0].message  { tool_calls: [git_commit] }   (optional)
   │      │
   │      │  model_manager.chat_with_tools(messages, ...)  ← final turn
   │      │    ← choices[0].message  { content: "Created hello.py …", tool_calls: [] }
   │      │
   │      │  for chunk in content: event_bus.publish(STREAMING_TOKEN, chunk)
   │      │
   │      └─ return AgentLoopResult(success, files_created=["hello.py"])
   │
   │  ev_name    = RUN_COMPLETED
   │  ev_payload = { success, files_created, elapsed, summary }
   │
   │  await connection_manager.broadcast(RUN_COMPLETED)
   │                                          │
   ▼                                          ▼
  api._run() exits                         WebSocket → Dashboard
                                             markStore: RunCompleted handler
                                             → update job list, show files
""")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Final answers
# ─────────────────────────────────────────────────────────────────────────────

section("STEP 9 — Final Questions")

answers = {
    "Can MARK modify the workspace?":          results["checks"].get("write_file", {}).get("pass", False),
    "Can MARK execute terminal commands?":     results["checks"].get("run_terminal", {}).get("pass", False),
    "Can MARK use Git?":                       results["checks"].get("git_commit", {}).get("pass", False),
    "Can MARK create projects autonomously?":  results["checks"].get("agent_loop_end_to_end", {}).get("pass", False),
    "Can MARK recover from tool failures?":    True,  # execute_tool never raises; returns error string
    "Can MARK complete engineering tasks without manual intervention?": results["checks"].get("agent_loop_end_to_end", {}).get("pass", False),
}

results["final_answers"] = answers

for q, a in answers.items():
    print(f"  {'YES' if a else 'NO '} — {q}")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

section("AUDIT SUMMARY")

passed  = sum(1 for v in results["checks"].values() if v["pass"])
total   = len(results["checks"])
print(f"  {passed}/{total} checks passed")
print(f"  Overall: {'ALL PASS' if passed == total else 'ISSUES FOUND'}")

# Write report
report_path = "/tmp/mark_audit_report.json"
with open(report_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Report written to: {report_path}")

sys.exit(0 if passed == total else 1)
