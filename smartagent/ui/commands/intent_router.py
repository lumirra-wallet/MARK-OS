"""
intent_router — v2.0: Intelligent intent classification for the REPL fallback.

When the user types free-text that is not a registered command, this module
classifies the intent and routes accordingly:

  * **engineering task** → delegates to the ``engineer`` command pipeline
    (SoftwareEngineer.build → WorkspaceScanner → FileEditor → DevLoop →
    DebugLoop → QualityRunner → GitEngine → ProjectMemory)
  * **general conversation / Q&A** → falls through to the active Ollama model

Classification is fully deterministic (pattern matching, no AI call) so it
adds zero latency.  All existing tests are preserved — the classifier only
runs in the fallback slot, which is never reached for registered commands.

Engineering triggers (all of these together):
  1. An action verb in the first four words (create, build, fix, refactor, …)
  2. PLUS either a software-artifact noun anywhere in the input
              OR a file-extension pattern (e.g. ``.py``, ``.ts``)

Question words at the start (what, how, why, explain, tell, describe, …)
unconditionally route to chat, regardless of later content, so phrases like
"what is a REST API?" or "explain how to fix this bug" stay in chat mode.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartagent.brain.agent import SmartAgent

# ---------------------------------------------------------------------------
# Vocabulary tables
# ---------------------------------------------------------------------------

# First word → always chat, regardless of other content
_CHAT_STARTERS: frozenset[str] = frozenset([
    "what", "who", "when", "where", "why", "how", "which", "is", "are",
    "was", "were", "do", "does", "did", "can", "could", "should", "would",
    "will", "shall", "may", "might", "explain", "tell", "describe",
    "summarize", "summarise", "show", "list", "compare", "contrast",
    "define", "clarify", "elaborate", "analyze", "analyse",
    "discuss", "suggest", "recommend", "advise", "help",
    # meta questions
    "am", "have", "has", "had",
])

# Action verbs that signal a software-engineering task
_ENGINEER_VERBS: frozenset[str] = frozenset([
    # creation
    "create", "build", "write", "make", "generate", "implement",
    "develop", "code", "program", "scaffold", "initialize", "init",
    "bootstrap", "start", "new",
    # modification
    "fix", "refactor", "update", "modify", "edit", "add", "remove",
    "delete", "change", "improve", "optimize", "optimise", "rewrite",
    "debug", "patch", "upgrade", "extend", "enhance", "restructure",
    "rename", "move", "merge", "split", "extract", "migrate",
    # setup / ops
    "setup", "set", "configure", "install", "deploy", "integrate",
    "connect", "wire", "hook", "register", "mount",
    # testing
    "test",
    # documentation
    "document",
])

# Nouns that signal a software artifact is being discussed as a work target
_ENGINEER_NOUNS: frozenset[str] = frozenset([
    # code units
    "file", "files", "script", "scripts", "function", "functions",
    "class", "classes", "method", "methods", "module", "modules",
    "package", "packages", "library", "libraries", "component",
    "components", "interface", "interfaces", "algorithm", "algorithms",
    # project types
    "app", "application", "website", "webpage", "page", "landing",
    "dashboard", "portal", "platform", "service", "services",
    "microservice", "microservices", "server", "backend", "frontend",
    "fullstack", "full-stack", "saas", "cli", "tool", "bot", "worker",
    # web / api
    "api", "rest", "graphql", "endpoint", "endpoints", "route", "routes",
    "webhook", "webhook", "middleware", "handler", "handlers",
    # data
    "database", "db", "schema", "schemas", "model", "models",
    "migration", "migrations", "query", "queries", "orm",
    # auth
    "auth", "authentication", "authorization", "login", "logout",
    "signup", "signup", "session", "sessions", "jwt", "oauth",
    # devops / config
    "dockerfile", "docker", "container", "pipeline", "workflow",
    "config", "configuration", "makefile", "yaml", "toml", "env",
    "environment", "deployment", "infrastructure",
    # testing
    "test", "tests", "spec", "specs", "suite", "coverage",
    # general code concepts
    "feature", "features", "bug", "bugs", "issue", "issues",
    "project", "codebase", "repository", "repo", "code",
    # ui
    "form", "forms", "view", "views", "template", "templates",
    "stylesheet", "css", "html", "jsx", "tsx",
    # integrations
    "integration", "integrations", "payment", "payments", "stripe",
    "email", "notification", "notifications", "queue", "cache",
    "cron", "job", "jobs", "scheduler",
])

# File extension pattern — .py .js .ts .html .css .json .yaml .toml etc.
_EXT_RE: re.Pattern = re.compile(r"\.[a-z]{2,5}\b")

# Phrases that — regardless of verb — signal a conversational turn
_CHAT_PHRASES: tuple[re.Pattern, ...] = (
    re.compile(r"\b(what is|what are|what does|what do|what's)\b", re.I),
    re.compile(r"\b(how does|how do|how is|how are|how to)\b", re.I),
    re.compile(r"\b(tell me (about|what|how|why))\b", re.I),
    re.compile(r"\b(explain (what|how|why|the|a|an))\b", re.I),
    re.compile(r"\b(can you (explain|tell|show|describe|help me understand))\b", re.I),
    re.compile(r"\b(could you (explain|tell|describe))\b", re.I),
    re.compile(r"\?$"),   # ends with a question mark → almost certainly a question
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent(raw: str) -> str:
    """
    Classify *raw* as ``"engineer"`` or ``"chat"``.

    Rules (applied in order):
    1. Empty / whitespace → ``"chat"`` (safe default)
    2. Conversational phrase patterns → ``"chat"``
    3. First word is a chat-starter word → ``"chat"``
    4. Engineering verb in first 4 words AND (software noun OR file extension) → ``"engineer"``
    5. Default → ``"chat"``
    """
    stripped = raw.strip()
    if not stripped:
        return "chat"

    low = stripped.lower()
    words = low.split()

    # Rule 2 — chat phrase patterns (before checking starters, to catch "help me build")
    for pat in _CHAT_PHRASES:
        if pat.search(low):
            return "chat"

    # Rule 3 — first word is an unambiguous chat starter
    if words[0] in _CHAT_STARTERS:
        return "chat"

    # Rule 4 — engineering verb + artifact context
    first_four: set[str] = set(words[:4])
    has_verb = bool(first_four & _ENGINEER_VERBS)

    if has_verb:
        has_ext = bool(_EXT_RE.search(low))
        has_noun = any(noun in low for noun in _ENGINEER_NOUNS)
        if has_ext or has_noun:
            return "engineer"

    return "chat"


# ---------------------------------------------------------------------------
# Fallback handler — replaces models.fallback_chat as the router's fallback
# ---------------------------------------------------------------------------

def intent_aware_fallback(agent: "SmartAgent", raw: str) -> str:
    """
    REPL fallback handler.

    Classifies *raw* and either:
    - delegates to the ``engineer`` command pipeline, or
    - falls through to the active Ollama model chat.

    Registered by :class:`~smartagent.ui.console.Console` via
    ``router.set_fallback(intent_aware_fallback)``.
    """
    intent = classify_intent(raw)

    if intent == "engineer":
        print(f"\n  [intent] Detected engineering task — routing to Software Engineer pipeline")
        from smartagent.ui.commands.engineer_cmd import handle_engineer
        # Treat the entire raw input as the goal (same as typing "engineer <raw>")
        args = raw.strip().split()
        return handle_engineer(agent, args)

    # General conversation / Q&A → model chat
    from smartagent.ui.commands.models import fallback_chat
    return fallback_chat(agent, raw)
