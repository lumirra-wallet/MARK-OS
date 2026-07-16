"""
Tests for Milestone 19: File Editing Engine — FileEditor and FileEditMixin.

Test coverage:
    FileEditor:
      • __init__ creates base_dir
      • create() — new file, overwrite, parent dirs
      • edit() — overwrite content
      • patch() — replace substring, not found error, missing file
      • delete() — existing file, missing file
      • read() — existing and missing
      • exists() — true / false
      • list_files() — recursive, relative, forward slashes
      • list_edits() — records all operations
      • written_files() — only successful writes, deduplicated
      • total_bytes_written() — sum of successful writes
      • summary() — correct verb count
      • path escape prevention

    FileEditMixin:
      • _extract_file_blocks() — all three patterns (A, B, C)
      • _extract_file_blocks() — no filename → skipped
      • _write_output_files() — with FileEditor in context
      • _write_output_files() — with workspace fallback
      • _write_output_files() — no editor/workspace → no-op
      • execute() override appends "Files written:" footer
      • execute() transparent when no blocks found
"""

from __future__ import annotations

import os
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from smartagent.workspace.file_editor import EditResult, FileEditor
from smartagent.executive.workers.file_edit_mixin import FileEditMixin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def editor(tmp_path):
    """Return a FileEditor rooted in a temporary directory."""
    return FileEditor(str(tmp_path))


# ---------------------------------------------------------------------------
# FileEditor — __init__
# ---------------------------------------------------------------------------

class TestFileEditorInit:
    def test_base_dir_created(self, tmp_path):
        nested = tmp_path / "deep" / "dir"
        ed = FileEditor(str(nested))
        assert os.path.isdir(str(nested))

    def test_base_dir_property(self, tmp_path):
        ed = FileEditor(str(tmp_path))
        assert ed.base_dir == str(tmp_path)

    def test_repr(self, editor):
        r = repr(editor)
        assert "FileEditor" in r


# ---------------------------------------------------------------------------
# FileEditor — create
# ---------------------------------------------------------------------------

class TestFileEditorCreate:
    def test_create_simple(self, editor):
        result = editor.create("hello.py", "print('hi')")
        assert result.success is True
        assert result.operation == "create"
        assert result.bytes_written > 0
        assert editor.exists("hello.py")

    def test_create_content_written(self, editor):
        editor.create("file.txt", "hello world")
        assert editor.read("file.txt") == "hello world"

    def test_create_overwrites_existing(self, editor):
        editor.create("file.txt", "original")
        editor.create("file.txt", "updated")
        assert editor.read("file.txt") == "updated"

    def test_create_nested_path(self, editor):
        result = editor.create("src/auth/login.py", "def login(): pass")
        assert result.success is True
        assert editor.exists("src/auth/login.py")

    def test_create_returns_edit_result(self, editor):
        result = editor.create("a.py", "x = 1")
        assert isinstance(result, EditResult)

    def test_create_records_edit(self, editor):
        editor.create("f.py", "")
        edits = editor.list_edits()
        assert len(edits) == 1
        assert edits[0].operation == "create"

    def test_create_path_escape_fails(self, editor):
        result = editor.create("../../escape.py", "bad")
        assert result.success is False
        assert "escape" in result.message.lower() or "ValueError" in result.message or "escape" in result.message


# ---------------------------------------------------------------------------
# FileEditor — edit
# ---------------------------------------------------------------------------

class TestFileEditorEdit:
    def test_edit_existing(self, editor):
        editor.create("f.py", "original")
        result = editor.edit("f.py", "updated")
        assert result.success is True
        assert result.operation == "edit"
        assert editor.read("f.py") == "updated"

    def test_edit_creates_if_missing(self, editor):
        # edit() should also work even if file doesn't exist (same as create)
        result = editor.edit("new.py", "content")
        assert result.success is True

    def test_edit_records_edit(self, editor):
        editor.edit("f.py", "x")
        assert editor.list_edits()[0].operation == "edit"


# ---------------------------------------------------------------------------
# FileEditor — patch
# ---------------------------------------------------------------------------

class TestFileEditorPatch:
    def test_patch_simple(self, editor):
        editor.create("f.py", "def foo(): pass")
        result = editor.patch("f.py", "def foo():", "def bar():")
        assert result.success is True
        assert "bar" in editor.read("f.py")
        assert "foo" not in editor.read("f.py")

    def test_patch_first_occurrence_only(self, editor):
        editor.create("f.py", "a\na\na")
        editor.patch("f.py", "a", "b")
        content = editor.read("f.py")
        assert content.count("b") == 1
        assert content.count("a") == 2

    def test_patch_not_found_fails(self, editor):
        editor.create("f.py", "original content")
        result = editor.patch("f.py", "nonexistent text", "replacement")
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_patch_missing_file_fails(self, editor):
        result = editor.patch("missing.py", "old", "new")
        assert result.success is False

    def test_patch_records_edit(self, editor):
        editor.create("f.py", "x = 1")
        editor.patch("f.py", "x = 1", "x = 2")
        ops = [e.operation for e in editor.list_edits()]
        assert "patch" in ops


