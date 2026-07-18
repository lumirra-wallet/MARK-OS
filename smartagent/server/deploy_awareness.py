"""
deploy_awareness.py — restart/redeploy awareness.

Persists the last-known git HEAD commit per workspace (via get_storage())
and, on each server start / connect, compares it against the current HEAD
so MARK can mention what changed since it was last running — the
"remember and check if changes were made" behavior requested alongside the
Engineer worker's new git-push capability (see
agent_tools.py::_git_push, api.py::_push_with_approval).

Not a chat feature on its own: check_for_new_commits() returns a plain-text
summary (or None) that callers feed into the opening-message prompt as
another fact, the same way _workspace_preamble() does in api.py — MARK's
own LLM composes the actual sentence, this module only supplies the raw
material.
"""

from __future__ import annotations

import subprocess

from smartagent.logs.logger import get_logger
from smartagent.server.conversation_store import workspace_id
from smartagent.storage.factory import get_storage

logger = get_logger(__name__)

_NAMESPACE = "agent_state"
_MAX_COMMITS_SHOWN = 10


def _run_git(args: list[str], workspace: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args], capture_output=True, text=True, cwd=workspace, timeout=10,
        )
        if r.returncode != 0:
            return None
        return r.stdout.strip()
    except Exception as exc:
        logger.debug("deploy_awareness: git %s failed: %s", args, exc)
        return None


def _key(workspace: str) -> str:
    return f"{workspace_id(workspace)}:last_known_commit"


def check_for_new_commits(workspace: str) -> str | None:
    """
    Compare the current git HEAD against the last commit MARK remembers for
    *workspace*, then persist the current HEAD as the new baseline.

    Returns a short plain-text summary of what changed if the workspace has
    moved on since MARK last ran here (a push + redeploy, a manual pull,
    etc.) — or None on a first-ever run, an unchanged HEAD, or a non-git
    workspace.
    """
    current_head = _run_git(["rev-parse", "HEAD"], workspace)
    if not current_head:
        return None

    store = get_storage()
    key = _key(workspace)
    last_known = store.get(_NAMESPACE, key)
    store.set(_NAMESPACE, key, current_head)

    if not last_known or last_known == current_head:
        return None

    log = _run_git(
        ["log", f"{last_known}..{current_head}", "--oneline", f"-{_MAX_COMMITS_SHOWN}"],
        workspace,
    )
    if not log:
        # last_known may no longer be reachable (force-push, rebase, etc.)
        # — still worth a mention even without a clean commit range.
        return f"The codebase has changed since I was last running here (now at {current_head[:8]})."

    commit_count = len(log.splitlines())
    return (
        f"The codebase has been updated since I was last running here — "
        f"{commit_count} new commit{'s' if commit_count != 1 else ''}:\n{log}"
    )
