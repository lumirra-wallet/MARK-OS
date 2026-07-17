"""
tests/test_architecture_guard.py — Task #8: Architecture Guardrails

Tests for ArchitectureGuard, GuardReport, and ArchitectureViolation,
plus Orchestrator integration (guard called before execution).

Coverage:
  ── GuardReport ───────────────────────────────────────────────────────────
  - Empty report: no issues, blocks_execution=False
  - Warning-only report: blocks_execution=False, warnings list populated
  - Error report: blocks_execution=True, errors list populated
  - Mixed: errors + warnings both counted; blocks on error
  - to_dict shape: issues/errors/warnings/blocks_execution keys present
  ── ArchitectureViolation ─────────────────────────────────────────────────
  - Is an Exception subclass
  - Carries message
  ── ArchitectureGuard.scan() — duplicate symbol check ─────────────────────
  - Clean workspace → no duplicate-symbol issues
  - Existing class in workspace + plan mentions it → warn
  - Existing function in workspace + plan mentions it → warn
  - Plan mentions symbol that doesn't exist → no issue
  - Short names (≤3 chars) are ignored
  - Symbol only in description (not title) still detected
  ── ArchitectureGuard.scan() — API route conflict check ───────────────────
  - No api_*.py files → no route issues
  - Plan route not in existing → no issue
  - Plan route exactly matches existing → error
  - Plan route has prefix overlap with existing → warn
  - Multiple conflicts detected in one scan
  ── ArchitectureGuard.scan() — layer boundary check ──────────────────────
  - Clean executive dir (no server imports) → no issues
  - Executive file imports from smartagent.server → warn
  - "from smartagent.server.foo import bar" format detected
  - "import smartagent.server" format detected
  - executive dir absent → no issues (graceful)
  ── ArchitectureGuard.scan() — combined / integration ─────────────────────
  - Clean project → GuardReport with zero issues
  - All three checks run even if workspace has issues
  - Error check does not prevent warning check from running
  - report stored in context.metadata["guard_report"]
  ── Orchestrator integration ──────────────────────────────────────────────
  - Guard called after planning, before execution
  - Warning report → execution continues, report stored in metadata
  - Error report → ArchitectureViolation raised, execution halted
  - arch_guard=None disables guard (no crash)
  - Custom arch_guard injected via constructor
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from smartagent.executive.architecture_guard import (
    ArchitectureGuard,
    ArchitectureViolation,
    GuardReport,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_task(title: str = "", description: str = ""):
    from smartagent.executive.task import Task
    return Task(title=title, description=description)


def _write(tmp_path, rel: str, content: str):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ── GuardReport ────────────────────────────────────────────────────────────────

class TestGuardReport:
    def test_empty_report_no_issues(self):
        r = GuardReport()
        assert r.issues == []
        assert not r.blocks_execution

    def test_warning_only_does_not_block(self):
        r = GuardReport(issues=[{"severity": "warn", "check": "x", "detail": "y"}])
        assert not r.blocks_execution
        assert len(r.warnings) == 1
        assert r.errors == []

    def test_error_blocks_execution(self):
        r = GuardReport(issues=[{"severity": "error", "check": "x", "detail": "y"}])
        assert r.blocks_execution
        assert len(r.errors) == 1

    def test_mixed_blocks_on_error(self):
        r = GuardReport(issues=[
            {"severity": "warn",  "check": "a", "detail": "w"},
            {"severity": "error", "check": "b", "detail": "e"},
        ])
        assert r.blocks_execution
        assert len(r.warnings) == 1
        assert len(r.errors) == 1

    def test_to_dict_keys(self):
        r = GuardReport()
        d = r.to_dict()
        assert "issues" in d
        assert "errors" in d
        assert "warnings" in d
        assert "blocks_execution" in d

    def test_to_dict_counts(self):
        r = GuardReport(issues=[
            {"severity": "warn",  "check": "a", "detail": ""},
            {"severity": "error", "check": "b", "detail": ""},
        ])
        d = r.to_dict()
        assert d["errors"] == 1
        assert d["warnings"] == 1
        assert d["blocks_execution"] is True

    def test_multiple_errors_counted(self):
        r = GuardReport(issues=[
            {"severity": "error", "check": "x", "detail": "1"},
            {"severity": "error", "check": "x", "detail": "2"},
        ])
        assert len(r.errors) == 2


# ── ArchitectureViolation ─────────────────────────────────────────────────────

class TestArchitectureViolation:
    def test_is_exception(self):
        assert issubclass(ArchitectureViolation, Exception)

    def test_carries_message(self):
        exc = ArchitectureViolation("route conflict detected")
        assert "route conflict" in str(exc)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(ArchitectureViolation, match="test"):
            raise ArchitectureViolation("test message")


# ── Duplicate symbol check ────────────────────────────────────────────────────

class TestDuplicateSymbolCheck:
    def test_clean_workspace_no_issues(self, tmp_path):
        _write(tmp_path, "foo.py", "def helper(): pass\n")
        guard = ArchitectureGuard(workspace_path=tmp_path)
        report = guard.scan("add a new feature", [_make_task("Add feature", "build it")])
        sym_issues = [i for i in report.issues if i["check"] == "duplicate_symbol"]
        assert sym_issues == []

    def test_duplicate_class_detected(self, tmp_path):
        _write(tmp_path, "mymod.py", "class MyProcessor:\n    pass\n")
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Create MyProcessor", "implement MyProcessor class")
        report = guard.scan("create MyProcessor", [t])
        sym_issues = [i for i in report.issues if i["check"] == "duplicate_symbol"]
        assert any("MyProcessor" in i["detail"] for i in sym_issues)

    def test_duplicate_function_detected(self, tmp_path):
        _write(tmp_path, "utils.py", "def compute_hash():\n    return ''\n")
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Add compute_hash function", "implement compute_hash()")
        report = guard.scan("add function compute_hash", [t])
        sym_issues = [i for i in report.issues if i["check"] == "duplicate_symbol"]
        assert any("compute_hash" in i["detail"] for i in sym_issues)

    def test_novel_symbol_no_issue(self, tmp_path):
        _write(tmp_path, "mymod.py", "class Existing:\n    pass\n")
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Create BrandNewClass", "add class BrandNewClass")
        report = guard.scan("create BrandNewClass", [t])
        # BrandNewClass is not in workspace → no issue
        dup = [i for i in report.issues if i["check"] == "duplicate_symbol"
               and "BrandNewClass" in i["detail"]]
        assert dup == []

    def test_short_names_ignored(self, tmp_path):
        _write(tmp_path, "api.py", "def run():\n    pass\nclass Foo:\n    pass\n")
        guard = ArchitectureGuard(workspace_path=tmp_path)
        # "run" is 3 chars, "Foo" is 3 chars — both below the length threshold
        t = _make_task("Add run and Foo", "implement run() and Foo")
        report = guard.scan("add run and Foo class", [t])
        dup = [i for i in report.issues if i["check"] == "duplicate_symbol"]
        # length ≤ 3 names are stripped; no warnings expected
        assert all("run" not in i["detail"] and "Foo" not in i["detail"] for i in dup)

    def test_symbol_in_description_detected(self, tmp_path):
        _write(tmp_path, "engine.py", "class ReasoningEngine:\n    pass\n")
        guard = ArchitectureGuard(workspace_path=tmp_path)
        # Symbol in description, not title
        t = _make_task("Build engine", "implement ReasoningEngine class here")
        report = guard.scan("build engine", [t])
        dup = [i for i in report.issues if i["check"] == "duplicate_symbol"]
        assert any("ReasoningEngine" in i["detail"] for i in dup)


# ── API route conflict check ──────────────────────────────────────────────────

class TestApiRouteConflictCheck:
    def test_no_api_files_no_issues(self, tmp_path):
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Add endpoint", "create endpoint /widgets")
        report = guard.scan("add route /widgets", [t])
        route_issues = [i for i in report.issues if i["check"] == "api_route_conflict"]
        assert route_issues == []

    def test_novel_route_no_issue(self, tmp_path):
        server = tmp_path / "smartagent" / "server"
        server.mkdir(parents=True)
        (server / "api_items.py").write_text(
            '@router.get("/items")\ndef list_items(): ...\n'
        )
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Add endpoint", "create endpoint /orders")
        report = guard.scan("add route /orders", [t])
        route_issues = [i for i in report.issues if i["check"] == "api_route_conflict"]
        assert route_issues == []

    def test_exact_route_match_is_error(self, tmp_path):
        server = tmp_path / "smartagent" / "server"
        server.mkdir(parents=True)
        (server / "api_health.py").write_text(
            '@router.get("/health")\ndef health(): ...\n'
        )
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Add health endpoint", "create endpoint /health")
        report = guard.scan("add route /health", [t])
        errors = [i for i in report.issues
                  if i["check"] == "api_route_conflict" and i["severity"] == "error"]
        assert any("/health" in i["detail"] for i in errors)

    def test_prefix_overlap_is_warning(self, tmp_path):
        server = tmp_path / "smartagent" / "server"
        server.mkdir(parents=True)
        (server / "api_models.py").write_text(
            '@router.get("/models/list")\ndef list_models(): ...\n'
        )
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Add route", "create endpoint /models")
        report = guard.scan("add route /models", [t])
        warns = [i for i in report.issues
                 if i["check"] == "api_route_conflict" and i["severity"] == "warn"]
        assert any("/models" in i["detail"] for i in warns)

    def test_multiple_conflicts_detected(self, tmp_path):
        server = tmp_path / "smartagent" / "server"
        server.mkdir(parents=True)
        (server / "api_a.py").write_text(
            '@router.get("/alpha")\ndef a(): ...\n'
            '@router.post("/beta")\ndef b(): ...\n'
        )
        guard = ArchitectureGuard(workspace_path=tmp_path)
        t = _make_task("Add routes",
                       "create endpoint /alpha and create endpoint /beta")
        report = guard.scan("add routes /alpha /beta", [t])
        errors = [i for i in report.issues
                  if i["check"] == "api_route_conflict" and i["severity"] == "error"]
        assert len(errors) >= 2


# ── Layer boundary check ──────────────────────────────────────────────────────

class TestLayerBoundaryCheck:
    def test_clean_executive_no_issues(self, tmp_path):
        exec_dir = tmp_path / "smartagent" / "executive"
        exec_dir.mkdir(parents=True)
        (exec_dir / "planner.py").write_text(
            "from smartagent.executive.task import Task\n"
        )
        guard = ArchitectureGuard(workspace_path=tmp_path)
        report = guard.scan("plan something", [])
        layer_issues = [i for i in report.issues if i["check"] == "layer_boundary"]
        assert layer_issues == []

    def test_from_server_import_detected(self, tmp_path):
        exec_dir = tmp_path / "smartagent" / "executive"
        exec_dir.mkdir(parents=True)
        (exec_dir / "bad_planner.py").write_text(
            "from smartagent.server.api import router\n"
            "class Planner: pass\n"
        )
        guard = ArchitectureGuard(workspace_path=tmp_path)
        report = guard.scan("plan something", [])
        layer_issues = [i for i in report.issues if i["check"] == "layer_boundary"]
        assert len(layer_issues) >= 1
        assert any("bad_planner" in i["detail"] for i in layer_issues)

    def test_import_server_format_detected(self, tmp_path):
        exec_dir = tmp_path / "smartagent" / "executive"
        exec_dir.mkdir(parents=True)
        (exec_dir / "worker.py").write_text(
            "import smartagent.server.websocket\n"
        )
        guard = ArchitectureGuard(workspace_path=tmp_path)
        report = guard.scan("something", [])
        layer_issues = [i for i in report.issues if i["check"] == "layer_boundary"]
        assert len(layer_issues) >= 1

    def test_no_executive_dir_no_issues(self, tmp_path):
        # workspace has no smartagent/executive/ dir at all
        guard = ArchitectureGuard(workspace_path=tmp_path)
        report = guard.scan("something", [])
        layer_issues = [i for i in report.issues if i["check"] == "layer_boundary"]
        assert layer_issues == []

    def test_multiple_violations_all_reported(self, tmp_path):
        exec_dir = tmp_path / "smartagent" / "executive"
        exec_dir.mkdir(parents=True)
        (exec_dir / "a.py").write_text("from smartagent.server import foo\n")
        (exec_dir / "b.py").write_text("from smartagent.server import bar\n")
        guard = ArchitectureGuard(workspace_path=tmp_path)
        report = guard.scan("x", [])
        layer_issues = [i for i in report.issues if i["check"] == "layer_boundary"]
        assert len(layer_issues) == 2


# ── Combined / integration ────────────────────────────────────────────────────

class TestCombinedScan:
    def test_clean_project_zero_issues(self, tmp_path):
        guard = ArchitectureGuard(workspace_path=tmp_path)
        report = guard.scan("build something new", [])
        assert report.issues == []
        assert not report.blocks_execution

    def test_check_exception_recorded_as_warn(self, tmp_path):
        """If one check raises, it becomes a warn and others still run."""
        guard = ArchitectureGuard(workspace_path=tmp_path)
        with patch.object(
            guard, "_check_duplicate_symbols", side_effect=RuntimeError("boom")
        ):
            report = guard.scan("x", [])
        warn_checks = [i["check"] for i in report.issues if i["severity"] == "warn"]
        assert "duplicate_symbol" in warn_checks

    def test_remaining_checks_run_after_failure(self, tmp_path):
        exec_dir = tmp_path / "smartagent" / "executive"
        exec_dir.mkdir(parents=True)
        (exec_dir / "bad.py").write_text("from smartagent.server import api\n")

        guard = ArchitectureGuard(workspace_path=tmp_path)
        with patch.object(
            guard, "_check_duplicate_symbols", side_effect=RuntimeError("boom")
        ):
            report = guard.scan("x", [])

        checks_seen = {i["check"] for i in report.issues}
        assert "layer_boundary" in checks_seen  # still ran

    def test_report_stored_in_metadata_via_orchestrator(self, tmp_path):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.architecture_guard import ArchitectureGuard

        guard = ArchitectureGuard(workspace_path=tmp_path)
        orc = Orchestrator(arch_guard=guard)
        ctx = orc.execute_goal("build a simple thing")
        assert "guard_report" in ctx.metadata
        assert "issues" in ctx.metadata["guard_report"]

    def test_warning_does_not_block_orchestrator(self, tmp_path):
        """A warn-only guard lets execution proceed."""
        from smartagent.executive.orchestrator import Orchestrator

        guard = ArchitectureGuard(workspace_path=tmp_path)
        warn_report = GuardReport(issues=[
            {"severity": "warn", "check": "layer_boundary", "detail": "minor"}
        ])
        with patch.object(guard, "scan", return_value=warn_report):
            orc = Orchestrator(arch_guard=guard)
            # Should not raise
            ctx = orc.execute_goal("do something")
        assert ctx.metadata["guard_report"]["warnings"] == 1

    def test_error_blocks_orchestrator(self, tmp_path):
        """An error-severity issue raises ArchitectureViolation."""
        from smartagent.executive.orchestrator import Orchestrator

        guard = ArchitectureGuard(workspace_path=tmp_path)
        error_report = GuardReport(issues=[
            {"severity": "error", "check": "api_route_conflict",
             "detail": "Route '/health' already exists"}
        ])
        with patch.object(guard, "scan", return_value=error_report):
            orc = Orchestrator(arch_guard=guard)
            with pytest.raises(ArchitectureViolation, match="blocked"):
                orc.execute_goal("add /health endpoint")

    def test_no_guard_no_crash(self):
        """arch_guard=None skips guard entirely — no AttributeError."""
        from smartagent.executive.orchestrator import Orchestrator
        orc = Orchestrator(arch_guard=None)
        ctx = orc.execute_goal("build a simple thing")
        # guard_report not set when guard is disabled
        assert "guard_report" not in ctx.metadata
