"""
Git console commands — Milestone 21: Git Engine.

All git operations are available as ``git <sub-command>`` from the MARK
console.  The sub-command dispatcher resolves the current repository from
the active workspace path (if one is open) or the current working directory.

Available sub-commands
----------------------
    status              — show working-tree state
    branch <name>       — create + checkout a branch
    checkout <name>     — switch to an existing branch
    branches [--all]    — list branches
    add [paths…]        — stage files (default: all)
    commit <message>    — commit staged files
    push [--upstream]   — push current branch
    pull                — pull from remote
    log [n]             — recent commits (default 10)
    diff [--staged]     — show diff
    merge <branch>      — merge branch into HEAD
    rollback [n]        — soft-reset n commits (default 1)
    restore <path>      — discard working-tree changes in a file
    stash               — stash working-tree changes
    stash pop           — restore the most recent stash
    stash list          — list all stash entries
    init [path]         — initialise a new repository
    tag <name> [msg]    — create a tag
    pr [title]          — generate a pull-request description
    config <key>        — read a git config value
    remote              — list remotes
    help                — show this listing

Examples::

    git status
    git branch feature/login
    git commit "Add login module"
    git push --upstream
    git log 5
    git pr "Login System"
    git rollback 2
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from smartagent.ui.command_router import CommandRouter

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_client(agent: "SmartAgent") -> "GitClient":  # noqa: F821
    """
    Resolve the GitClient to use for this command.

    Priority:
      1. ``agent.metadata["git_client"]`` (injected by Orchestrator or tests)
      2. Active workspace project path (if a workspace is open)
      3. Current working directory
    """
    from smartagent.git.git_client import GitClient

    # Check for an agent-level override (e.g. from tests)
    cached = getattr(agent, "_git_client_cache", None)
    if cached is not None:
        return cached

    # Active workspace
    ws_mgr = getattr(agent, "workspace_manager", None)
    if ws_mgr is not None and ws_mgr.active is not None:
        ws_path = getattr(ws_mgr.active, "path", None) or os.getcwd()
    else:
        ws_path = os.getcwd()

    return GitClient(ws_path)


def _display(result) -> str:
    """Turn a GitResult into a console string."""
    return "\n".join(result.as_display_lines())


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------

def _sub_status(git, args: list[str]) -> str:
    status = git.status()
    if not status.branch:
        return "[error] Not a git repository. Run 'git init' first."
    return "\n".join(status.as_display_lines())


def _sub_branch(git, args: list[str]) -> str:
    if not args:
        return (
            "Usage: git branch <name> [--from <base>]\n"
            "Example: git branch feature/login"
        )
    name = args[0]
    from_branch = None
    if "--from" in args:
        idx = args.index("--from")
        if idx + 1 < len(args):
            from_branch = args[idx + 1]
    checkout = "--no-checkout" not in args
    result = git.create_branch(name, checkout=checkout, from_branch=from_branch)
    return _display(result)


def _sub_checkout(git, args: list[str]) -> str:
    if not args:
        return "Usage: git checkout <branch>"
    return _display(git.checkout(args[0]))


def _sub_branches(git, args: list[str]) -> str:
    all_branches = "--all" in args or "-a" in args
    branches = git.list_branches(all_branches=all_branches)
    if not branches:
        return "No branches found. Run 'git init' or 'git branch <name>' first."
    lines = ["  Branches:"]
    for i, b in enumerate(branches):
        marker = "  *" if i == 0 else "   "
        lines.append(f"{marker} {b}")
    return "\n".join(lines)


def _sub_add(git, args: list[str]) -> str:
    paths = args if args else ["."]
    result = git.add(paths)
    if result.success:
        status = git.status()
        staged_count = len(status.staged)
        return f"✓ {staged_count} file(s) staged"
    return _display(result)


def _sub_commit(git, args: list[str]) -> str:
    if not args:
        return (
            "Usage: git commit <message>\n"
            "Example: git commit \"Add login module\""
        )
    message = " ".join(args)
    # Strip surrounding quotes if the user typed them literally
    if len(message) >= 2 and message[0] in ('"', "'") and message[-1] == message[0]:
        message = message[1:-1]
    result = git.commit(message)
    return _display(result)


def _sub_push(git, args: list[str]) -> str:
    set_upstream = "--upstream" in args or "-u" in args
    force        = "--force" in args or "-f" in args
    remote       = next((a for a in args if not a.startswith("-")), "origin")
    result = git.push(remote=remote, set_upstream=set_upstream, force=force)
    return _display(result)


def _sub_pull(git, args: list[str]) -> str:
    rebase = "--rebase" in args
    remote = next((a for a in args if not a.startswith("-")), "origin")
    result = git.pull(remote=remote, rebase=rebase)
    return _display(result)


def _sub_log(git, args: list[str]) -> str:
    n = 10
    for a in args:
        try:
            n = int(a)
            break
        except ValueError:
            pass
    commits = git.log(n=n)
    if not commits:
        return "  (no commits)"
    lines = [f"  Recent commits ({len(commits)}):"]
    for c in commits:
        lines.append(f"    {c}")
    return "\n".join(lines)


def _sub_diff(git, args: list[str]) -> str:
    staged = "--staged" in args or "--cached" in args
    path = next((a for a in args if not a.startswith("-")), None)
    diff = git.diff(staged=staged, path=path)
    if not diff.strip():
        label = "staged" if staged else "working tree"
        return f"  No {label} changes."
    # Truncate very large diffs
    lines = diff.splitlines()
    if len(lines) > 100:
        shown = lines[:100]
        shown.append(f"  … ({len(lines) - 100} more lines)")
        return "\n".join(shown)
    return diff


def _sub_merge(git, args: list[str]) -> str:
    if not args or args[0].startswith("-"):
        return (
            "Usage: git merge <branch> [--no-ff]\n"
            "Example: git merge feature/login"
        )
    branch = args[0]
    no_ff  = "--no-ff" in args
    result = git.merge(branch, no_ff=no_ff)
    return _display(result)


def _sub_rollback(git, args: list[str]) -> str:
    n = 1
    mode = "soft"
    for a in args:
        if a.isdigit():
            n = int(a)
        elif a in ("--soft", "--mixed", "--hard"):
            mode = a.lstrip("-")
    if mode == "hard":
        return (
            "[warning] Hard rollback is destructive and cannot be undone.\n"
            "If you are sure, run:\n"
            f"  git reset --hard HEAD~{n}\n"
            "directly, or pass --confirm to proceed."
        )
    result = git.reset(mode=mode, target=f"HEAD~{n}")
    return _display(result)


def _sub_restore(git, args: list[str]) -> str:
    if not args:
        return "Usage: git restore <path>"
    staged = "--staged" in args
    paths = [a for a in args if not a.startswith("-")]
    if not paths:
        return "Usage: git restore <path>"
    results = [git.restore(p, staged=staged) for p in paths]
    return "\n".join(_display(r) for r in results)


def _sub_stash(git, args: list[str]) -> str:
    if not args:
        result = git.stash()
        return _display(result)
    sub = args[0].lower()
    if sub == "pop":
        return _display(git.stash_pop())
    if sub == "list":
        entries = git.stash_list()
        if not entries:
            return "  Stash is empty."
        return "\n".join(f"  {e}" for e in entries)
    # Treat unknown sub-arg as the stash message
    return _display(git.stash(message=" ".join(args)))


def _sub_init(git, args: list[str]) -> str:
    if args:
        from smartagent.git.git_client import GitClient
        target = os.path.abspath(args[0])
        os.makedirs(target, exist_ok=True)
        git = GitClient(target)
    return _display(git.init())


def _sub_tag(git, args: list[str]) -> str:
    if not args:
        # List tags
        tags = git.list_tags()
        if not tags:
            return "  No tags."
        return "\n".join(f"  {t}" for t in tags)
    name    = args[0]
    message = " ".join(args[1:]) if len(args) > 1 else None
    return _display(git.tag(name, message=message))


def _sub_pr(git, args: list[str]) -> str:
    base   = "main"
    title  = None
    remaining = []
    i = 0
    while i < len(args):
        if args[i] == "--base" and i + 1 < len(args):
            base = args[i + 1]
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    if remaining:
        title = " ".join(remaining)
    try:
        pr = git.pr_builder().build(title=title, base_branch=base)
        return "\n".join(pr.as_display_lines())
    except Exception as exc:  # noqa: BLE001
        return f"[error] PR generation failed: {exc}"


def _sub_config(git, args: list[str]) -> str:
    if not args:
        return (
            "Usage: git config <key> [value]\n"
            "Example: git config user.name"
        )
    if len(args) == 1:
        value = git.config_get(args[0])
        return f"  {args[0]} = {value!r}" if value else f"  {args[0]} not set"
    key, value = args[0], " ".join(args[1:])
    return _display(git.config_set(key, value))


def _sub_remote(git, args: list[str]) -> str:
    remotes = git.list_remotes()
    if not remotes:
        return "  No remotes configured."
    lines = ["  Remotes:"]
    for name, url in remotes.items():
        lines.append(f"    {name}  {url}")
    return "\n".join(lines)


def _sub_help(*_) -> str:
    return """\
  Git Engine commands:

    git status                — show working-tree state
    git branch <name>         — create + checkout branch
    git checkout <branch>     — switch branch
    git branches [--all]      — list all branches
    git add [paths…]          — stage files (default: all)
    git commit <message>      — commit staged files
    git push [--upstream]     — push current branch
    git pull [--rebase]       — pull from remote
    git log [n]               — show n recent commits (default 10)
    git diff [--staged]       — show diff
    git merge <branch>        — merge branch into HEAD
    git rollback [n]          — soft-reset n commits (default 1)
    git restore <path>        — discard changes in file
    git stash                 — stash working-tree changes
    git stash pop             — restore most recent stash
    git stash list            — list all stash entries
    git init [path]           — init a repository
    git tag [name [msg]]      — create/list tags
    git pr [title]            — generate PR description
    git config <key> [value]  — read/write config
    git remote                — list remotes
    git help                  — show this listing\