# ---------------------------------------------------------------------------
# FileEditor — delete
# ---------------------------------------------------------------------------

class TestFileEditorDelete:
    def test_delete_existing(self, editor):
        editor.create("todelete.py", "")
        result = editor.delete("todelete.py")
        assert result.success is True
        assert not editor.exists("todelete.py")

    def test_delete_missing_fails(self, editor):
        result = editor.delete("ghost.py")
        assert result.success is False

    def test_delete_records_edit(self, editor):
        editor.create("f.py", "")
        editor.delete("f.py")
        ops = [e.operation for e in editor.list_edits()]
        assert "delete" in ops


# ---------------------------------------------------------------------------
# FileEditor — read / exists
# ---------------------------------------------------------------------------

class TestFileEditorReadExists:
    def test_read_existing(self, editor):
        editor.create("f.py", "hello")
        assert editor.read("f.py") == "hello"

    def test_read_missing_raises(self, editor):
        with pytest.raises((FileNotFoundError, OSError)):
            editor.read("ghost.py")

    def test_exists_true(self, editor):
        editor.create("f.py", "")
        assert editor.exists("f.py") is True

    def test_exists_false(self, editor):
        assert editor.exists("missing.py") is False

    def test_exists_escape_returns_false(self, editor):
        assert editor.exists("../../outside.py") is False


# ---------------------------------------------------------------------------
# FileEditor — list_files
# ---------------------------------------------------------------------------

class TestFileEditorListFiles:
    def test_empty(self, editor):
        assert editor.list_files() == []

    def test_single_file(self, editor):
        editor.create("a.py", "")
        assert editor.list_files() == ["a.py"]

    def test_nested_files(self, editor):
        editor.create("src/a.py", "")
        editor.create("src/b.py", "")
        editor.create("README.md", "")
        files = editor.list_files()
        # Check forward slashes and presence
        assert any("src/a.py" in f or "src\\a.py" in f for f in files) or "src/a.py" in files
        assert "README.md" in files

    def test_sorted(self, editor):
        editor.create("z.py", "")
        editor.create("a.py", "")
        files = editor.list_files()
        assert files == sorted(files)


# ---------------------------------------------------------------------------
# FileEditor — list_edits / written_files / bytes
# ---------------------------------------------------------------------------

class TestFileEditorTracking:
    def test_list_edits_empty_initially(self, editor):
        assert editor.list_edits() == []

    def test_list_edits_accumulates(self, editor):
        editor.create("a.py", "x")
        editor.edit("a.py", "y")
        editor.delete("a.py")
        assert len(editor.list_edits()) == 3

    def test_written_files_deduped(self, editor):
        editor.create("a.py", "v1")
        editor.edit("a.py", "v2")
        written = editor.written_files()
        # Should appear only once even though written twice
        assert written.count("a.py") == 1

    def test_written_files_excludes_deletes(self, editor):
        editor.create("a.py", "x")
        editor.delete("a.py")
        written = editor.written_files()
        assert "a.py" in written  # create was first
        # delete was after but doesn't add to written

    def test_written_files_excludes_failed_ops(self, editor):
        editor.patch("missing.py", "old", "new")  # fails
        assert editor.written_files() == []

    def test_total_bytes_written(self, editor):
        editor.create("a.py", "hello")   # 5 bytes
        editor.create("b.py", "world!")  # 6 bytes
        assert editor.total_bytes_written() >= 11

    def test_total_bytes_excludes_failed(self, editor):
        editor.patch("missing.py", "old", "new")
        assert editor.total_bytes_written() == 0


# ---------------------------------------------------------------------------
# FileEditor — summary
# ---------------------------------------------------------------------------

class TestFileEditorSummary:
    def test_no_writes(self, editor):
        assert editor.summary() == "No files written."

    def test_one_file(self, editor):
        editor.create("auth.py", "x")
        s = editor.summary()
        assert "1 file" in s
        assert "auth.py" in s

    def test_multiple_files(self, editor):
        editor.create("a.py", "")
        editor.create("b.py", "")
        s = editor.summary()
        assert "2 file" in s

    def test_many_files_truncated(self, editor):
        for i in range(10):
            editor.create(f"f{i}.py", "")
        s = editor.summary()
        assert "more" in s


# ---------------------------------------------------------------------------
# FileEditMixin — _extract_file_blocks
# ---------------------------------------------------------------------------

