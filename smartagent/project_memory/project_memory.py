"""
ProjectMemory — Milestone 22: Project Memory.

MARK remembers every project it works in.  Profiles are stored as JSON files
under a configurable base directory (default: ``project_memory/``).

Key features
────────────
- ``load(name, path)``   — load or create a profile for a project
- ``save(profile)``      — persist a profile to disk
- ``set(profile, k, v)`` — set a known field or a freeform preference
- ``get(profile, k)``    — read a field value
- ``scan(profile)``      — auto-detect tech stack by inspecting project files
- ``summary(profile)``   — compact text for console display
- ``ai_context(profile)``— compact text for injection into AI prompts
- ``list_projects()``    — list all remembered projects
- ``delete(name)``       — remove a project profile
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from smartagent.logs.logger import get_logger
from smartagent.project_memory.project_profile import ProjectProfile

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Known field names that map to first-class ProjectProfile attributes
# ---------------------------------------------------------------------------
_FIELD_NAMES: frozenset[str] = frozenset({
    "language", "framework", "test_runner", "package_manager",
    "database", "style_checker",
})

# ---------------------------------------------------------------------------
# File-pattern → tech-stack inference rules
# ---------------------------------------------------------------------------
_DETECT_RULES: list[tuple[str, str, str, str]] = [
    # (filename_pattern, field, value, description)
    # Language
    (r"\.py$",             "language",        "Python",     ""),
    (r"\.ts$|\.tsx$",      "language",        "TypeScript", ""),
    (r"\.js$|\.jsx$",      "language",        "JavaScript", ""),
    (r"\.go$",             "language",        "Go",         ""),
    (r"\.rs$",             "language",        "Rust",       ""),
    (r"\.rb$",             "language",        "Ruby",       ""),
    (r"\.java$",           "language",        "Java",       ""),
    # Framework (config files)
    (r"pyproject\.toml$",  "package_manager", "poetry",     ""),
    (r"poetry\.lock$",     "package_manager", "poetry",     ""),
    (r"requirements\.txt$","package_manager", "pip",        ""),
    (r"setup\.py$",        "package_manager", "pip",        ""),
    (r"Pipfile$",          "package_manager", "pipenv",     ""),
    (r"package\.json$",    "package_manager", "npm",        ""),
    (r"pnpm-lock\.yaml$",  "package_manager", "pnpm",       ""),
    (r"Cargo\.toml$",      "package_manager", "cargo",      ""),
    (r"go\.mod$",          "package_manager", "go modules", ""),
    (r"Gemfile$",          "package_manager", "bundler",    ""),
    # Test runners
    (r"pytest\.ini$|conftest\.py$", "test_runner", "pytest", ""),
    (r"jest\.config\.",    "test_runner", "jest",      ""),
    (r"vitest\.config\.",  "test_runner", "vitest",    ""),
    (r"\.rspec$",          "test_runner", "rspec",     ""),
    # Databases
    (r"alembic\.ini$",     "database",  "PostgreSQL (alembic)", ""),
    (r"migrations/",       "database",  "SQL (migrations dir)", ""),
    # Style
    (r"\.flake8$|setup\.cfg$", "style_checker", "flake8",  ""),
    (r"pyproject\.toml$",      "style_checker", "black",   ""),   # best-guess
    (r"\.eslintrc",            "style_checker", "eslint",  ""),
    (r"\.prettierrc",          "style_checker", "prettier",""),
    (r"rustfmt\.toml$",        "style_checker", "rustfmt", ""),
]

# Patterns to search inside file content
_CONTENT_RULES: list[tuple[str, str, str, str]] = [
    # (file_pattern, content_regex, field, value)
    (r"pyproject\.toml$",   r"fastapi",         "framework", "FastAPI"),
    (r"pyproject\.toml$",   r"django",          "framework", "Django"),
    (r"pyproject\.toml$",   r"flask",           "framework", "Flask"),
    (r"pyproject\.toml$",   r"sqlalchemy",      "tools",     "SQLAlchemy"),
    (r"pyproject\.toml$",   r"alembic",         "tools",     "Alembic"),
    (r"pyproject\.toml$",   r'"black"',         "style_checker", "black"),
    (r"pyproject\.toml$",   r'"ruff"',          "style_checker", "ruff"),
    (r"pyproject\.toml$",   r'"pytest"',        "test_runner",   "pytest"),
    (r"pyproject\.toml$",   r'"asyncpg"|"psycopg2"', "database", "PostgreSQL"),
    (r"requirements\.txt$", r"fastapi",         "framework", "FastAPI"),
    (r"requirements\.txt$", r"django",          "framework", "Django"),
    (r"requirements\.txt$", r"flask",           "framework", "Flask"),
    (r"requirements\.txt$", r"sqlalchemy",      "tools",     "SQLAlchemy"),
    (r"requirements\.txt$", r"psycopg2|asyncpg","database",  "PostgreSQL"),
    (r"requirements\.txt$", r"pymysql|mysql",   "database",  "MySQL"),
    (r"requirements\.txt$", r"motor|pymongo",   "database",  "MongoDB"),
    (r"requirements\.txt$", r"redis",           "tools",     "Redis"),
    (r"package\.json$",     r'"next"',          "framework", "Next.js"),
    (r"package\.json$",     r'"react"',         "framework", "React"),
    (r"package\.json$",     r'"vue"',           "framework", "Vue"),
    (r"package\.json$",     r'"express"',       "framework", "Express"),
    (r"package\.json$",     r'"prisma"',        "tools",     "Prisma"),
    (r"package\.json$",     r'"drizzle-orm"',   "tools",     "Drizzle ORM"),
]


class ProjectMemory:
    """
    Stores and retrieves per-project tech-stack profiles.

    Args:
        base_path: Directory for JSON profile storage.  Created if absent.
    """

    def __init__(self, base_path: str = "project_memory") -> None:
        self._base_path = os.path.abspath(base_path)
        os.makedirs(self._base_path, exist_ok=True)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _profile_path(self, name: str) -> str:
        safe = re.sub(r"[^\w\-.]", "_", name)
        return os.path.join(self._base_path, f"{safe}.json")

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self, name: str, path: str = "") -> ProjectProfile:
        """
        Load an existing profile or create a new blank one.

        Args:
            name: Project slug (e.g. ``"my-fastapi-service"``).
            path: Filesystem path to the project root.
        """
        fpath = self._profile_path(name)
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    profile = ProjectProfile.from_dict(json.load(f))
                if path and not profile.path:
                    profile.path = os.path.abspath(path)
                return profile
            except Exception as exc:
                logger.warning("ProjectMemory: failed to load %r: %s", fpath, exc)

        profile = ProjectProfile(
            name=name,
            path=os.path.abspath(path) if path else "",
        )
        profile.touch()
        self.save(profile)
        return profile

    def save(self, profile: ProjectProfile) -> None:
        """Persist *profile* to disk."""
        profile.touch()
        fpath = self._profile_path(profile.name)
        try:
            with open(fpath, "w") as f:
                json.dump(profile.to_dict(), f, indent=2)
            logger.debug("ProjectMemory: saved %r → %s", profile.name, fpath)
        except Exception as exc:
            logger.error("ProjectMemory: failed to save %r: %s", profile.name, exc)

    # ------------------------------------------------------------------
    # Get / set
    # ------------------------------------------------------------------

    def set(self, profile: ProjectProfile, key: str, value: str) -> None:
        """
        Set a field on *profile* and persist.

        Known fields (language, framework, test_runner, package_manager,
        database, style_checker) are set directly.  Unknown keys are stored
        in ``profile.preferences``.

        Special keys:
          - ``"tool"``  → appends to ``profile.tools``
          - ``"note"``  → appends to ``profile.notes``
        """
        key = key.lower().strip().replace("-", "_").replace(" ", "_")
        if key == "tool":
            if value not in profile.tools:
                profile.tools.append(value)
                profile.tools.sort()
        elif key == "note":
            profile.notes.append(value)
        elif key in _FIELD_NAMES:
            setattr(profile, key, value)
        else:
            profile.preferences[key] = value
        self.save(profile)

    def get(self, profile: ProjectProfile, key: str) -> str:
        """
        Read a field value.  Returns ``""`` if not set.
        """
        key = key.lower().strip().replace("-", "_").replace(" ", "_")
        if key in _FIELD_NAMES:
            return getattr(profile, key, "")
        if key == "tools":
            return ", ".join(profile.tools)
        if key == "notes":
            return "; ".join(profile.notes)
        return profile.preferences.get(key, "")

    # ------------------------------------------------------------------
    # Auto-detection
    # ------------------------------------------------------------------

    def scan(self, profile: ProjectProfile, max_files: int = 500) -> list[str]:
        """
        Walk *profile.path* and infer the tech stack from filenames and
        a subset of file contents.

        Returns:
            List of human-readable strings describing what was detected.
        """
        if not profile.path or not os.path.isdir(profile.path):
            return ["[scan] Project path not set or does not exist."]

        detected: list[str] = []
        files_seen = 0

        for root, dirs, files in os.walk(profile.path):
            # Skip hidden and common noise dirs
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in {"__pycache__", "node_modules", ".git", "venv", ".venv"}
            ]
            for fname in files:
                if files_seen >= max_files:
                    break
                files_seen += 1
                rel = os.path.relpath(os.path.join(root, fname), profile.path)

                # Filename-pattern rules — check ALL rules (no break) so a
                # single file (e.g. conftest.py) can match both the language
                # rule (Python) and the test-runner rule (pytest).
                for pattern, field, value, _ in _DETECT_RULES:
                    if re.search(pattern, rel, re.IGNORECASE):
                        current = self.get(profile, field)
                        if not current:
                            self.set(profile, field, value)
                            detected.append(f"Detected {field}: {value}  (from {rel})")

                # Content rules — only for key config files
                fpath = os.path.join(root, fname)
                for file_pat, content_re, field, value in _CONTENT_RULES:
                    if re.search(file_pat, rel, re.IGNORECASE):
                        try:
                            with open(fpath, errors="ignore") as f:
                                content = f.read(4096)
                            if re.search(content_re, content, re.IGNORECASE):
                                if field == "tools":
                                    if value not in profile.tools:
                                        self.set(profile, "tool", value)
                                        detected.append(f"Detected tool: {value}  (from {rel})")
                                else:
                                    current = self.get(profile, field)
                                    if not current:
                                        self.set(profile, field, value)
                                        detected.append(f"Detected {field}: {value}  (from {rel})")
                        except Exception:
                            pass

        self.save(profile)
        if not detected:
            detected.append("No new tech-stack signals detected.")
        return detected

    # ------------------------------------------------------------------
    # List / delete
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectProfile]:
        """Return all saved profiles, sorted by name."""
        profiles: list[ProjectProfile] = []
        if not os.path.isdir(self._base_path):
            return profiles
        for fname in sorted(os.listdir(self._base_path)):
            if fname.endswith(".json"):
                fpath = os.path.join(self._base_path, fname)
                try:
                    with open(fpath) as f:
                        profiles.append(ProjectProfile.from_dict(json.load(f)))
                except Exception as exc:
                    logger.warning("ProjectMemory: skipping %s: %s", fname, exc)
        return profiles

    def delete(self, name: str) -> bool:
        """Delete a project profile.  Returns True if it existed."""
        fpath = self._profile_path(name)
        if os.path.exists(fpath):
            os.remove(fpath)
            return True
        return False

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def ai_context(self, profile: ProjectProfile) -> str:
        """Return a compact string for injection into AI prompts."""
        return profile.as_ai_context()

    def summary(self, profile: ProjectProfile) -> str:
        """Return a one-line console summary."""
        tech = " / ".join(
            x for x in [
                profile.language, profile.framework,
                profile.test_runner, profile.database,
            ] if x
        )
        parts = [f"{profile.name}"]
        if tech:
            parts.append(tech)
        if profile.package_manager:
            parts.append(f"({profile.package_manager})")
        return "  " + "  ·  ".join(parts)

    def inject_into_context(self, profile: ProjectProfile, context_meta: dict) -> None:
        """
        Inject project profile data into an ``ExecutionContext.metadata`` dict.

        Workers that check ``context.metadata.get("project_profile")`` will
        automatically receive the active project context.
        """
        context_meta["project_profile"] = profile
        context_meta["project_ai_context"] = profile.as_ai_context()