"""


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH = {
    "status":   _sub_status,
    "branch":   _sub_branch,
    "checkout": _sub_checkout,
    "branches": _sub_branches,
    "add":      _sub_add,
    "commit":   _sub_commit,
    "push":     _sub_push,
    "pull":     _sub_pull,
    "log":      _sub_log,
    "diff":     _sub_diff,
    "merge":    _sub_merge,
    "rollback": _sub_rollback,
    "restore":  _sub_restore,
    "stash":    _sub_stash,
    "init":     _sub_init,
    "tag":      _sub_tag,
    "pr":       _sub_pr,
    "config":   _sub_config,
    "remote":   _sub_remote,
    "help":     _sub_help,
}


def handle_git(agent: "SmartAgent", args: list[str]) -> str:
    """
    Main entry point for all ``git <sub>`` commands.

    Usage: git <sub-command> [args…]

    Run 'git help' for a full listing.
    """
    if not args:
        # Default: show status
        git = _make_client(agent)
        return _sub_status(git, [])

    sub  = args[0].lower()
    rest = args[1:]

    handler = _DISPATCH.get(sub)
    if handler is None:
        return (
            f"Unknown git sub-command: {sub!r}\n"
            "Run 'git help' for available commands."
        )

    git = _make_client(agent)
    return handler(git, rest)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(router: CommandRouter) -> None:
    """Register all git commands with *router*."""
    router.register(
        "git", handle_git,
        "git <sub> — Git engine (status, branch, commit, push, pull, merge, …)",
        "GIT", 0,
    )
