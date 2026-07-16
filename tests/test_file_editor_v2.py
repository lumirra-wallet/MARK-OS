"""
Tests for FileEditor v2.0 additions:
  - preview / diff
  - snapshot / restore
  - move / rename
  - export_audit_log
  - EditResult.to_dict
"""

import json
import os
import pytest

from smartagent.workspace.file_editor import FileEditor, EditResult, _unified_diff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def editor(tmp_path):
    return FileEditor(str(tmp_path))


# ---------------------------------------------------------------------------
# EditResult.to_dict
# ---------------------------------------------------------------------------

class TestEditResultToDict:
    def test_keys(self):
        r = EditResult(success=True, path="a.py", operation="create", message="ok", bytes_written=5)
        d = r.to_dict()
        assert set(d.keys()) == {"success", "path", "operation", "message", "bytes_written"}

    def test_values(self):
        r = EditResult(success=False, path="b.py", operation="delete", message="err")
        d = r.to_dict()
        assert d["success"] is False
        assert d["path"] == "b.py"
        assert d["bytes_written"] == 0


# ---------------------------------------------------------------------------
# preview / diff
# ---------------------------------------------------------------------------

class TestPreviewDiff:
    def test_preview_new_file(self, editor):
        diff = editor.preview("new.py", "print('hello')")
        assert "+" in diff
        assert "print" in diff

    def test_preview_existing_file(self, editor):
        editor.create("greet.py", "print('hi')")
        diff = editor.preview("greet.py", "print('hello')")
        assert "-print('hi')" in diff or "-" in diff
        assert "+print('hello')" in diff or "+" in diff

    def test_preview_no_change(self, editor):
        editor.create("same.py", "x = 1")
        diff = editor.preview("same.py", "x = 1")
        assert diff == ""

    def test_diff_is_alias_for_preview(self, editor):
        editor.create("f.py", "a")
        assert editor.diff("f.py", "b") == editor.preview("f.py", "b")

    def test_preview_does_not_write(self, editor):
        editor.create("orig.py", "original")
        editor.preview("orig.py", "changed")
        assert editor.read("orig.py") == "original"

    def test_unified_diff_helper(self):
        d = _unified_diff("x.py", "old\n", "new\n")
        assert "--- a/x.py" in d
        assert "+++ b/x.py" in d


# ---------------------------------------------------------------------------
# snapshot / restore
# ---------------------------------------------------------------------------

class TestSnapshotRestore:
    def test_snapshot_captures_files(self, editor):
        editor.create("a.py", "aaa")
        editor.create("b.py", "bbb")
        snap = editor.snapshot()
        assert set(snap.keys()) == {"a.py", "b.py"}
        assert snap["a.py"] == "aaa"
        assert snap["b.py"] == "bbb"

    def test_empty_snapshot(self, editor):
        snap = editor.snapshot()
        assert snap == {}

    def test_restore_reverts_edits(self, editor):
        editor.create("code.py", "v1")
        snap = editor.snapshot()
        editor.edit("code.py", "v2")
        assert editor.read("code.py") == "v2"
        editor.restore(snap)
        assert editor.read("code.py") == "v1"

    def test_restore_deletes_new_files(self, editor):
        editor.create("keep.py", "k")
        snap = editor.snapshot()
        editor.create("extra.py", "x")
        assert editor.exists("extra.py")
        editor.restore(snap)
        assert not editor.exists("extra.py")
        assert editor.exists("keep.py")

    def test_restore_returns_edit_results(self, editor):
        editor.create("f.py", "a")
        snap = editor.snapshot()
        results = editor.restore(snap)
        assert isinstance(results, list)
        assert all(hasattr(r, "success") for r in results)

    def test_snapshot_then_restore_no_change(self, editor):
        editor.create("x.py", "hello")
        snap = editor.snapshot()
        editor.restore(snap)
        assert editor.read("x.py") == "hello"

    def test_snapshot_after_patch(self, editor):
        editor.create("p.py", "foo")
        editor.patch("p.py", "foo", "bar")
        snap = editor.snapshot()
        assert snap["p.py"] == "bar"


