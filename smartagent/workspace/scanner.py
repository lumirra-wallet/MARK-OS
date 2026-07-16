"""
ProjectScanner — Milestone 18: Workspace Intelligence.

Scans an arbitrary project directory and builds MARK's "mental model":

  • file_graph      — directory tree with language detection and file sizes
  • import_graph    — Python AST-level import relationships between modules
  • module_map      — module-name → file-path mapping
  • dep_graph       — declared dependencies from requirements.txt / pyproject.toml etc.
  • git_status      — current branch, staged/unstaged/untracked changes
  • summary         — language breakdown, file counts, test counts, architecture guess

Usage::

    from smartagent.workspace.scanner import ProjectScanner

    scanner = ProjectScanner("/path/to/project")
    snapshot = scanner.scan()
    print("\\n".join(snapshot.as_display_lines()))
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXT_LANGUAGE: dict[str, str] = {
    ".py":   "Python",
    ".js":   "JavaScript",
    ".ts":   "TypeScript",
    ".tsx":  "TypeScript",
    ".jsx":  "JavaScript",
    ".java": "Java",
    ".go":   "Go",
    ".rs":   "Rust",
    ".cpp":  "C++",
    ".c":    "C",
    ".h":    "C/C++",
    ".cs":   "C#",
    ".rb":   "Ruby",
    ".php":  "PHP",
    ".html": "HTML",
    ".css":  "CSS",
    ".scss": "SCSS",
    ".sql":  "SQL",
    ".sh":   "Shell",
    ".yaml": "YAML",
    ".yml":  "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".md":   "Markdown",
    ".rst":  "reStructuredText",
    ".txt":  "Text",
    ".xml":  "XML",
}

# Directories that should never be walked
_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", ".venv", "venv", "env", ".env",
    "node_modules", ".mypy_cache", ".pytest_cache", ".tox",
    "dist", "build", ".eggs", ".idea", ".vscode",
})


def _detect_language(filepath: str) -> str:
    """Return the human-readable language name for a file path."""
    ext = os.path.splitext(filepath)[1].lower()
    return _EXT_LANGUAGE.get(ext, "Other")


def _is_test_path(rel_path: str) -> bool:
    """Return True if *rel_path* looks like a test file."""
    parts = rel_path.replace("\\", "/").split("/")
    basename = os.path.basename(rel_path)
    return (
        basename.startswith("test_")
        or basename.endswith("_test.py")
        or any(p in {"tests", "test", "spec", "__tests__"} for p in parts)
    )


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FileNode:
    """One file in the project."""
    path: str          # relative to scan root
    language: str
    size: int          # bytes
    is_test: bool


@dataclass
class ImportEdge:
    """One import statement discovered in a Python file."""
    from_file: str     # relative source path
    to_module: str     # raw module name (e.g. ``"os"`` or ``"smartagent.brain"``)
    is_relative: bool  # True for ``from . import x``


@dataclass
class ProjectSnapshot:
    """
    MARK's complete mental model of a project directory.

    All path attributes are relative to ``root`` unless otherwise noted.
    """

    root: str
    scanned_at: str

    # File graph
    files: list[FileNode] = field(default_factory=list)

    # Language breakdown  { "Python": 42, "Markdown": 5, ... }
    languages: dict[str, int] = field(default_factory=dict)

    # Import graph
    import_edges: list[ImportEdge] = field(default_factory=list)

    # Module map  { "smartagent.brain.agent": "smartagent/brain/agent.py" }
    module_map: dict[str, str] = field(default_factory=dict)

    # Dependencies  { "fastapi": ">=0.100", "pydantic": "*" }
    dependencies: dict[str, str] = field(default_factory=dict)

    # Git info
    git_branch: str = ""
    git_commit: str = ""
    git_status_lines: list[str] = field(default_factory=list)
    git_available: bool = False

    # Summary stats (populated by _compute_summary)
    file_count: int = 0
    test_count: int = 0
    architecture: str = "Unknown"
    primary_language: str = ""

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def python_files(self) -> list[FileNode]:
        """All Python source files (non-test)."""
        return [f for f in self.files if f.language == "Python" and not f.is_test]

    @property
    def test_files(self) -> list[FileNode]:
        """All test files."""
        return [f for f in self.files if f.is_test]

    def as_display_lines(self) -> list[str]:
        """Format the snapshot as a human-readable console report."""
        lines: list[str] = [
            f"Project Scan — {self.root}",
            "─" * 60,
            f"  Scanned     : {self.scanned_at}",
            f"  Architecture: {self.architecture}",
            f"  Files       : {self.file_count}",
            f"  Tests       : {self.test_count}",
        ]

        # Languages
        if self.languages:
            top = sorted(self.languages.items(), key=lambda x: x[1], reverse=True)[:6]
            lang_str = "  ".join(f"{lang}: {cnt}" for lang, cnt in top)
            lines.append(f"  Languages   : {lang_str}")

        # Primary language
        if self.primary_language:
            lines.append(f"  Primary     : {self.primary_language}")

        # Dependencies
        if self.dependencies:
            lines.append("")
            lines.append(f"  Dependencies ({len(self.dependencies)}):")
            for pkg, spec in sorted(self.dependencies.items())[:15]:
                spec_str = spec if spec and spec != "*" else "(any)"
                lines.append(f"    {pkg:<30s} {spec_str}")
            if len(self.dependencies) > 15:
                lines.append(f"    … and {len(self.dependencies) - 15} more")

        # Git status
        if self.git_available:
            lines.append("")
            lines.append("  Git Status:")
            lines.append(f"    Branch: {self.git_branch or '(detached)'}")
            if self.git_commit:
                lines.append(f"    Commit: {self.git_commit}")
            if self.git_status_lines:
                lines.append(f"    Changes ({len(self.git_status_lines)}):")
                for s in self.git_status_lines[:10]:
                    lines.append(f"      {s}")
                if len(self.git_status_lines) > 10:
                    lines.append(f"      … and {len(self.git_status_lines) - 10} more")
            else:
                lines.append("    Working tree clean.")

        # Import graph summary
        if self.import_edges:
            lines.append("")
            lines.append(f"  Import graph: {len(self.import_edges)} edges")

        # Module map summary
        if self.module_map:
            lines.append(f"  Module map  : {len(self.module_map)} modules")

        lines.append("")
        lines.append("  Use 'workspace status' to see generated output files.")
        return lines

    def as_summary_text(self) -> str:
        """Return a compact text summary suitable for injecting into prompts."""
        parts: list[str] = [
            f"Project: {os.path.basename(self.root)}",
            f"Architecture: {self.architecture}",
            f"Primary language: {self.primary_language}",
            f"Files: {self.file_count}  Tests: {self.test_count}",
        ]
        if self.languages:
            top = sorted(self.languages.items(), key=lambda x: x[1], reverse=True)[:4]
            parts.append("Languages: " + ", ".join(f"{l}({c})" for l, c in top))
        if self.dependencies:
            deps = list(self.dependencies.keys())[:10]
            parts.append("Dependencies: " + ", ".join(deps))
        if self.git_available and self.git_branch:
            parts.append(f"Git branch: {self.git_branch}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

class ProjectScanner:
    """
    Scan a project directory and build a :class:`ProjectSnapshot`.

    Args:
        root:            Directory to scan.  Defaults to current working directory.
        max_file_size:   Skip files larger than this (bytes).  Default 1 MB.
        follow_symlinks: Whether to follow symlinks during directory walk.
    """

    def __init__(
        self,
        root: str = ".",
        *,
        max_file_size: int = 1_000_000,
        follow_symlinks: bool = False,
    ) -> None:
        self._root = os.path.abspath(root)
        self._max_file_size = max_file_size
        self._follow_symlinks = follow_symlinks

    @property
    def root(self) -> str:
        """Absolute path to the project root."""
        return self._root

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scan(self) -> ProjectSnapshot:
        """
        Run a full project scan and return a :class:`ProjectSnapshot`.

        Steps:
          1. Walk the directory tree and collect :class:`FileNode` records.
          2. Build the module map from Python files.
          3. Parse Python AST imports.
          4. Parse dependency manifests.
          5. Query git status.
          6. Detect architecture pattern.
          7. Compute final summary stats.
        """
        snap = ProjectSnapshot(
            root=self._root,
            scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._collect_files(snap)
        self._build_module_map(snap)
        self._collect_imports(snap)
        self._collect_dependencies(snap)
        self._collect_git(snap)
        self._detect_architecture(snap)
        self._compute_summary(snap)
        logger.info(
            "ProjectScanner: scanned %r — %d files, %d tests, %d deps",
            self._root, snap.file_count, snap.test_count, len(snap.dependencies),
        )
        return snap

    # ------------------------------------------------------------------
    # Step 1 — file collection
    # ------------------------------------------------------------------

    def _collect_files(self, snap: ProjectSnapshot) -> None:
        """Walk the directory tree and populate snap.files and snap.languages."""
        for dirpath, dirnames, filenames in os.walk(
            self._root, followlinks=self._follow_symlinks
        ):
            # Prune ignored directories in-place so os.walk doesn't descend
            dirnames[:] = [
                d for d in dirnames
                if d not in _IGNORE_DIRS and not d.endswith(".egg-info")
            ]

            for fname in filenames:
                full = os.path.join(dirpath, fname)
                rel  = os.path.relpath(full, self._root)

                # Skip files that are too large
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                if size > self._max_file_size:
                    continue

                lang     = _detect_language(fname)
                is_test  = _is_test_path(rel)
                node     = FileNode(path=rel, language=lang, size=size, is_test=is_test)
                snap.files.append(node)
                snap.languages[lang] = snap.languages.get(lang, 0) + 1

    # ------------------------------------------------------------------
    # Step 2 — module map
    # ------------------------------------------------------------------

    def _build_module_map(self, snap: ProjectSnapshot) -> None:
        """
        Build snap.module_map: module_dotted_name → relative_file_path.

        Derived from Python files using their path relative to the project root.
        e.g. ``smartagent/brain/agent.py`` → ``"smartagent.brain.agent"``.
        """
        for node in snap.files:
            if node.language != "Python":
                continue
            rel = node.path.replace("\\", "/")
            if not rel.endswith(".py"):
                continue
            # Convert path to module name
            module = rel[:-3].replace("/", ".")
            if module.endswith(".__init__"):
                module = module[: -len(".__init__")]
            snap.module_map[module] = node.path

    # ------------------------------------------------------------------
    # Step 3 — import graph
    # ------------------------------------------------------------------

    def _collect_imports(self, snap: ProjectSnapshot) -> None:
        """Parse Python AST imports for each Python source file."""
        for node in snap.files:
            if node.language != "Python":
                continue
            full = os.path.join(self._root, node.path)
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    source = f.read()
                tree = ast.parse(source, filename=node.path)
            except (SyntaxError, OSError):
                continue

            for ast_node in ast.walk(tree):
                if isinstance(ast_node, ast.Import):
                    for alias in ast_node.names:
                        snap.import_edges.append(
                            ImportEdge(
                                from_file=node.path,
                                to_module=alias.name,
                                is_relative=False,
                            )
                        )
                elif isinstance(ast_node, ast.ImportFrom):
                    module = ast_node.module or ""
                    is_rel = (ast_node.level or 0) > 0
                    if is_rel:
                        module = "." * ast_node.level + module
                    snap.import_edges.append(
                        ImportEdge(
                            from_file=node.path,
                            to_module=module,
                            is_relative=is_rel,
                        )
                    )

    # ------------------------------------------------------------------
    # Step 4 — dependency manifests
    # ------------------------------------------------------------------

    def _collect_dependencies(self, snap: ProjectSnapshot) -> None:
        """Parse requirements.txt, pyproject.toml, setup.cfg, and package.json."""
        self._parse_requirements(snap, "requirements.txt")
        self._parse_requirements(snap, "requirements-dev.txt")
        self._parse_requirements(snap, "requirements-test.txt")
        self._parse_pyproject_toml(snap)
        self._parse_setup_cfg(snap)
        self._parse_package_json(snap)

    def _parse_requirements(self, snap: ProjectSnapshot, filename: str) -> None:
        """Parse a requirements.txt-style file."""
        path = os.path.join(self._root, filename)
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # e.g. "fastapi>=0.100.0" or "pydantic[email]==2.0"
                    m = re.match(r'^([A-Za-z0-9_.\-]+)\s*([><=!~^.*].+)?', line)
                    if m:
                        pkg  = m.group(1).lower().replace("-", "_")
                        spec = (m.group(2) or "*").strip()
                        snap.dependencies[pkg] = spec
        except OSError:
            pass

    def _parse_pyproject_toml(self, snap: ProjectSnapshot) -> None:
        """Parse dependencies from pyproject.toml without a TOML library."""
        path = os.path.join(self._root, "pyproject.toml")
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return

        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped in ('[project]', '[tool.poetry.dependencies]',
                            '[tool.poetry.dev-dependencies]'):
                in_deps = True
                continue
            if stripped.startswith("[") and stripped.endswith("]") and in_deps:
                in_deps = False
                continue
            if not in_deps:
                continue
            # Match: "fastapi = '>=0.100'" or '"fastapi": ">=0.100"'
            m = re.match(r'["\']?([A-Za-z0-9_.\-]+)["\']?\s*[=:]\s*["\']?([^"\'#\n]+)?', stripped)
            if m:
                pkg  = m.group(1).lower().replace("-", "_")
                spec = (m.group(2) or "*").strip().strip('"\'')
                if pkg and pkg not in {"python", "name", "version", "description"}:
                    snap.dependencies[pkg] = spec

    def _parse_setup_cfg(self, snap: ProjectSnapshot) -> None:
        """Parse install_requires from setup.cfg."""
        path = os.path.join(self._root, "setup.cfg")
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            return

        in_requires = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "install_requires =":
                in_requires = True
                continue
            if stripped.startswith("[") or (stripped and not line.startswith(" ") and not line.startswith("\t")):
                in_requires = False
                continue
            if in_requires and stripped:
                m = re.match(r'([A-Za-z0-9_.\-]+)\s*([><=!~^.*].+)?', stripped)
                if m:
                    pkg  = m.group(1).lower().replace("-", "_")
                    spec = (m.group(2) or "*").strip()
                    snap.dependencies[pkg] = spec

    def _parse_package_json(self, snap: ProjectSnapshot) -> None:
        """Parse dependencies from package.json."""
        path = os.path.join(self._root, "package.json")
        if not os.path.isfile(path):
            return
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for section in ("dependencies", "devDependencies"):
                for pkg, spec in (data.get(section) or {}).items():
                    key = pkg.lower().replace("-", "_")
                    snap.dependencies[key] = spec
        except (OSError, Exception):  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Step 5 — git status
    # ------------------------------------------------------------------

    def _collect_git(self, snap: ProjectSnapshot) -> None:
        """Query git for branch, last commit, and working-tree status."""
        def _git(*args: str) -> tuple[str, bool]:
            try:
                result = subprocess.run(
                    ["git"] + list(args),
                    capture_output=True,
                    text=True,
                    cwd=self._root,
                    timeout=5,
                )
                return result.stdout.strip(), result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                return "", False

        # Check if git is available and this is a git repo
        _, ok = _git("rev-parse", "--is-inside-work-tree")
        if not ok:
            snap.git_available = False
            return

        snap.git_available = True

        branch, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
        snap.git_branch = branch

        commit, _ = _git("log", "--oneline", "-1")
        snap.git_commit = commit

        status_out, _ = _git("status", "--porcelain")
        if status_out:
            snap.git_status_lines = [
                line for line in status_out.splitlines() if line.strip()
            ]

    # ------------------------------------------------------------------
    # Step 6 — architecture detection
    # ------------------------------------------------------------------

    def _detect_architecture(self, snap: ProjectSnapshot) -> None:
        """
        Heuristically detect the project's architecture pattern from directory names.

        Patterns detected (in priority order):
          MVC       — views/ + models/ + controllers/ (or routes/)
          DDD       — domain/ + services/ + (repositories/ or repos/)
          Clean     — usecases/ + entities/ + adapters/
          Layered   — api/ + core/ (or domain/) + db/ (or infrastructure/)
          Flat      — all source in a single directory
          Standard  — conventional Python package layout
        """
        dirs: set[str] = set()
        for node in snap.files:
            parts = node.path.replace("\\", "/").split("/")
            dirs.update(parts[:-1])  # all directory components (not the filename)

        d = dirs  # shorthand

        if {"views", "models"} & d and {"controllers", "routes"} & d:
            snap.architecture = "MVC"
        elif "domain" in d and "services" in d:
            snap.architecture = "DDD"
        elif "usecases" in d and "entities" in d:
            snap.architecture = "Clean Architecture"
        elif "api" in d and ("core" in d or "db" in d):
            snap.architecture = "Layered"
        elif len(d) <= 2:
            snap.architecture = "Flat"
        else:
            snap.architecture = "Standard Package"

    # ------------------------------------------------------------------
    # Step 7 — summary stats
    # ------------------------------------------------------------------

    def _compute_summary(self, snap: ProjectSnapshot) -> None:
        """Compute final aggregate statistics for the snapshot."""
        snap.file_count = len(snap.files)
        snap.test_count = sum(1 for f in snap.files if f.is_test)

        if snap.languages:
            snap.primary_language = max(
                snap.languages.items(), key=lambda x: x[1]
            )[0]