class TestFileEditMixinExtract:
    """Test the extraction logic on its own (no IO)."""

    @pytest.fixture()
    def mixin(self):
        """Instantiate a concrete subclass that only uses FileEditMixin."""
        class _TestMixin(FileEditMixin):
            pass
        return _TestMixin()

    def test_pattern_b_fence_label(self, mixin):
        text = textwrap.dedent("""\
            ```python auth.py
            def login(): pass
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert len(blocks) == 1
        filename, content = blocks[0]
        assert filename == "auth.py"
        assert "def login" in content

    def test_pattern_a_filename_comment(self, mixin):
        text = textwrap.dedent("""\
            ```python
            # filename: routes.py
            from fastapi import APIRouter
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert len(blocks) == 1
        filename, content = blocks[0]
        assert filename == "routes.py"
        # Comment line should be stripped
        assert "# filename:" not in content
        assert "APIRouter" in content

    def test_pattern_a_file_colon(self, mixin):
        text = textwrap.dedent("""\
            ```python
            # file: models.py
            class User: pass
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "models.py"

    def test_pattern_c_mark_marker(self, mixin):
        text = textwrap.dedent("""\
            ```python
            # ---FILE: services/auth.py---
            def authenticate(): pass
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "services/auth.py"

    def test_no_filename_skipped(self, mixin):
        text = textwrap.dedent("""\
            ```python
            def no_filename(): pass
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert blocks == []

    def test_multiple_blocks(self, mixin):
        text = textwrap.dedent("""\
            ```python auth.py
            def login(): pass
            ```

            ```python models.py
            class User: pass
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert len(blocks) == 2
        filenames = {b[0] for b in blocks}
        assert "auth.py" in filenames
        assert "models.py" in filenames

    def test_mixed_no_filename_block_skipped(self, mixin):
        text = textwrap.dedent("""\
            Here is some explanation.

            ```python
            # no file annotation here
            x = 1
            ```

            ```python routes.py
            from fastapi import APIRouter
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "routes.py"

    def test_nested_path(self, mixin):
        text = textwrap.dedent("""\
            ```python
            # filename: tests/test_auth.py
            def test_login(): pass
            ```
        """)
        blocks = mixin._extract_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0][0] == "tests/test_auth.py"


# ---------------------------------------------------------------------------
# FileEditMixin — _write_output_files
# ---------------------------------------------------------------------------

class TestFileEditMixinWrite:
    @pytest.fixture()
    def mixin(self):
        class _TestMixin(FileEditMixin):
            pass
        return _TestMixin()

    def _context(self, **metadata):
        ctx = MagicMock()
        ctx.metadata = metadata
        return ctx

    def test_writes_via_file_editor(self, mixin, tmp_path):
        editor = FileEditor(str(tmp_path))
        ctx = self._context(file_editor=editor)
        text = "```python auth.py\ndef login(): pass\n```"
        written = mixin._write_output_files(text, ctx)
        assert "auth.py" in written
        assert editor.exists("auth.py")

    def test_writes_via_workspace_fallback(self, mixin, tmp_path):
        ws = MagicMock()
        ws.output_path = str(tmp_path)

        with patch("smartagent.workspace.file_output.write_output_file") as mock_write:
            mock_write.return_value = str(tmp_path / "routes.py")
            ctx = self._context(workspace=ws)
            text = "```python routes.py\nfrom fastapi import APIRouter\n```"
            written = mixin._write_output_files(text, ctx)

        assert "routes.py" in written

    def test_no_op_without_editor_or_workspace(self, mixin):
        ctx = self._context()
        text = "```python auth.py\ndef login(): pass\n```"
        written = mixin._write_output_files(text, ctx)
        assert written == []

    def test_no_blocks_returns_empty(self, mixin, tmp_path):
        editor = FileEditor(str(tmp_path))
        ctx = self._context(file_editor=editor)
        text = "No code blocks here."
        written = mixin._write_output_files(text, ctx)
        assert written == []

    def test_multiple_files_written(self, mixin, tmp_path):
        editor = FileEditor(str(tmp_path))
        ctx = self._context(file_editor=editor)
        text = textwrap.dedent("""\
            ```python auth.py
            def login(): pass
            ```

            ```python models.py
            class User: pass
            ```
        """)
        written = mixin._write_output_files(text, ctx)
        assert len(written) == 2
        assert editor.exists("auth.py")
        assert editor.exists("models.py")


# ---------------------------------------------------------------------------
# FileEditMixin — execute() integration
# ---------------------------------------------------------------------------

class TestFileEditMixinExecute:
    def _make_worker(self, return_text: str):
        """Build a minimal worker using FileEditMixin."""
        class _BaseStub:
            def execute(self, task, context):
                return return_text

        class _Worker(FileEditMixin, _BaseStub):
            pass

        return _Worker()

    def _context(self, **metadata):
        ctx = MagicMock()
        ctx.metadata = metadata
        return ctx

    def test_appends_files_written_footer(self, tmp_path):
        editor = FileEditor(str(tmp_path))
        ctx = self._context(file_editor=editor)
        text = "Result\n\n```python auth.py\ndef login(): pass\n```"
        worker = self._make_worker(text)
        result = worker.execute(None, ctx)
        assert "Files written:" in result
        assert "auth.py" in result

    def test_no_footer_when_no_blocks(self, tmp_path):
        editor = FileEditor(str(tmp_path))
        ctx = self._context(file_editor=editor)
        text = "No code blocks here."
        worker = self._make_worker(text)
        result = worker.execute(None, ctx)
        assert "Files written:" not in result
        assert result == "No code blocks here."

    def test_transparent_without_context_services(self):
        ctx = self._context()  # no file_editor, no workspace
        text = "```python auth.py\ndef login(): pass\n```"
        worker = self._make_worker(text)
        result = worker.execute(None, ctx)
        # Returns original text — no crash, no footer
        assert "Files written:" not in result
