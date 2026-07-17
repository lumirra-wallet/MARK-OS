"""
Workspace analyzer — runs once when a client connects.

Gathers project type, frameworks, Git info, test status, TODO count,
and assembles a one-line summary for the startup announcement.

All operations are fast subprocess/filesystem reads — no LLM call.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from smartagent.logs.logger import get_logger

logger = get_logger(__name__)


def analyze_workspace(workspace_path: str) -> dict[str, Any]:
    """
    Return a dict suitable for broadcasting as a ``WorkspaceAnalyzed`` event.

    Never raises — falls back gracefully on any failure.
    """
    try:
        ws = Path(workspace_path).resolve() if workspace_path and workspace_path != "." else Path.cwd()
        if not ws.exists():
            ws = Path.cwd()

        project_type  = _detect_project_type(ws)
        frameworks    = _detect_frameworks(ws, project_type)
        git_branch    = _git_branch(ws)
        last_commit   = _last_commit(ws)
        test_framework = _detect_test_framework(ws, project_type)
        todo_count    = _count_todos(ws)
        file_count    = _count_source_files(ws, project_type)
        has_ci        = _has_ci(ws)
        open_todos    = _sample_todos(ws)

        summary = _build_summary(
            project_type, frameworks, git_branch,
            test_framework, todo_count, file_count,
        )

        return {
            "project_type":    project_type,
            "frameworks":      frameworks,
            "git_branch":      git_branch,
            "last_commit":     last_commit,
            "test_framework":  test_framework,
            "todo_count":      todo_count,
            "file_count":      file_count,
            "has_ci":          has_ci,
            "open_todos":      open_todos[:5],
            "summary":         summary,
            "workspace":       str(ws),
        }
    except Exception as exc:
        logger.warning("workspace_analyzer: error during analysis: %s", exc)
        return {
            "project_type": "Unknown",
            "frameworks": [],
            "git_branch": "unknown",
            "last_commit": "",
            "test_framework": None,
            "todo_count": 0,
            "file_count": 0,
            "has_ci": False,
            "open_todos": [],
            "summary": "Workspace analysis unavailable.",
            "workspace": workspace_path or ".",
        }


# ── Project type ──────────────────────────────────────────────────────────────

def _detect_project_type(ws: Path) -> str:
    if (ws / "pyproject.toml").exists() or (ws / "setup.py").exists():
        return "Python"
    if list(ws.glob("*.py"))[:1]:
        return "Python"
    if (ws / "Cargo.toml").exists():
        return "Rust"
    if (ws / "go.mod").exists():
        return "Go"
    if (ws / "pom.xml").exists() or (ws / "build.gradle").exists():
        return "Java"
    if (ws / "package.json").exists():
        try:
            pkg = json.loads((ws / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                return "Next.js"
            if "react" in deps:
                return "React"
            if "@angular/core" in deps:
                return "Angular"
            if "vue" in deps:
                return "Vue"
            return "Node.js"
        except Exception:
            return "Node.js"
    if list(ws.glob("*.rb"))[:1]:
        return "Ruby"
    if list(ws.glob("*.php"))[:1]:
        return "PHP"
    return "Unknown"


# ── Frameworks ────────────────────────────────────────────────────────────────

def _detect_frameworks(ws: Path, project_type: str) -> list[str]:
    found: list[str] = []

    if project_type in ("Python",):
        # Check requirements.txt / pyproject.toml / setup.py
        req_text = ""
        for candidate in ["requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "Pipfile"]:
            p = ws / candidate
            if p.exists():
                try:
                    req_text += p.read_text().lower()
                except Exception:
                    pass
        for fw, keywords in [
            ("Flask",       ["flask"]),
            ("FastAPI",     ["fastapi"]),
            ("Django",      ["django"]),
            ("SQLAlchemy",  ["sqlalchemy"]),
            ("Pydantic",    ["pydantic"]),
            ("Celery",      ["celery"]),
            ("Pandas",      ["pandas"]),
            ("NumPy",       ["numpy"]),
            ("PyTorch",     ["torch"]),
            ("TensorFlow",  ["tensorflow"]),
        ]:
            if any(k in req_text for k in keywords):
                found.append(fw)

    elif "Node" in project_type or project_type in ("React", "Vue", "Angular", "Next.js"):
        try:
            pkg = json.loads((ws / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for fw, key in [
                ("Express", "express"), ("Prisma", "prisma"),
                ("TypeScript", "typescript"), ("Tailwind", "tailwindcss"),
                ("Vite", "vite"), ("Jest", "jest"), ("Vitest", "vitest"),
            ]:
                if key in deps:
                    found.append(fw)
        except Exception:
            pass

    return found[:5]


# ── Git ───────────────────────────────────────────────────────────────────────

def _git_branch(ws: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=ws, capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _last_commit(ws: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%s", "HEAD"],
            cwd=ws, capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip()[:80] or ""
    except Exception:
        return ""


# ── Tests ─────────────────────────────────────────────────────────────────────

def _detect_test_framework(ws: Path, project_type: str) -> str | None:
    if project_type == "Python":
        if list(ws.rglob("test_*.py"))[:1] or list(ws.rglob("*_test.py"))[:1]:
            return "pytest"
        if list(ws.rglob("test*.py"))[:1]:
            return "unittest"
    elif "Node" in project_type or project_type in ("React", "Vue", "Next.js"):
        try:
            pkg = json.loads((ws / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "vitest" in deps:  return "vitest"
            if "jest"   in deps:  return "jest"
            if "mocha"  in deps:  return "mocha"
        except Exception:
            pass
    elif project_type == "Rust":
        return "cargo test"
    elif project_type == "Go":
        return "go test"
    return None


# ── TODOs ─────────────────────────────────────────────────────────────────────

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b.*", re.IGNORECASE)
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".cache"}


def _walk_source(ws: Path, exts: set[str] | None = None, max_files: int = 500):
    count = 0
    for path in ws.rglob("*"):
        if count >= max_files:
            break
        if any(part in _IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if exts and path.suffix not in exts:
            continue
        count += 1
        yield path


def _count_todos(ws: Path) -> int:
    count = 0
    try:
        for p in _walk_source(ws, exts={".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}):
            try:
                text = p.read_text(errors="ignore")
                count += len(_TODO_RE.findall(text))
            except Exception:
                pass
    except Exception:
        pass
    return count


def _sample_todos(ws: Path) -> list[str]:
    todos: list[str] = []
    try:
        for p in _walk_source(ws, exts={".py", ".ts", ".tsx", ".js", ".jsx"}):
            if len(todos) >= 10:
                break
            try:
                for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                    if _TODO_RE.search(line):
                        todos.append(f"{p.name}:{i} {line.strip()[:80]}")
                        if len(todos) >= 10:
                            break
            except Exception:
                pass
    except Exception:
        pass
    return todos


def _count_source_files(ws: Path, project_type: str) -> int:
    ext_map: dict[str, set[str]] = {
        "Python":   {".py"},
        "Rust":     {".rs"},
        "Go":       {".go"},
        "Java":     {".java"},
        "Node.js":  {".js", ".ts", ".jsx", ".tsx"},
        "React":    {".js", ".ts", ".jsx", ".tsx"},
        "Vue":      {".vue", ".js", ".ts"},
        "Next.js":  {".js", ".ts", ".jsx", ".tsx"},
    }
    exts = ext_map.get(project_type, {".py", ".js", ".ts"})
    return sum(1 for _ in _walk_source(ws, exts=exts, max_files=2000))


def _has_ci(ws: Path) -> bool:
    return (
        (ws / ".github" / "workflows").exists()
        or (ws / ".gitlab-ci.yml").exists()
        or (ws / ".circleci").exists()
        or (ws / "Jenkinsfile").exists()
        or (ws / ".travis.yml").exists()
    )


# ── Idle static analysis ──────────────────────────────────────────────────────

def idle_suggestions(workspace_path: str) -> list[dict[str, str]]:
    """
    Quick static analysis that runs when MARK is idle.
    Returns a list of suggestion dicts.  Never raises.
    """
    try:
        ws = Path(workspace_path).resolve()
        suggestions: list[dict[str, str]] = []

        # Missing tests
        for p in _walk_source(ws, exts={".py"}, max_files=200):
            if p.name.startswith("test_") or p.name.endswith("_test.py"):
                continue
            test_file = p.parent / f"test_{p.name}"
            if not test_file.exists():
                suggestions.append({
                    "category": "missing-tests",
                    "priority": "medium",
                    "title":    f"No tests for {p.name}",
                    "description": f"Consider adding {test_file.name} to cover {p.name}.",
                    "file":    str(p.relative_to(ws)),
                })
            if len(suggestions) >= 3:
                break

        # Hardcoded credentials
        _CRED_RE = re.compile(
            r'(password|secret|api_key|token|auth)\s*=\s*["\'][^"\']{4,}["\']',
            re.IGNORECASE,
        )
        for p in _walk_source(ws, exts={".py", ".js", ".ts"}, max_files=300):
            try:
                text = p.read_text(errors="ignore")
                if _CRED_RE.search(text):
                    suggestions.append({
                        "category": "security",
                        "priority": "high",
                        "title":    f"Possible hardcoded credential in {p.name}",
                        "description": "Move secrets to environment variables or a secrets manager.",
                        "file":    str(p.relative_to(ws)),
                    })
                    break
            except Exception:
                pass

        # Large functions (Python)
        _DEF_RE = re.compile(r"^def ")
        for p in _walk_source(ws, exts={".py"}, max_files=100):
            try:
                lines = p.read_text(errors="ignore").splitlines()
                func_start = None
                for i, line in enumerate(lines):
                    if _DEF_RE.match(line):
                        if func_start is not None and (i - func_start) > 80:
                            suggestions.append({
                                "category": "performance",
                                "priority": "low",
                                "title":    f"Large function in {p.name} (line {func_start + 1})",
                                "description": "Functions over 80 lines are hard to test and maintain. Consider refactoring.",
                                "file": str(p.relative_to(ws)),
                            })
                            if len(suggestions) >= 8:
                                break
                        func_start = i
            except Exception:
                pass
            if len(suggestions) >= 8:
                break

        # Missing README
        has_readme = any((ws / r).exists() for r in ["README.md", "README.rst", "README.txt", "readme.md"])
        if not has_readme:
            suggestions.append({
                "category": "docs",
                "priority": "medium",
                "title":    "No README found",
                "description": "Add a README.md with project description, setup instructions, and usage examples.",
                "file": "",
            })

        return suggestions[:8]
    except Exception as exc:
        logger.warning("idle_suggestions: error: %s", exc)
        return []


# ── Summary builder ───────────────────────────────────────────────────────────

def _build_summary(
    project_type: str,
    frameworks: list[str],
    git_branch: str,
    test_framework: str | None,
    todo_count: int,
    file_count: int,
) -> str:
    parts = [project_type]
    if frameworks:
        parts.append(f"· {' / '.join(frameworks[:2])}")
    parts.append(f"· branch {git_branch}")
    if test_framework:
        parts.append(f"· {test_framework}")
    if todo_count:
        parts.append(f"· {todo_count} TODO{'s' if todo_count != 1 else ''}")
    if file_count:
        parts.append(f"· {file_count} source files")
    return " ".join(parts)
