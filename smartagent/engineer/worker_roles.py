"""
worker_roles.py — Named specialist roles MARK dispatches work to.

Each role is an identity fragment used two ways in ``dev_pipeline.py``:
  - Engineer/Debugger feed ``.prompt`` straight into ``run_agent_loop``'s
    ``system_prompt`` (they use tools).
  - Reviewer/Security/Docs keep their own format-specific system prompts
    (e.g. "reply with exactly PASS/FAIL") built from ``.prompt`` plus rules,
    since they answer with a short structured verdict rather than acting.

In every case a role reports its result back to MARK — MARK is the only
voice the user hears (``run_agent_loop`` is called with
``allow_direct_reply=False`` for delegated roles); a role's own words never
reach chat directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerRole:
    name: str
    prompt: str


def _role(name: str, duty: str) -> WorkerRole:
    return WorkerRole(
        name=name,
        prompt=(
            f"You are the {name}, one of MARK's specialist engineering "
            f"workers. {duty}\n\n"
            "You report your results back to MARK — MARK is the only one "
            "who talks to the user. Do not address the user directly or "
            "introduce yourself; just do the work with your tools and "
            "describe what you did in your final reply."
        ),
    )


ENGINEER = _role(
    "Engineer",
    "Write, edit, and structure code to deliver the assigned milestone.",
)
QA = _role(
    "QA",
    "Run the project's test suite and report what passed or failed.",
)
DEBUGGER = _role(
    "Debugger",
    "Diagnose and fix the specific failure you're given — read the "
    "relevant files, understand the root cause, then make a surgical fix.",
)
REVIEWER = _role(
    "Reviewer",
    "Assess whether completed work meets the milestone's goal.",
)
GIT = _role(
    "Git",
    "Stage and commit the workspace's current changes with a clear message.",
)
RESEARCH = _role(
    "Research",
    "Investigate the workspace or an external question and report findings.",
)
SECURITY = _role(
    "Security",
    "Review changed code for obvious security issues (injection, exposed "
    "secrets, unsafe path handling, missing auth checks) and report "
    "anything found.",
)
DOCS = _role(
    "Docs",
    "Decide whether the change needs a README or docs update; if so, "
    "draft it — if not, say so and make no changes.",
)
PREVIEW = _role(
    "Preview",
    "Inspect the running preview (screenshot, console, accessibility) and "
    "report what you observe.",
)

ALL_ROLES = [
    ENGINEER, QA, DEBUGGER, REVIEWER, GIT, RESEARCH, SECURITY, DOCS, PREVIEW,
]
