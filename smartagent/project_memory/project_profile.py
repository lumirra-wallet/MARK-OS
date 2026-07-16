"""
ProjectProfile — the data model for one project's remembered tech stack.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProjectProfile:
    """
    Remembered metadata about one project.

    Attributes:
        name:            Unique project name (slug-style, e.g. "my-fastapi-service").
        path:            Absolute path to the project root on disk.
        language:        Primary programming language (e.g. "Python", "TypeScript").
        framework:       Web / application framework (e.g. "FastAPI", "Django").
        test_runner:     Test framework (e.g. "pytest", "jest", "go test").
        package_manager: Dependency manager (e.g. "poetry", "pip", "npm", "cargo").
        database:        Primary data store (e.g. "PostgreSQL", "SQLite", "Redis").
        style_checker:   Linter / formatter (e.g. "black", "ruff", "eslint").
        preferences:     Freeform key→value pairs ("prefers_async": "true", …).
        tools:           Sorted list of tools detected / remembered.
        notes:           Freeform notes added by the user or auto-detection.
        created_at:      ISO timestamp of first save.
        updated_at:      ISO timestamp of last save.
    """

    name:            str
    path:            str
    language:        str = ""
    framework:       str = ""
    test_runner:     str = ""
    package_manager: str = ""
    database:        str = ""
    style_checker:   str = ""
    preferences:     dict[str, str] = field(default_factory=dict)
    tools:           list[str]      = field(default_factory=list)
    notes:           list[str]      = field(default_factory=list)
    created_at:      str = ""
    updated_at:      str = ""

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name":            self.name,
            "path":            self.path,
            "language":        self.language,
            "framework":       self.framework,
            "test_runner":     self.test_runner,
            "package_manager": self.package_manager,
            "database":        self.database,
            "style_checker":   self.style_checker,
            "preferences":     self.preferences,
            "tools":           self.tools,
            "notes":           self.notes,
            "created_at":      self.created_at,
            "updated_at":      self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectProfile":
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            language=data.get("language", ""),
            framework=data.get("framework", ""),
            test_runner=data.get("test_runner", ""),
            package_manager=data.get("package_manager", ""),
            database=data.get("database", ""),
            style_checker=data.get("style_checker", ""),
            preferences=data.get("preferences", {}),
            tools=data.get("tools", []),
            notes=data.get("notes", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "ProjectProfile":
        return cls.from_dict(json.loads(text))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def touch(self) -> None:
        """Update the ``updated_at`` timestamp to now."""
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    def as_ai_context(self) -> str:
        """
        Return a compact string suitable for injecting into an AI prompt.

        Example::

            Project: my-api  |  Python / FastAPI / pytest / PostgreSQL
            Preferences: prefers_async=true
            Tools: black, ruff, poetry
            Notes: Uses alembic for migrations.
        """
        parts: list[str] = [f"Project: {self.name}"]
        tech = " / ".join(
            x for x in [self.language, self.framework, self.test_runner, self.database]
            if x
        )
        if tech:
            parts.append(tech)
        lines = [" | ".join(parts)]
        if self.preferences:
            kv = ", ".join(f"{k}={v}" for k, v in self.preferences.items())
            lines.append(f"Preferences: {kv}")
        if self.tools:
            lines.append("Tools: " + ", ".join(self.tools))
        if self.notes:
            for note in self.notes[-3:]:  # last 3 notes
                lines.append(f"Note: {note}")
        return "\n".join(lines)

    def as_display_lines(self) -> list[str]:
        """Rich multiline display for the console."""
        lines = [
            f"  Project   : {self.name}",
            f"  Path      : {self.path}",
        ]
        for label, val in [
            ("Language", self.language),
            ("Framework", self.framework),
            ("Tests", self.test_runner),
            ("Packages", self.package_manager),
            ("Database", self.database),
            ("Style", self.style_checker),
        ]:
            if val:
                lines.append(f"  {label:<10}: {val}")
        if self.tools:
            lines.append(f"  Tools     : {', '.join(self.tools)}")
        if self.preferences:
            for k, v in self.preferences.items():
                lines.append(f"  Pref      : {k} = {v}")
        if self.notes:
            lines.append(f"  Notes     :")
            for note in self.notes:
                lines.append(f"    · {note}")
        if self.updated_at:
            lines.append(f"  Updated   : {self.updated_at}")
        return lines
