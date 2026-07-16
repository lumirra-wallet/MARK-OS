"""
Tests for Milestone 18: WorkspaceIntelligence — ProjectScanner.

Test coverage:
    • FileNode / ImportEdge / ProjectSnapshot data models
    • _detect_language helper
    • _is_test_path helper
    • ProjectScanner._collect_files (directory walk, ignore dirs, size filter)
    • ProjectScanner._build_module_map (Python paths → dotted names)
    • ProjectScanner._collect_imports (AST import parsing)
    • ProjectScanner._collect_dependencies (requirements.txt, pyproject.toml)
    • ProjectScanner._detect_architecture (MVC, DDD, Layered, Flat, Standard)
    • ProjectScanner._compute_summary (counts, primary language)
    • ProjectScanner._collect_git (mock subprocess, unavailable git)
    • ProjectScanner.scan() end-to-end
    • ProjectSnapshot.as_display_lines() and as_summary_text()
"""

from __future__ import annotations

import os
import textwrap
from unittest.mock import patch, MagicMock

import pytest

from smartagent.workspace.scanner import (
    FileNode,
    ImportEdge,
    ProjectScanner,
    ProjectSnapshot,
    _detect_language,
    _is_test_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(**kwargs) -> ProjectSnapshot:
    """Build a minimal valid ProjectSnapshot with sensible defaults."""
    defaults = dict(root="/tmp/proj", scanned_at="2026-01-01T00:00:00+00:00")
    defaults.update(kwargs)
    return ProjectSnapshot(**defaults)


# ---------------------------------------------------------------------------
# _detect_language
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    def test_python(self):
        assert _detect_language("main.py") == "Python"

    def test_javascript(self):
        assert _detect_language("index.js") == "JavaScript"

    def test_typescript(self):
        assert _detect_language("app.ts") == "TypeScript"

    def test_tsx(self):
        assert _detect_language("Component.tsx") == "TypeScript"

    def test_jsx(self):
        assert _detect_language("App.jsx") == "JavaScript"

    def test_go(self):
        assert _detect_language("main.go") == "Go"

    def test_rust(self):
        assert _detect_language("lib.rs") == "Rust"

    def test_java(self):
        assert _detect_language("Main.java") == "Java"

    def test_markdown(self):
        assert _detect_language("README.md") == "Markdown"

    def test_yaml(self):
        assert _detect_language("config.yml") == "YAML"

    def test_yaml_full(self):
        assert _detect_language("docker-compose.yaml") == "YAML"

    def test_toml(self):
        assert _detect_language("pyproject.toml") == "TOML"

    def test_json(self):
        assert _detect_language("package.json") == "JSON"

    def test_shell(self):
        assert _detect_language("deploy.sh") == "Shell"

    def test_unknown(self):
        assert _detect_language("Makefile") == "Other"

    def test_no_extension(self):
        assert _detect_language("Dockerfile") == "Other"

    def test_uppercase_ext(self):
        # Should match lowercase extension
        assert _detect_language("main.PY") == "Python"

    def test_css(self):
        assert _detect_language("styles.css") == "CSS"

    def test_sql(self):
        assert _detect_language("schema.sql") == "SQL"


# ---------------------------------------------------------------------------
# _is_test_path
# ---------------------------------------------------------------------------

class TestIsTestPath:
    def test_test_prefix_file(self):
        assert _is_test_path("test_auth.py") is True

    def test_tests_directory(self):
        assert _is_test_path("tests/test_auth.py") is True

    def test_test_dir_not_prefix(self):
        assert _is_test_path("tests/helpers.py") is True

    def test_spec_directory(self):
        assert _is_test_path("spec/auth_spec.rb") is True

    def test_suffix_test(self):
        assert _is_test_path("auth_test.py") is True

    def test_regular_file(self):
        assert _is_test_path("auth.py") is False

    def test_src_directory(self):
        assert _is_test_path("src/auth.py") is False

    def test_nested_tests(self):
        assert _is_test_path("tests/unit/test_auth.py") is True

    def test_test_in_middle_not_matched(self):
        # "contest.py" has "test" inside but doesn't start with "test_"
        assert _is_test_path("src/contest.py") is False


# ---------------------------------------------------------------------------
# FileNode
# ---------------------------------------------------------------------------

class TestFileNode:
    def test_create(self):
        node = FileNode(path="src/auth.py", language="Python", size=1024, is_test=False)
        assert node.path == "src/auth.py"
        assert node.language == "Python"
        assert node.size == 1024
        assert node.is_test is False

    def test_test_node(self):
        node = FileNode(path="tests/test_auth.py", language="Python", size=512, is_test=True)
        assert node.is_test is True


# ---------------------------------------------------------------------------
# ImportEdge
# ---------------------------------------------------------------------------

class TestImportEdge:
    def test_absolute_import(self):
        edge = ImportEdge(from_file="a.py", to_module="os", is_relative=False)
        assert edge.to_module == "os"
        assert edge.is_relative is False

    def test_relative_import(self):
        edge = ImportEdge(from_file="pkg/a.py", to_module=".utils", is_relative=True)
        assert edge.is_relative is True


# ---------------------------------------------------------------------------
# ProjectSnapshot
# ---------------------------------------------------------------------------

class TestProjectSnapshot:
    def test_defaults(self):
        snap = _make_snapshot()
        assert snap.file_count == 0
        assert snap.test_count == 0
        assert snap.languages == {}
        assert snap.dependencies == {}
        assert snap.git_available is False

    def test_python_files_property(self):
        snap = _make_snapshot()
        snap.files = [
            FileNode("src/a.py",     "Python", 100, False),
            FileNode("tests/t.py",   "Python", 100, True),
            FileNode("README.md",    "Markdown", 50, False),
        ]
        py_files = snap.python_files
        assert len(py_files) == 1
        assert py_files[0].path == "src/a.py"

    def test_test_files_property(self):
        snap = _make_snapshot()
        snap.files = [
            FileNode("src/a.py",     "Python", 100, False),
            FileNode("tests/t.py",   "Python", 100, True),
        ]
        assert len(snap.test_files) == 1

    def test_as_display_lines_basic(self):
        snap = _make_snapshot(
            file_count=10,
            test_count=3,
            architecture="MVC",
            primary_language="Python",
        )
        snap.languages = {"Python": 8, "Markdown": 2}
        lines = snap.as_display_lines()
        assert any("MVC" in l for l in lines)
        assert any("10" in l for l in lines)
        assert any("Python" in l for l in lines)

    def test_as_display_lines_with_git(self):
        snap = _make_snapshot()
        snap.git_available = True
        snap.git_branch = "main"
        snap.git_commit = "abc1234 Initial commit"
        snap.git_status_lines = ["M src/auth.py", "?? new_file.py"]
        lines = snap.as_display_lines()
        assert any("main" in l for l in lines)
        assert any("abc1234" in l for l in lines)

    def test_as_display_lines_with_deps(self):
        snap = _make_snapshot()
        snap.dependencies = {"fastapi": ">=0.100", "pydantic": "==2.0"}
        lines = snap.as_display_lines()
        assert any("fastapi" in l for l in lines)

    def test_as_summary_text(self):
        snap = _make_snapshot(
            architecture="Layered",
            primary_language="Python",
            file_count=42,
            test_count=10,
        )
        snap.languages = {"Python": 40, "YAML": 2}
        summary = snap.as_summary_text()
        assert "Layered" in summary
        assert "Python" in summary
        assert "42" in summary

    def test_as_display_lines_no_git(self):
        snap = _make_snapshot()
        snap.git_available = False
        lines = snap.as_display_lines()
        # No git section
        assert not any("Branch:" in l for l in lines)


# ---------------------------------------------------------------------------
# ProjectScanner — directory scanning (uses real filesystem via tmp_path)
# ---------------------------------------------------------------------------

class TestProjectScannerCollectFiles:
    def test_collects_python_files(self, tmp_path):
        (tmp_path / "main.py").write_text("# hello")
        (tmp_path / "utils.py").write_text("# utils")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_files(snap)
        paths = {f.path for f in snap.files}
        assert "main.py" in paths
        assert "utils.py" in paths

    def test_ignores_pycache(self, tmp_path):
        py = tmp_path / "__pycache__"
        py.mkdir()
        (py / "cached.pyc").write_bytes(b"\x00")
        (tmp_path / "main.py").write_text("# code")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_files(snap)
        assert all("__pycache__" not in f.path for f in snap.files)

    def test_ignores_git_dir(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text("[core]")
        (tmp_path / "main.py").write_text("# code")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_files(snap)
        assert all(".git" not in f.path for f in snap.files)

    def test_ignores_venv(self, tmp_path):
        (tmp_path / ".venv").mkdir()
        (tmp_path / ".venv" / "lib.py").write_text("")
        (tmp_path / "app.py").write_text("")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_files(snap)
        assert all(".venv" not in f.path for f in snap.files)

    def test_marks_test_files(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_main.py").write_text("")
        (tmp_path / "app.py").write_text("")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_files(snap)
        by_path = {f.path.replace("\\", "/"): f for f in snap.files}
        assert by_path["tests/test_main.py"].is_test is True
        assert by_path["app.py"].is_test is False

    def test_skips_large_files(self, tmp_path):
        big = tmp_path / "bigfile.py"
        big.write_bytes(b"x" * 2000)
        scanner = ProjectScanner(str(tmp_path), max_file_size=1000)
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_files(snap)
        assert all("bigfile.py" not in f.path for f in snap.files)

    def test_language_counts(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "README.md").write_text("")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_files(snap)
        assert snap.languages["Python"] == 2
        assert snap.languages["Markdown"] == 1


# ---------------------------------------------------------------------------
# Module map
# ---------------------------------------------------------------------------

class TestBuildModuleMap:
    def test_simple_file(self, tmp_path):
        (tmp_path / "mymod.py").write_text("x = 1")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("mymod.py", "Python", 10, False)]
        scanner._build_module_map(snap)
        assert "mymod" in snap.module_map

    def test_nested_package(self, tmp_path):
        pkg = tmp_path / "pkg" / "sub"
        pkg.mkdir(parents=True)
        (pkg / "module.py").write_text("")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("pkg/sub/module.py", "Python", 10, False)]
        scanner._build_module_map(snap)
        assert "pkg.sub.module" in snap.module_map

    def test_init_file_drops_init(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("pkg/__init__.py", "Python", 10, False)]
        scanner._build_module_map(snap)
        assert "pkg" in snap.module_map
        assert "pkg.__init__" not in snap.module_map

    def test_non_python_ignored(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("README.md", "Markdown", 10, False)]
        scanner._build_module_map(snap)
        assert snap.module_map == {}


# ---------------------------------------------------------------------------
# Import collection
# ---------------------------------------------------------------------------

class TestCollectImports:
    def test_simple_import(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("import os\nimport sys\n")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("main.py", "Python", f.stat().st_size, False)]
        scanner._collect_imports(snap)
        modules = {e.to_module for e in snap.import_edges}
        assert "os" in modules
        assert "sys" in modules

    def test_from_import(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text("from os.path import join, exists\n")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("app.py", "Python", f.stat().st_size, False)]
        scanner._collect_imports(snap)
        modules = {e.to_module for e in snap.import_edges}
        assert "os.path" in modules

    def test_relative_import(self, tmp_path):
        f = tmp_path / "pkg" / "sub.py"
        f.parent.mkdir()
        f.write_text("from . import utils\n")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        rel = os.path.relpath(str(f), str(tmp_path))
        snap.files = [FileNode(rel, "Python", f.stat().st_size, False)]
        scanner._collect_imports(snap)
        rel_edges = [e for e in snap.import_edges if e.is_relative]
        assert len(rel_edges) == 1

    def test_syntax_error_skipped(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def oops(:\n")  # syntax error
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("bad.py", "Python", f.stat().st_size, False)]
        scanner._collect_imports(snap)
        # No crash — just no edges
        assert snap.import_edges == []

    def test_non_python_ignored(self, tmp_path):
        f = tmp_path / "main.js"
        f.write_text("const x = require('os')\n")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        snap.files = [FileNode("main.js", "JavaScript", f.stat().st_size, False)]
        scanner._collect_imports(snap)
        assert snap.import_edges == []


# ---------------------------------------------------------------------------
# Dependency collection
# ---------------------------------------------------------------------------

class TestCollectDependencies:
    def test_requirements_txt(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("fastapi>=0.100.0\npydantic==2.0\n# comment\nrequests\n")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_dependencies(snap)
        assert "fastapi" in snap.dependencies
        assert "pydantic" in snap.dependencies
        assert "requests" in snap.dependencies

    def test_requirements_comment_skipped(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("# this is a comment\nflask\n")
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_dependencies(snap)
        assert "flask" in snap.dependencies
        # Only 'flask' — comment not parsed as a package
        dep_keys = list(snap.dependencies.keys())
        assert all(not k.startswith("#") for k in dep_keys)

    def test_no_requirements_file(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_dependencies(snap)
        assert snap.dependencies == {}

    def test_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(textwrap.dedent("""\
            [project]
            name = "myapp"
            fastapi = ">=0.100"
            pydantic = ">=2"
        """))
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_dependencies(snap)
        assert "fastapi" in snap.dependencies

    def test_package_json(self, tmp_path):
        import json
        pkg_json = {"dependencies": {"express": "^4.18", "axios": "^1.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg_json))
        scanner = ProjectScanner(str(tmp_path))
        snap = ProjectSnapshot(root=str(tmp_path), scanned_at="now")
        scanner._collect_dependencies(snap)
        assert "express" in snap.dependencies
        assert "axios" in snap.dependencies


# ---------------------------------------------------------------------------
# Architecture detection
# ---------------------------------------------------------------------------

class TestDetectArchitecture:
    def _snap_with_dirs(self, dirs: list[str]) -> ProjectSnapshot:
        snap = _make_snapshot()
        snap.files = [FileNode(f"{d}/x.py", "Python", 10, False) for d in dirs]
        return snap

    def test_mvc(self):
        snap = self._snap_with_dirs(["views", "models", "controllers"])
        scanner = ProjectScanner("/tmp")
        scanner._detect_architecture(snap)
        assert snap.architecture == "MVC"

    def test_mvc_with_routes(self):
        snap = self._snap_with_dirs(["views", "models", "routes"])
        scanner = ProjectScanner("/tmp")
        scanner._detect_architecture(snap)
        assert snap.architecture == "MVC"

    def test_ddd(self):
        snap = self._snap_with_dirs(["domain", "services", "repositories"])
        scanner = ProjectScanner("/tmp")
        scanner._detect_architecture(snap)
        assert snap.architecture == "DDD"

    def test_clean(self):
        snap = self._snap_with_dirs(["usecases", "entities", "adapters"])
        scanner = ProjectScanner("/tmp")
        scanner._detect_architecture(snap)
        assert snap.architecture == "Clean Architecture"

    def test_layered(self):
        snap = self._snap_with_dirs(["api", "core", "db"])
        scanner = ProjectScanner("/tmp")
        scanner._detect_architecture(snap)
        assert snap.architecture == "Layered"

    def test_flat(self):
        snap = _make_snapshot()
        snap.files = [
            FileNode("main.py", "Python", 10, False),
            FileNode("utils.py", "Python", 10, False),
        ]
        scanner = ProjectScanner("/tmp")
        scanner._detect_architecture(snap)
        assert snap.architecture == "Flat"

    def test_standard(self):
        snap = self._snap_with_dirs(["src", "docs", "config", "data"])
        scanner = ProjectScanner("/tmp")
        scanner._detect_architecture(snap)
        assert snap.architecture == "Standard Package"


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------

class TestComputeSummary:
    def test_counts(self):
        snap = _make_snapshot()
        snap.files = [
            FileNode("a.py",          "Python", 10, False),
            FileNode("test_a.py",     "Python", 10, True),
            FileNode("README.md",     "Markdown", 10, False),
        ]
        scanner = ProjectScanner("/tmp")
        scanner._compute_summary(snap)
        assert snap.file_count == 3
        assert snap.test_count == 1

    def test_primary_language(self):
        snap = _make_snapshot()
        snap.languages = {"Python": 10, "Markdown": 2, "YAML": 1}
        scanner = ProjectScanner("/tmp")
        scanner._compute_summary(snap)
        assert snap.primary_language == "Python"

    def test_empty_project(self):
        snap = _make_snapshot()
        scanner = ProjectScanner("/tmp")
        scanner._compute_summary(snap)
        assert snap.file_count == 0
        assert snap.primary_language == ""


# ---------------------------------------------------------------------------
# Git collection
# ---------------------------------------------------------------------------

class TestCollectGit:
    def test_git_not_available(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        snap = _make_snapshot(root=str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            scanner._collect_git(snap)
        assert snap.git_available is False

    def test_git_not_a_repo(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        snap = _make_snapshot(root=str(tmp_path))

        mock_result = MagicMock()
        mock_result.returncode = 128  # not a git repo
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            scanner._collect_git(snap)
        assert snap.git_available is False

    def test_git_available(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        snap = _make_snapshot(root=str(tmp_path))

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            if "--is-inside-work-tree" in cmd:
                r.returncode = 0
                r.stdout = "true"
            elif "--abbrev-ref" in cmd:
                r.returncode = 0
                r.stdout = "main"
            elif "--oneline" in cmd:
                r.returncode = 0
                r.stdout = "abc1234 Initial commit"
            elif "--porcelain" in cmd:
                r.returncode = 0
                r.stdout = "M src/app.py\n?? new.py"
            else:
                r.returncode = 0
                r.stdout = ""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            scanner._collect_git(snap)

        assert snap.git_available is True
        assert snap.git_branch == "main"
        assert snap.git_commit == "abc1234 Initial commit"
        assert len(snap.git_status_lines) == 2

    def test_clean_working_tree(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        snap = _make_snapshot(root=str(tmp_path))

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            if "--is-inside-work-tree" in cmd:
                r.returncode = 0
                r.stdout = "true"
            elif "--abbrev-ref" in cmd:
                r.returncode = 0
                r.stdout = "develop"
            elif "--oneline" in cmd:
                r.returncode = 0
                r.stdout = ""
            elif "--porcelain" in cmd:
                r.returncode = 0
                r.stdout = ""
            else:
                r.returncode = 0
                r.stdout = ""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            scanner._collect_git(snap)

        assert snap.git_available is True
        assert snap.git_branch == "develop"
        assert snap.git_status_lines == []


# ---------------------------------------------------------------------------
# End-to-end scan
# ---------------------------------------------------------------------------

class TestProjectScannerEndToEnd:
    def test_scan_returns_snapshot(self, tmp_path):
        (tmp_path / "app.py").write_text("import os\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("import app\n")
        (tmp_path / "requirements.txt").write_text("pytest\n")
        (tmp_path / "README.md").write_text("# App\n")

        scanner = ProjectScanner(str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            snap = scanner.scan()

        assert snap.file_count >= 4
        assert snap.test_count >= 1
        assert "Python" in snap.languages
        assert "pytest" in snap.dependencies
        assert snap.git_available is False

    def test_scan_root_property(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        assert scanner.root == str(tmp_path)

    def test_scan_empty_directory(self, tmp_path):
        scanner = ProjectScanner(str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            snap = scanner.scan()
        assert snap.file_count == 0
        assert snap.primary_language == ""

    def test_scan_display_lines_is_list(self, tmp_path):
        (tmp_path / "main.py").write_text("")
        scanner = ProjectScanner(str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError):
            snap = scanner.scan()
        lines = snap.as_display_lines()
        assert isinstance(lines, list)
        assert len(lines) > 3
