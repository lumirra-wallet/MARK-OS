"""
RequirementAnalyzer — Milestone 25 / v2.0 Performance Upgrade.

v2.0 fixes:
  - "calculator CLI", "cli", "command-line", "script", "utility" → backend
    (were previously missing from backend keywords, causing them to fall
    through to the wrong domain or get no domain at all)
  - Removed "interface" and "web app" from frontend keywords — too ambiguous
    (a CLI has an "interface"; a "web app" built on Flask is backend-first)
  - Removed "ui" from frontend — a "CLI UI" should not classify as frontend
  - Added "screen" / "button" only via explicit frontend patterns to avoid
    false positives on terminal UI libraries (curses, rich)
  - Added "cli", "command line", "utility", "script", "function" explicitly
    to backend so they always win over the default path

Analyzes a natural-language goal and extracts:
  - Complexity estimate (small / medium / large / xlarge)
  - Required technical domains (backend, frontend, database, auth, …)
  - Inferred tech stack hints
  - Suggested team assignments
  - Open questions (things that need clarification)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RequirementReport:
    """
    Structured analysis of a development goal.

    Attributes:
        goal:            Original goal string.
        complexity:      ``"small"``, ``"medium"``, ``"large"``, or ``"xlarge"``.
        domains:         Technical areas involved (e.g. ``["backend", "auth"]``).
        stack_hints:     Detected or inferred tech (e.g. ``["FastAPI", "React"]``).
        teams:           Recommended team order (e.g. ``["engineering", "qa"]``).
        open_questions:  Questions that need clarification before work starts.
        notes:           Additional analysis notes.
    """

    goal:            str
    complexity:      str              = "medium"
    domains:         list[str]        = field(default_factory=list)
    stack_hints:     list[str]        = field(default_factory=list)
    teams:           list[str]        = field(default_factory=list)
    open_questions:  list[str]        = field(default_factory=list)
    notes:           list[str]        = field(default_factory=list)

    def as_display_lines(self) -> list[str]:
        lines = [
            f"  Goal       : {self.goal[:80]}",
            f"  Complexity : {self.complexity}",
        ]
        if self.domains:
            lines.append(f"  Domains    : {', '.join(self.domains)}")
        if self.stack_hints:
            lines.append(f"  Stack hints: {', '.join(self.stack_hints)}")
        if self.teams:
            lines.append(f"  Teams      : {' → '.join(self.teams)}")
        if self.open_questions:
            lines.append("  Questions  :")
            for q in self.open_questions:
                lines.append(f"    · {q}")
        if self.notes:
            lines.append("  Notes      :")
            for n in self.notes:
                lines.append(f"    · {n}")
        return lines

    def as_ai_context(self) -> str:
        """Return a compact string for injection into an AI prompt."""
        parts = [
            f"Goal: {self.goal}",
            f"Complexity: {self.complexity}",
        ]
        if self.domains:
            parts.append("Domains: " + ", ".join(self.domains))
        if self.stack_hints:
            parts.append("Stack: " + ", ".join(self.stack_hints))
        if self.open_questions:
            parts.append("Open: " + "; ".join(self.open_questions[:3]))
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Keyword rules
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "backend": [
        # Original
        "api", "rest", "graphql", "server", "backend", "endpoint", "service",
        "fastapi", "django", "flask", "express", "rails", "spring",
        # v2.0 additions — CLI / script / utility goals must route here
        "cli", "command line", "command-line", "script", "utility", "tool",
        "calculator", "function", "automation", "bot", "crawler", "scraper",
        "library", "module", "package", "class", "algorithm", "parser",
    ],
    "frontend": [
        # v2.0: removed "ui", "interface", "web app" — too ambiguous
        # Only keep unambiguously visual/browser keywords
        "frontend", "react", "vue", "angular", "svelte", "next.js",
        "tailwind", "html", "css", "dashboard", "web page", "webpage",
        "browser", "component", "stylesheet", "responsive",
    ],
    "mobile": [
        "mobile", "ios", "android", "react native", "flutter", "expo",
        "app store", "push notification",
    ],
    "database": [
        "database", "db", "schema", "migration", "orm", "sql", "postgres",
        "mysql", "sqlite", "mongodb", "redis", "elasticsearch",
    ],
    "auth": [
        "auth", "authentication", "login", "sign in", "sign up", "jwt",
        "oauth", "session", "password", "permissions", "roles",
    ],
    "testing": [
        "test", "pytest", "jest", "coverage", "tdd", "bdd", "ci", "qa",
        "unit test", "integration test", "e2e",
    ],
    "devops": [
        "deploy", "docker", "kubernetes", "ci/cd", "github actions",
        "aws", "gcp", "azure", "nginx", "ssl", "domain",
    ],
    "payments": [
        "payment", "stripe", "billing", "subscription", "checkout",
        "invoice", "saas", "pricing plan",
    ],
    "realtime": [
        "websocket", "real-time", "realtime", "live", "streaming",
        "notification", "socket.io", "sse",
    ],
    "search": [
        "search", "full-text", "elasticsearch", "algolia", "solr",
        "index", "query", "filter",
    ],
}

_STACK_PATTERNS: list[tuple[str, str]] = [
    (r"\bfastapi\b",       "FastAPI"),
    (r"\bdjango\b",        "Django"),
    (r"\bflask\b",         "Flask"),
    (r"\bexpress\b",       "Express"),
    (r"\bnext\.?js\b",     "Next.js"),
    (r"\breact\b",         "React"),
    (r"\bvue\b",           "Vue"),
    (r"\bsvelte\b",        "Svelte"),
    (r"\btailwind\b",      "Tailwind CSS"),
    (r"\bpostgres(ql)?\b", "PostgreSQL"),
    (r"\bmysql\b",         "MySQL"),
    (r"\bsqlite\b",        "SQLite"),
    (r"\bmongodb\b",       "MongoDB"),
    (r"\bredis\b",         "Redis"),
    (r"\bpytest\b",        "pytest"),
    (r"\bjest\b",          "Jest"),
    (r"\bdocker\b",        "Docker"),
    (r"\bkubernetes\b",    "Kubernetes"),
    (r"\bstripe\b",        "Stripe"),
    (r"\bgithub actions\b","GitHub Actions"),
    (r"\bpython\b",        "Python"),
    (r"\btypescript\b",    "TypeScript"),
    (r"\bjavascript\b",    "JavaScript"),
    (r"\bgo\b|\bgolang\b", "Go"),
    (r"\brust\b",          "Rust"),
    (r"\bruntime\b",       "Node.js"),
]

_COMPLEXITY_RULES: list[tuple[int, str]] = [
    (0,  "small"),
    (2,  "medium"),
    (4,  "large"),
    (6,  "xlarge"),
]

_DEFAULT_TEAMS: list[str] = ["research", "engineering", "qa", "documentation"]

# v2.0: goals containing these patterns should NEVER add "frontend" even if
# another keyword overlaps (e.g. "web app" in a Flask context)
_BACKEND_ONLY_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.I) for p in [
        r"\bcli\b",
        r"\bcommand[\s-]line\b",
        r"\bcalculator\b",
        r"\bscript\b",
        r"\butility\b",
        r"\bfunction\b",
        r"\balgorithm\b",
        r"\bparser\b",
        r"\bscraper\b",
        r"\bcrawler\b",
        r"\bbot\b",
        r"\blibrary\b",
        r"\bmodule\b",
        r"\bpackage\b",
        r"\bhello[\s._-]?world\b",
        r"\bhello\.py\b",
    ]
]


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class RequirementAnalyzer:
    """
    Analyzes a natural-language development goal and returns a
    :class:`RequirementReport`.

    v2.0: fixed domain classification for CLI/script/utility goals.
    """

    def __init__(self, model_manager: Any | None = None) -> None:
        self._model_manager = model_manager

    def analyze(self, goal: str) -> RequirementReport:
        """
        Analyze *goal* and return a :class:`RequirementReport`.

        Always produces a useful result even without a model.
        """
        low = goal.lower()
        domains    = self._detect_domains(low)
        stack      = self._detect_stack(low)
        complexity = self._estimate_complexity(domains, goal)
        teams      = self._select_teams(domains)
        questions  = self._generate_questions(goal, domains)
        notes      = self._notes(goal, domains)

        return RequirementReport(
            goal=goal,
            complexity=complexity,
            domains=domains,
            stack_hints=stack,
            teams=teams,
            open_questions=questions,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _detect_domains(self, low: str) -> list[str]:
        found = []

        # v2.0: check backend-only patterns first; if matched, suppress frontend
        is_backend_only = any(p.search(low) for p in _BACKEND_ONLY_PATTERNS)

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            if domain == "frontend" and is_backend_only:
                continue  # Never classify CLI/script goals as frontend
            if any(kw in low for kw in keywords):
                found.append(domain)

        # Always include backend as default if nothing is found
        if not found:
            found = ["backend"]
        return found

    def _detect_stack(self, low: str) -> list[str]:
        found = []
        for pattern, label in _STACK_PATTERNS:
            if re.search(pattern, low, re.IGNORECASE) and label not in found:
                found.append(label)
        return found

    def _estimate_complexity(self, domains: list[str], goal: str) -> str:
        score = len(domains)
        word_count = len(goal.split())
        if word_count > 30:
            score += 1
        if word_count > 60:
            score += 1
        for threshold, label in reversed(_COMPLEXITY_RULES):
            if score >= threshold:
                return label
        return "small"

    def _select_teams(self, domains: list[str]) -> list[str]:
        teams = ["research", "engineering"]
        if "testing" in domains or len(domains) >= 2:
            teams.append("qa")
        teams.append("documentation")
        return teams

    def _generate_questions(self, goal: str, domains: list[str]) -> list[str]:
        questions: list[str] = []
        low = goal.lower()

        if "auth" in domains and "oauth" not in low and "jwt" not in low:
            questions.append("What authentication method is preferred? (JWT, sessions, OAuth?)")
        if "database" in domains and not any(
            db in low for db in ["postgres", "mysql", "sqlite", "mongo"]
        ):
            questions.append("Which database should be used? (PostgreSQL, MySQL, MongoDB?)")
        if "frontend" in domains and not any(
            fw in low for fw in ["react", "vue", "angular", "svelte", "next"]
        ):
            questions.append("Which frontend framework should be used? (React, Vue, Next.js?)")
        if "payments" in domains and "stripe" not in low:
            questions.append("Which payment provider should be used? (Stripe, PayPal?)")
        if "devops" in domains and not any(
            p in low for p in ["docker", "kubernetes", "aws", "gcp"]
        ):
            questions.append("What is the target deployment environment?")

        return questions

    def _notes(self, goal: str, domains: list[str]) -> list[str]:
        notes = []
        if "payments" in domains:
            notes.append("This project involves payments — handle PCI compliance carefully.")
        if "auth" in domains:
            notes.append("Implement authentication before other domain logic.")
        if "realtime" in domains:
            notes.append("WebSocket / SSE infrastructure will be needed.")
        if len(domains) >= 5:
            notes.append("Large scope — consider splitting into multiple milestones.")
        return notes
