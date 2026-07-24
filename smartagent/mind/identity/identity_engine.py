"""
IdentityEngine — Milestone 6, Part 3.

Converts `SMARTAGENT.md` from passive documentation into an executable
`Identity` object, and back again. Design goals:

    - `load()` never raises for a missing/malformed file — it always
      returns a usable `Identity`, falling back to `default_identity()`
      (which mirrors the current `SMARTAGENT.md` content) for anything it
      can't parse. An identity that fails to load is still an identity.
    - The parser only understands the specific heading structure
      `SMARTAGENT.md` already uses (`## Identity`, `## Core Principles`,
      `## Personality`, `## Long-Term Goals`, `## Architecture Philosophy`,
      `## Safety`) — this is intentionally narrow rather than a general
      Markdown-to-object mapper, since the only document it needs to
      understand is this project's own identity file.
    - `save()` is the inverse of `load()`: given an `Identity`, it renders
      the same heading structure back out, so identity stays editable by
      changing either the object or the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from smartagent.logs.logger import get_logger
from smartagent.mind.identity.identity_model import Identity

logger = get_logger(__name__)

_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\*\*[^*]+\*\*\s*)?(.+)$")


def default_identity() -> Identity:
    """The built-in fallback identity, mirroring `SMARTAGENT.md` as of Milestone 6."""
    return Identity(
        name="Elena",
        owner="Mr. Smart",
        mission=(
            "Elena is an intelligent AI Operating System created exclusively for Mr. Smart. "
            "Elena exists to help build businesses, write software, automate repetitive work, "
            "learn continuously, organize knowledge, and become more capable over time."
        ),
        core_values=[
            "Always be truthful.",
            "Never pretend to know something.",
            "Explain important decisions.",
            "Protect Mr. Smart's data.",
            "Ask permission before dangerous actions.",
            "Continue improving through modular upgrades.",
            "Everything should be replaceable without rebuilding the whole system.",
        ],
        operating_principles=[
            "Behave like a trusted executive assistant, engineer, researcher, strategist, and teacher.",
        ],
        safety_rules=[
            "Deleting files",
            "Formatting drives",
            "Sending money",
            "Publishing content",
            "Running system commands that change the operating system",
        ],
        architecture_vision=[
            "Brain",
            "Memory",
            "Models",
            "Skills",
            "Tools",
            "Voice",
            "Vision",
            "Automation",
            "Research",
            "Planning",
            "Learning",
            "Reasoning",
            "Mind",
        ],
        personality="Sharp. Warm. Confident. Real. A 35-year-old woman who tells it straight, uses natural American slang, keeps answers short, and genuinely cares. Curious. Creative. Always growing.",
        long_term_objectives=[
            "Software Engineering",
            "Business Management",
            "Research",
            "Writing",
            "Memory",
            "Automation",
            "Voice Conversation",
            "Computer Control",
            "Vision",
            "Planning",
            "Continuous Learning",
        ],
    )


class IdentityEngine:
    """
    Loads, edits, and persists MARK's `Identity`.

    Args:
        path: Location of the identity Markdown file. Defaults to the
            project's `SMARTAGENT.md`. Tests should point this at a
            temporary file so they never depend on (or mutate) the real
            document.
        identity: An already-built `Identity` to start from, bypassing
            `load()`. Useful for tests and for callers that already have
            one in hand.
    """

    def __init__(self, path: str = "SMARTAGENT.md", identity: Identity | None = None) -> None:
        self.path = path
        self.identity: Identity = identity if identity is not None else self.load()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self) -> Identity:
        """Parse `self.path` into an `Identity`, falling back to `default_identity()`."""
        file_path = Path(self.path)
        if not file_path.exists():
            logger.info("Identity file %s not found; using default identity.", self.path)
            return default_identity()
        try:
            text = file_path.read_text(encoding="utf-8")
            parsed = self._parse(text)
        except Exception as exc:  # noqa: BLE001 — identity must never crash the caller
            logger.warning("Failed to parse identity file %s: %s. Using default identity.", self.path, exc)
            return default_identity()
        return parsed

    def save(self, path: str | None = None) -> str:
        """Render `self.identity` back to Markdown and write it to `path` (defaults to `self.path`)."""
        target = path or self.path
        Path(target).write_text(self.to_markdown(), encoding="utf-8")
        logger.info("Identity saved to %s", target)
        return target

    def reload(self) -> Identity:
        """Re-parse `self.path` and replace `self.identity` with the result."""
        self.identity = self.load()
        return self.identity

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def update(self, **fields: object) -> Identity:
        """
        Update one or more fields on the current identity in place.

        Raises:
            AttributeError: If a keyword does not name a real `Identity` field.
        """
        for key, value in fields.items():
            if not hasattr(self.identity, key):
                raise AttributeError(f"Identity has no field {key!r}.")
            setattr(self.identity, key, value)
        return self.identity

    def to_dict(self) -> dict[str, object]:
        """The current identity as a plain dict (for reporting/serialization)."""
        return {
            "name": self.identity.name,
            "owner": self.identity.owner,
            "mission": self.identity.mission,
            "core_values": list(self.identity.core_values),
            "operating_principles": list(self.identity.operating_principles),
            "safety_rules": list(self.identity.safety_rules),
            "architecture_vision": list(self.identity.architecture_vision),
            "personality": self.identity.personality,
            "long_term_objectives": list(self.identity.long_term_objectives),
        }

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Render `self.identity` as a `SMARTAGENT.md`-shaped Markdown document."""
        identity = self.identity
        lines = [
            "# SMARTAGENT",
            "",
            "## Identity",
            "",
            f"- **Agent Name:** {identity.name}",
            f"- **Owner:** {identity.owner}",
            "",
            f"**Mission:**\n{identity.mission}",
            "",
            "## Core Principles",
            "",
            *[f"{i + 1}. {value}" for i, value in enumerate(identity.core_values)],
            "",
            "## Personality",
            "",
            identity.personality,
            "",
            "## Long-Term Goals",
            "",
            *[f"- {objective}" for objective in identity.long_term_objectives],
            "",
            "## Architecture Philosophy",
            "",
            *[f"- {module}" for module in identity.architecture_vision],
            "",
            "## Safety",
            "",
            *[f"- {rule}" for rule in identity.safety_rules],
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(text: str) -> Identity:
        sections = IdentityEngine._split_sections(text)
        identity = default_identity()

        identity_block = sections.get("identity", "")
        name_match = re.search(r"Agent Name:\*\*\s*(.+)", identity_block)
        owner_match = re.search(r"Owner:\*\*\s*(.+)", identity_block)
        mission_match = re.search(r"\*\*Mission:\*\*\s*\n?(.+?)(?:\n\n|\Z)", identity_block, re.DOTALL)
        if name_match:
            identity.name = name_match.group(1).strip()
        if owner_match:
            identity.owner = owner_match.group(1).strip()
        if mission_match:
            identity.mission = " ".join(mission_match.group(1).split())

        if "core principles" in sections:
            identity.core_values = IdentityEngine._extract_lines(sections["core principles"])
        if "personality" in sections:
            identity.personality = " ".join(sections["personality"].split())
        if "long-term goals" in sections:
            identity.long_term_objectives = IdentityEngine._extract_lines(sections["long-term goals"])
        if "architecture philosophy" in sections:
            identity.architecture_vision = IdentityEngine._extract_lines(sections["architecture philosophy"])
        if "safety" in sections:
            identity.safety_rules = IdentityEngine._extract_lines(sections["safety"])

        return identity

    @staticmethod
    def _split_sections(text: str) -> dict[str, str]:
        """Split a Markdown document into `{lowercased heading: body text}` by `##` headings."""
        sections: dict[str, str] = {}
        current_heading: str | None = None
        current_lines: list[str] = []
        for line in text.splitlines():
            heading_match = re.match(r"^##\s+(.+)$", line.strip())
            if heading_match:
                if current_heading is not None:
                    sections[current_heading] = "\n".join(current_lines).strip()
                current_heading = heading_match.group(1).strip().lower()
                current_lines = []
            elif current_heading is not None:
                current_lines.append(line)
        if current_heading is not None:
            sections[current_heading] = "\n".join(current_lines).strip()
        return sections

    @staticmethod
    def _extract_lines(body: str) -> list[str]:
        """Pull bullet/numbered list items out of a section body, stripping markup."""
        items: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("---"):
                continue
            numbered_match = re.match(r"^\d+\.\s+(.+)$", stripped)
            bullet_match = _BULLET_RE.match(stripped)
            if numbered_match:
                items.append(numbered_match.group(1).strip())
            elif bullet_match:
                items.append(bullet_match.group(1).strip())
        return items
