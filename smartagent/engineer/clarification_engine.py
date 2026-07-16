"""
ClarificationEngine — Milestone 25: Full Software Engineer.

Turns open questions from RequirementAnalyzer into a prioritized, minimal
set of clarification prompts.  MARK asks only necessary questions — not a
survey.

Usage::

    engine = ClarificationEngine()
    cset = engine.from_report(report)
    for q in cset.questions:
        print(q.prompt)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClarificationQuestion:
    """
    One clarification question MARK needs answered before proceeding.

    Attributes:
        id:       Short slug identifier (e.g. ``"auth_method"``).
        prompt:   The question text shown to the user.
        domain:   Which domain this relates to (e.g. ``"auth"``).
        required: If True, MARK will block and wait; False = optional.
        default:  The assumed value if the user provides no answer.
    """
    id:       str
    prompt:   str
    domain:   str  = ""
    required: bool = False
    default:  str  = ""


@dataclass
class ClarificationSet:
    """
    Collection of clarification questions for one goal.

    Attributes:
        questions:    Ordered list of questions (priority-sorted).
        goal:         Original goal string.
        answered:     Filled in when the user provides answers.
    """
    goal:      str
    questions: list[ClarificationQuestion] = field(default_factory=list)
    answered:  dict[str, str]              = field(default_factory=dict)

    @property
    def has_required(self) -> bool:
        """True when there is at least one unanswered required question."""
        return any(
            q.required and q.id not in self.answered
            for q in self.questions
        )

    def answer(self, qid: str, value: str) -> None:
        """Record an answer for a question by its ``id``."""
        self.answered[qid] = value

    def answer_all_with_defaults(self) -> None:
        """Fill unanswered questions with their default values."""
        for q in self.questions:
            if q.id not in self.answered and q.default:
                self.answered[q.id] = q.default

    def as_display_lines(self) -> list[str]:
        if not self.questions:
            return ["  No clarification needed — proceeding with analysis."]
        lines = [f"  Clarification needed for: {self.goal[:72]}", ""]
        for i, q in enumerate(self.questions, 1):
            req = " (required)" if q.required else ""
            lines.append(f"  {i}. {q.prompt}{req}")
            if q.default:
                lines.append(f"     Default: {q.default}")
        return lines

    def as_context(self) -> str:
        """Return answered values as a string for AI prompt injection."""
        if not self.answered:
            return ""
        parts = []
        for qid, val in self.answered.items():
            parts.append(f"{qid}: {val}")
        return "User clarifications: " + "; ".join(parts)


class ClarificationEngine:
    """
    Turns open questions from :class:`RequirementReport` into a minimal,
    prioritized :class:`ClarificationSet`.

    MARK does not ask questions it can reasonably assume — only questions
    where the answer changes the architecture significantly.
    """

    def __init__(self, model_manager: Any | None = None) -> None:
        self._model_manager = model_manager

    def from_report(self, report: Any) -> ClarificationSet:
        """
        Build a :class:`ClarificationSet` from a :class:`RequirementReport`.
        """
        questions: list[ClarificationQuestion] = []
        open_q = getattr(report, "open_questions", [])
        domains = getattr(report, "domains", [])
        goal = getattr(report, "goal", "")

        # Convert open_questions from RequirementReport into ClarificationQuestion objects
        for i, q_text in enumerate(open_q[:5]):  # cap at 5
            domain = _infer_domain(q_text, domains)
            qid = f"q_{i}_{domain or 'general'}"
            default = _infer_default(q_text)
            questions.append(ClarificationQuestion(
                id=qid,
                prompt=q_text,
                domain=domain,
                required=(i == 0 and bool(open_q)),  # only the first is required
                default=default,
            ))

        # Sort: required first, then by domain priority
        questions.sort(key=lambda q: (0 if q.required else 1, q.domain))

        return ClarificationSet(goal=goal, questions=questions)

    def interactive_prompt(self, cset: ClarificationSet) -> ClarificationSet:
        """
        Display questions and collect answers from stdin.
        Non-interactive environments (CI, tests) should call
        ``cset.answer_all_with_defaults()`` instead.

        Returns the same ``cset`` with ``answered`` populated.
        """
        if not cset.questions:
            return cset
        print(f"\nMARK has {len(cset.questions)} clarification question(s):\n")
        for q in cset.questions:
            default_hint = f" [{q.default}]" if q.default else ""
            try:
                answer = input(f"  {q.prompt}{default_hint}: ").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            cset.answer(q.id, answer or q.default)
        print()
        return cset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_domain(question: str, domains: list[str]) -> str:
    low = question.lower()
    priority = [
        ("auth", ["auth", "login", "jwt", "oauth"]),
        ("database", ["database", "db", "postgres", "mysql", "mongo"]),
        ("frontend", ["frontend", "react", "vue", "framework"]),
        ("payments", ["payment", "stripe"]),
        ("devops", ["deploy", "docker", "cloud"]),
    ]
    for domain, keywords in priority:
        if any(kw in low for kw in keywords):
            return domain
    # Fall back to the first domain in the report
    return domains[0] if domains else "general"


def _infer_default(question: str) -> str:
    """Guess a sensible default answer for common question types."""
    low = question.lower()
    if "auth" in low:
        return "JWT"
    if "database" in low:
        return "PostgreSQL"
    if "frontend" in low or "framework" in low:
        return "React"
    if "payment" in low:
        return "Stripe"
    if "deploy" in low or "cloud" in low:
        return "Docker"
    return ""