# ---------------------------------------------------------------------------
# move / rename
# ---------------------------------------------------------------------------

class TestMoveRename:
    def test_move_basic(self, editor):
        editor.create("src.py", "content")
        result = editor.move("src.py", "dst.py")
        assert result.success
        assert editor.exists("dst.py")
        assert not editor.exists("src.py")

    def test_move_content_preserved(self, editor):
        editor.create("old.py", "hello world")
        editor.move("old.py", "new.py")
        assert editor.read("new.py") == "hello world"

    def test_move_into_subdirectory(self, editor):
        editor.create("flat.py", "data")
        result = editor.move("flat.py", "sub/flat.py")
        assert result.success
        assert editor.read("sub/flat.py") == "data"

    def test_move_missing_source(self, editor):
        result = editor.move("ghost.py", "dest.py")
        assert not result.success
        assert "not found" in result.message.lower() or "Source" in result.message

    def test_move_escape_rejected(self, editor):
        editor.create("f.py", "x")
        result = editor.move("f.py", "../../escaped.py")
        assert not result.success

    def test_rename_is_alias(self, editor):
        editor.create("a.py", "data")
        result = editor.rename("a.py", "b.py")
        assert result.success
        assert result.operation == "move"
        assert editor.exists("b.py")

    def test_move_recorded_in_audit(self, editor):
        editor.create("orig.py", "x")
        editor.move("orig.py", "moved.py")
        edits = editor.list_edits()
        ops = [e.operation for e in edits]
        assert "move" in ops


# ---------------------------------------------------------------------------
# export_audit_log
# ---------------------------------------------------------------------------

class TestExportAuditLog:
    def test_returns_valid_json(self, editor):
        editor.create("f.py", "hello")
        log = editor.export_audit_log()
        parsed = json.loads(log)
        assert isinstance(parsed, list)

    def test_log_contains_create(self, editor):
        editor.create("x.py", "data")
        parsed = json.loads(editor.export_audit_log())
        assert parsed[0]["operation"] == "create"
        assert parsed[0]["path"] == "x.py"
        assert parsed[0]["success"] is True

    def test_empty_log(self, editor):
        log = editor.export_audit_log()
        assert json.loads(log) == []

    def test_log_multiple_ops(self, editor):
        editor.create("a.py", "a")
        editor.edit("a.py", "b")
        editor.delete("a.py")
        parsed = json.loads(editor.export_audit_log())
        ops = [e["operation"] for e in parsed]
        assert ops == ["create", "edit", "delete"]

    def test_log_bytes_written(self, editor):
        editor.create("z.py", "hello")
        parsed = json.loads(editor.export_audit_log())
        assert parsed[0]["bytes_written"] == 5


# ---------------------------------------------------------------------------
# Backward-compatibility: all original methods still work
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_create_still_works(self, editor):
        r = editor.create("back.py", "ok")
        assert r.success

    def test_edit_still_works(self, editor):
        editor.create("back.py", "v1")
        r = editor.edit("back.py", "v2")
        assert r.success

    def test_patch_still_works(self, editor):
        editor.create("back.py", "old")
        r = editor.patch("back.py", "old", "new")
        assert r.success

    def test_delete_still_works(self, editor):
        editor.create("back.py", "x")
        r = editor.delete("back.py")
        assert r.success

    def test_read_still_works(self, editor):
        editor.create("back.py", "hello")
        assert editor.read("back.py") == "hello"

    def test_summary_still_works(self, editor):
        editor.create("a.py", "x")
        assert "a.py" in editor.summary()

    def test_list_edits_still_works(self, editor):
        editor.create("a.py", "x")
        assert len(editor.list_edits()) == 1

    def test_written_files_still_works(self, editor):
        editor.create("a.py", "x")
        assert "a.py" in editor.written_files()

    def test_total_bytes_still_works(self, editor):
        editor.create("a.py", "hello")
        assert editor.total_bytes_written() == 5
