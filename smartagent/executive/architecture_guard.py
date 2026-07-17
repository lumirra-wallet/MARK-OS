"""
ArchitectureGuard — Task #8: Pre-flight architecture checks.

Scans the workspace *before* implementation begins to catch three classes
of regression:

  1. Duplicate symbol   — class/function names the plan intends to create
                          already exist in the workspace.
  2. API route conflict — endpoint paths mentioned in the plan are already
                          registered in a ``smartagent/server/api_*.py`` file.
  3. Layer boundary     — executive-layer modules already import from the
                          server layer (``smartagent.server``), violating the
                          architecture documented in ``docs/architecture.md``.

Usage::

    guard  = ArchitectureGuard(workspace_path="/path/to/project")
    report = guard.scan(goal="build a REST API", tasks=[...])
    context.metadata["guard_report"] = report.to_dict()
    if report.blocks_execution:
        raise ArchitectureViolation(…)

All three checks are best-effort: a broken file that cannot be read is
skipped silently and a "check could not run" warning is appended instead,
so a single unreadable file never aborts the whole scan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from smartagent.logs.logger import get_logger

if TYPE_CHECKING:
    from smartagent.executive.task import Task

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Compiled regexes
# ---------------------------------------------------------------------------

# Existing source-level definitions
_DEF_CLASS_RE = re.compile(r"^class\s+([A-Z][A-Za-z0-9_]*)", re.MULTILINE)
_DEF_FUNC_RE  = re.compile(r"^def\s+([a-z_][A-Za-z0-9_]*)",  re.MULTILINE)

# Symbols mentioned in plan text ("create class Foo", "add function bar", …)
_PLAN_CLASS_RE = re.compile(
    r"(?:class|implement|create|add|introduce)\s+`?([A-Z][A-Za-z0-9_]*)`?", re.I,
)
_PLAN_FUNC_RE = re.compile(
    r"(?:function|method|def|implement|add)\s+`?([a-z_][a-z0-9_]*)\s*\(?`?",
)

# FastAPI route decorator in existing source
_ROUTE_RE = re.compile(
    r'@router\.\w+\(\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)

# Route paths mentioned in plan text
_PLAN_ROUTE_RE = re.compile(
    r'(?:endpoint|route|path)\s+`?(/[A-Za-z0-9_/{}*-]+)`?',
    re.I,
)

# Cross-layer import in executive modules
_LAYER_IMPORT_RE = re.compile(
    r"(?:from|import)\s+smartagent\.server",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class GuardReport:
    """Aggregated result of one ``ArchitectureGuard.scan()`` call."""

    issues: list[dict] = field(default_factory=list)

    @property
    def blocks_execution(self) -> bool:
        """True when at least one issue has severity ``"error"``."""
        return any(i["severity"] == "error" for i in self.issues)

    @property
    def errors(self) -> list[dict]:
        return [i for i in self.issues if i["severity"] == "error"]

    @property
    def warnings(self) -> list[dict]:
        return [i for i in self.issues if i["severity"] == "warn"]

    def to_dict(self) -> dict:
        return {
            "issues":           self.issues,
            "errors":           len(self.errors),
            "warnings":         len(self.warnings),
            "blocks_execution": self.blocks_execution,
        }


class ArchitectureViolation(Exception):
    """Raised by the Orchestrator when the guard report contains errors."""


# ---------------------------------------------------------------------------
# ArchitectureGuard
# ---------------------------------------------------------------------------

class ArchitectureGuard:
    """
    Pre-flight architecture scanner.

    Args:
        workspace_path: Root of the project to scan.  Defaults to ``cwd``.
    """

    def __init__(self, workspace_path: "str | Path | None" = None) -> None:
        import os
        self._root = Path(workspace_path or os.getcwd()).resolve()

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def scan(self, goal: str, tasks: "list[Task]") -> GuardReport:
        """
        Run all three checks and return a combined ``GuardReport``.

        Each check is isolated: a failure in one never prevents the others
        from running.  Exceptions produce a ``"warn"`` issue instead of
        propagating to the caller.
        """
        report = GuardReport()

        for check_fn, name in (
            (lambda: self._check_duplicate_symbols(goal, tasks), "duplicate_symbol"),
            (lambda: self._check_api_route_conflicts(goal, tasks), "api_route_conflict"),
            (lambda: self._check_layer_boundaries(), "layer_boundary"),
        ):
            try:
                report.issues.extend(check_fn())
            except Exception as exc:  # noqa: BLE001
                logger.warning("ArchitectureGuard: %s check failed: %s", name, exc)
                report.issues.append({
                    "severity": "warn",
                    "check":    name,
                    "detail":   f"Check could not run: {exc}",
                })

        logger.info(
            "ArchitectureGuard: scan complete — %d error(s), %d warning(s)",
            len(report.errors), len(report.warnings),
        )
        return report

    # ------------------------------------------------------------------
    # Check 1 — Duplicate symbols
    # ------------------------------------------------------------------

    def _collect_existing_symbols(self) -> set[str]:
        """Walk all ``*.py`` files and collect defined class/function names."""
        symbols: set[str] = set()
        for py in self._root.rglob("*.py"):
            try:
                src = py.read_text(encoding="utf-8", errors="replace")
                symbols.update(_DEF_CLASS_RE.findall(src))
                symbols.update(_DEF_FUNC_RE.findall(src))
            except OSError:
                pass
        return symbols

    def _extract_planned_symbols(self, goal: str, tasks: "list[Task]") -> set[str]:
        """Parse goal + task text for class/function names the plan intends to add."""
        combined = goal + "\n" + "\n".join(
            f"{t.title}\n{t.description}" for t in tasks
        )
        names: set[str] = set()
        names.update(_PLAN_CLASS_RE.findall(combined))
        names.update(_PLAN_FUNC_RE.findall(combined))
        # Discard trivially short names that produce noise
        return {s for s in names if len(s) > 3}

    def _check_duplicate_symbols(
        self, goal: str, tasks: "list[Task]"
    ) -> list[dict]:
        existing = self._collect_existing_symbols()
        planned  = self._extract_planned_symbols(goal, tasks)
        return [
            {
                "severity": "warn",
                "check":    "duplicate_symbol",
                "detail": (
                    f"Symbol '{name}' already exists in the workspace. "
                    "Ensure the plan extends it rather than re-creating it."
                ),
            }
            for name in sorted(planned & existing)
        ]

    # ------------------------------------------------------------------
    # Check 2 — API route conflicts
    # ------------------------------------------------------------------

    def _collect_registered_routes(self) -> set[str]:
        """Scan ``api_*.py`` files for existing FastAPI route paths."""
        routes: set[str] = set()
        server_dir = self._root / "smartagent" / "server"
        search_dir = server_dir if server_dir.is_dir() else self._root
        for api_file in search_dir.rglob("api_*.py"):
            try:
                src = api_file.read_text(encoding="utf-8", errors="replace")
                routes.update(_ROUTE_RE.findall(src))
            except OSError:
                pass
        return routes

    def _extract_planned_routes(self, goal: str, tasks: "list[Task]") -> set[str]:
        """Extract route paths mentioned in plan text."""
        combined = goal + "\n" + "\n".join(
            f"{t.title}\n{t.description}" for t in tasks
        )
        return set(_PLAN_ROUTE_RE.findall(combined))

    def _check_api_route_conflicts(
        self, goal: str, tasks: "list[Task]"
    ) -> list[dict]:
        existing = self._collect_registered_routes()
        planned  = self._extract_planned_routes(goal, tasks)
        issues: list[dict] = []

        for route in sorted(planned):
            if route in existing:
                issues.append({
                    "severity": "error",
                    "check":    "api_route_conflict",
                    "detail": (
                        f"Route '{route}' is already registered in an api_*.py "
                        "file. This will cause a duplicate-route error at startup."
                    ),
                })
            else:
                # Warn on prefix overlap (e.g. /models vs /models/switch)
                for ex in existing:
                    r_norm = route.rstrip("/")
                    e_norm = ex.rstrip("/")
                    if r_norm != e_norm and (
                        e_norm.startswith(r_norm + "/") or
                        r_norm.startswith(e_norm + "/")
                    ):
                        issues.append({
                            "severity": "warn",
                            "check":    "api_route_conflict",
                            "detail": (
                                f"Planned route '{route}' overlaps with existing "
                                f"route '{ex}'. Verify this is intentional."
                            ),
                        })
                        break
        return issues

    # ------------------------------------------------------------------
    # Check 3 — Layer boundaries
    # ------------------------------------------------------------------

    def _check_layer_boundaries(self) -> list[dict]:
        """
        Flag executive-layer files that already import from the server layer.

        Architecture rule: ``smartagent/executive/`` must not import from
        ``smartagent/server/``.  The Orchestrator receives server-layer
        objects via dependency injection, never via direct imports.
        """
        exec_dir = self._root / "smartagent" / "executive"
        issues: list[dict] = []
        if not exec_dir.is_dir():
            return issues

        for py in exec_dir.rglob("*.py"):
            try:
                src = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _LAYER_IMPORT_RE.search(src):
                try:
                    rel = py.relative_to(self._root)
                except ValueError:
                    rel = py
                issues.append({
                    "severity": "warn",
                    "check":    "layer_boundary",
                    "detail": (
                        f"{rel}: executive module imports from smartagent.server. "
                        "The architecture requires Executive to be independent "
                        "of the Server layer."
                    ),
                })
        return issues
