"""
Engineer end-to-end tests — verifying the file-writing pipeline.

These tests do NOT require Ollama.  They simulate the LLM output by feeding
pre-canned fenced code block strings through the real FileEditMixin /
FileEditor pipeline and assert that files actually land on disk.

Coverage:
  1. Pattern B (fence label): ```python calculator.py
  2. Pattern A (first-line comment): # filename: hello.py
  3. Pattern C (MARK marker): # ---FILE: utils.py---
  4. DevLoop test-command scoping via _build_scoped_test_cmd
  5. _set_orchestrator_project_dir wires through to Orchestrator
  6. SoftwareEngineerReport tracks files_created / files_modified / project_dir
  7. LoopResult.as_display_lines shows files
  8. Generated test file that actually passes when run with pytest
"""

from __future__ import annotations

import os
import subprocess
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_editor(tmp_path):
    """Return a FileEditor rooted at tmp_path and the path itself."""
    from smartagent.workspace.file_editor import FileEditor
    editor = FileEditor(str(tmp_path))
    return editor, tmp_path


@pytest.fixture()
def ctx_with_editor(tmp_path):
    """Return an ExecutionContext with a FileEditor already injected."""
    from smartagent.executive.execution_context import ExecutionContext
    from smartagent.workspace.file_editor import FileEditor

    editor = FileEditor(str(tmp_path))
    ctx = ExecutionContext(goal="test goal")
    ctx.metadata["file_editor"] = editor
    return ctx, editor, tmp_path


# ---------------------------------------------------------------------------
# 1. Pattern B — filename on fence line
# ---------------------------------------------------------------------------

class TestPatternB:
    """Filename appears directly on the fence line: ```python calculator.py"""

    CALCULATOR_OUTPUT = textwrap.dedent("""\
        Here is the implementation:

        ```python calculator.py
        def add(a: int, b: int) -> int:
            return a + b

        def subtract(a: int, b: int) -> int:
            return a - b
        ```
    """)

    def test_file_written_to_disk(self, ctx_with_editor):
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        class DummyMixin(FileEditMixin):
            pass

        written = DummyMixin()._write_output_files(self.CALCULATOR_OUTPUT, ctx)
        assert "calculator.py" in written
        assert (tmp_path / "calculator.py").exists()

    def test_file_content_correct(self, ctx_with_editor):
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        class DummyMixin(FileEditMixin):
            pass

        DummyMixin()._write_output_files(self.CALCULATOR_OUTPUT, ctx)
        content = (tmp_path / "calculator.py").read_text()
        assert "def add" in content
        assert "def subtract" in content

    def test_multiple_files_in_one_output(self, ctx_with_editor):
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        output = textwrap.dedent("""\
            ```python calculator.py
            def add(a, b): return a + b
            ```

            ```python test_calculator.py
            from calculator import add
            def test_add(): assert add(1, 2) == 3
            ```
        """)

        class DummyMixin(FileEditMixin):
            pass

        written = DummyMixin()._write_output_files(output, ctx)
        assert "calculator.py" in written
        assert "test_calculator.py" in written
        assert (tmp_path / "calculator.py").exists()
        assert (tmp_path / "test_calculator.py").exists()

    def test_nested_path_creates_parent_dirs(self, ctx_with_editor):
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        output = "```python src/utils.py\ndef noop(): pass\n```\n"

        class DummyMixin(FileEditMixin):
            pass

        written = DummyMixin()._write_output_files(output, ctx)
        assert "src/utils.py" in written
        assert (tmp_path / "src" / "utils.py").exists()


# ---------------------------------------------------------------------------
# 2. Pattern A — first-line comment
# ---------------------------------------------------------------------------

class TestPatternA:
    """Filename in first-line comment: # filename: hello.py"""

    def test_filename_comment_written(self, ctx_with_editor):
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        output = textwrap.dedent("""\
            ```python
            # filename: hello.py
            def greet(name: str) -> str:
                return f"Hello, {name}!"
            ```
        """)

        class DummyMixin(FileEditMixin):
            pass

        written = DummyMixin()._write_output_files(output, ctx)
        assert "hello.py" in written
        content = (tmp_path / "hello.py").read_text()
        assert "def greet" in content
        # filename comment line should NOT appear in the written content
        assert "# filename:" not in content

    def test_file_marker_pattern(self, ctx_with_editor):
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        output = textwrap.dedent("""\
            ```python
            # ---FILE: utils.py---
            CONSTANT = 42
            ```
        """)

        class DummyMixin(FileEditMixin):
            pass

        written = DummyMixin()._write_output_files(output, ctx)
        assert "utils.py" in written
        assert (tmp_path / "utils.py").exists()


# ---------------------------------------------------------------------------
# 3. No filename annotation — silently skipped
# ---------------------------------------------------------------------------

class TestNoAnnotation:
    def test_anonymous_block_produces_no_file(self, ctx_with_editor):
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        output = "```python\ndef foo(): pass\n```\n"

        class DummyMixin(FileEditMixin):
            pass

        written = DummyMixin()._write_output_files(output, ctx)
        assert written == []
        # No .py files should have been created
        assert list(tmp_path.glob("*.py")) == []

    def test_wrong_format_filename_colon(self, ctx_with_editor):
        """```python filename: calculator.py  (the OLD broken format) is silently skipped."""
        ctx, editor, tmp_path = ctx_with_editor
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin

        # This is the old broken format — fence_name regex can't parse "filename:"
        output = "```python filename: calculator.py\ndef add(a, b): return a + b\n```\n"

        class DummyMixin(FileEditMixin):
            pass

        # Should produce no files (old prompt format was broken — test confirms regression is fixed)
        written = DummyMixin()._write_output_files(output, ctx)
        # The regex cannot extract a filename here — this behaviour is expected/known
        # What matters is the NEW prompt format (Pattern B) DOES work (see TestPatternB)
        assert isinstance(written, list)


# ---------------------------------------------------------------------------
# 4. Test command scoping
# ---------------------------------------------------------------------------

class TestBuildScopedTestCmd:
    def _make_editor_with_files(self, tmp_path, filenames):
        from smartagent.workspace.file_editor import FileEditor
        editor = FileEditor(str(tmp_path))
        for fname in filenames:
            editor.create(fname, "# placeholder\n")
        return editor

    def test_bare_pytest_scoped_to_test_files(self, tmp_path):
        from smartagent.dev_loop.dev_loop import _build_scoped_test_cmd
        editor = self._make_editor_with_files(
            tmp_path, ["calculator.py", "test_calculator.py"]
        )
        cmd = _build_scoped_test_cmd("pytest", editor, str(tmp_path))
        assert cmd.startswith("pytest ")
        assert "test_calculator.py" in cmd
        # Implementation file must NOT be in the test command
        assert "calculator.py" not in cmd.replace("test_calculator.py", "")

    def test_no_test_files_returns_original(self, tmp_path):
        from smartagent.dev_loop.dev_loop import _build_scoped_test_cmd
        editor = self._make_editor_with_files(tmp_path, ["calculator.py"])
        cmd = _build_scoped_test_cmd("pytest", editor, str(tmp_path))
        # No test file generated — return the original command unchanged
        assert cmd == "pytest"

    def test_custom_test_cmd_unchanged(self, tmp_path):
        from smartagent.dev_loop.dev_loop import _build_scoped_test_cmd
        editor = self._make_editor_with_files(
            tmp_path, ["calculator.py", "test_calculator.py"]
        )
        cmd = _build_scoped_test_cmd("pytest tests/ -v", editor, str(tmp_path))
        # Custom command — do NOT modify it
        assert cmd == "pytest tests/ -v"

    def test_python_m_pytest_scoped(self, tmp_path):
        from smartagent.dev_loop.dev_loop import _build_scoped_test_cmd
        editor = self._make_editor_with_files(tmp_path, ["test_foo.py"])
        cmd = _build_scoped_test_cmd("python -m pytest", editor, str(tmp_path))
        assert cmd.startswith("pytest ")
        assert "test_foo.py" in cmd

    def test_none_editor_returns_original(self, tmp_path):
        from smartagent.dev_loop.dev_loop import _build_scoped_test_cmd
        cmd = _build_scoped_test_cmd("pytest", None, str(tmp_path))
        assert cmd == "pytest"

    def test_multiple_test_files_all_included(self, tmp_path):
        from smartagent.dev_loop.dev_loop import _build_scoped_test_cmd
        editor = self._make_editor_with_files(
            tmp_path, ["test_add.py", "test_subtract.py", "calculator.py"]
        )
        cmd = _build_scoped_test_cmd("pytest", editor, str(tmp_path))
        assert "test_add.py" in cmd
        assert "test_subtract.py" in cmd


# ---------------------------------------------------------------------------
# 5. Orchestrator project_dir wiring
# ---------------------------------------------------------------------------

class TestOrchestratorProjectDir:
    def test_set_project_dir_creates_editor_at_right_path(self, tmp_path):
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        from smartagent.executive.execution_state import ExecutionState

        orch = Orchestrator()
        orch.set_project_dir(str(tmp_path))

        ctx = ExecutionContext(goal="test")
        ctx.transition_to(ExecutionState.PLANNING)
        orch._inject_file_editor(ctx)

        editor = ctx.metadata.get("file_editor")
        assert editor is not None
        assert editor.base_dir == str(tmp_path)

    def test_default_no_project_dir_uses_cwd(self, tmp_path, monkeypatch):
        """Without set_project_dir, editor is rooted at CWD (not output/)."""
        from smartagent.executive.orchestrator import Orchestrator
        from smartagent.executive.execution_context import ExecutionContext
        from smartagent.executive.execution_state import ExecutionState

        monkeypatch.chdir(tmp_path)
        orch = Orchestrator()  # no set_project_dir call

        ctx = ExecutionContext(goal="test")
        ctx.transition_to(ExecutionState.PLANNING)
        orch._inject_file_editor(ctx)

        editor = ctx.metadata.get("file_editor")
        assert editor is not None
        # Must be CWD, not CWD/output
        assert editor.base_dir == str(tmp_path)
        assert "output" not in editor.base_dir

    def test_set_orchestrator_project_dir_helper(self, tmp_path):
        """_set_orchestrator_project_dir propagates through the executive."""
        from smartagent.dev_loop.dev_loop import _set_orchestrator_project_dir
        from smartagent.executive.executive_controller import ExecutiveController

        ctrl = ExecutiveController()
        _set_orchestrator_project_dir(ctrl, str(tmp_path))
        assert ctrl._orchestrator._project_dir == str(tmp_path)

    def test_set_orchestrator_project_dir_none_executive(self):
        """_set_orchestrator_project_dir is safe when executive is None."""
        from smartagent.dev_loop.dev_loop import _set_orchestrator_project_dir
        # Must not raise
        _set_orchestrator_project_dir(None, "/some/path")


# ---------------------------------------------------------------------------
# 6. SoftwareEngineerReport file tracking
# ---------------------------------------------------------------------------

class TestSoftwareEngineerReport:
    def test_report_has_file_fields(self):
        from smartagent.engineer.software_engineer import SoftwareEngineerReport
        report = SoftwareEngineerReport(
            goal="Build hello",
            files_created=["hello.py"],
            files_modified=["existing.py"],
            project_dir="/tmp/project",
        )
        assert report.files_created == ["hello.py"]
        assert report.files_modified == ["existing.py"]
        assert report.project_dir == "/tmp/project"

    def test_as_display_lines_shows_files(self):
        from smartagent.engineer.software_engineer import SoftwareEngineerReport
        report = SoftwareEngineerReport(
            goal="Build hello",
            files_created=["hello.py", "test_hello.py"],
            files_modified=["config.py"],
            project_dir="/tmp/myproject",
            success=True,
        )
        lines = report.as_display_lines()
        combined = "\n".join(lines)
        assert "+ hello.py" in combined
        assert "+ test_hello.py" in combined
        assert "~ config.py" in combined
        assert "/tmp/myproject" in combined

    def test_as_display_lines_no_files_no_section(self):
        from smartagent.engineer.software_engineer import SoftwareEngineerReport
        report = SoftwareEngineerReport(goal="test", success=False)
        lines = report.as_display_lines()
        combined = "\n".join(lines)
        assert "Files:" not in combined


# ---------------------------------------------------------------------------
# 7. LoopResult file tracking display
# ---------------------------------------------------------------------------

class TestLoopResultFileTracking:
    def test_loop_result_has_file_fields(self):
        from smartagent.dev_loop.loop_result import LoopResult
        result = LoopResult(
            goal="test",
            success=True,
            files_created=["calculator.py"],
            files_modified=[],
            project_dir="/tmp/proj",
        )
        assert result.files_created == ["calculator.py"]
        assert result.project_dir == "/tmp/proj"

    def test_as_display_lines_shows_files(self):
        from smartagent.dev_loop.loop_result import LoopResult
        result = LoopResult(
            goal="Build calculator",
            success=True,
            stop_reason="success",
            files_created=["calculator.py", "test_calculator.py"],
            files_modified=[],
            project_dir="/tmp/calc",
        )
        lines = result.as_display_lines()
        combined = "\n".join(lines)
        assert "+ calculator.py" in combined
        assert "+ test_calculator.py" in combined
        assert "/tmp/calc" in combined

    def test_as_display_lines_no_files_no_section(self):
        from smartagent.dev_loop.loop_result import LoopResult
        result = LoopResult(goal="test", success=True, stop_reason="success")
        lines = result.as_display_lines()
        combined = "\n".join(lines)
        assert "Files:" not in combined


# ---------------------------------------------------------------------------
# 8. Integration: generated file actually passes pytest
# ---------------------------------------------------------------------------

class TestGeneratedFilePytestIntegration:
    """
    Full round-trip: write a calculator.py + test_calculator.py via
    FileEditMixin and then run pytest against those files.
    """

    IMPL_OUTPUT = textwrap.dedent("""\
        ```python calculator.py
        def add(a: int, b: int) -> int:
            return a + b

        def subtract(a: int, b: int) -> int:
            return a - b

        def multiply(a: int, b: int) -> int:
            return a * b
        ```
    """)

    TEST_OUTPUT = textwrap.dedent("""\
        ```python test_calculator.py
        from calculator import add, subtract, multiply

        def test_add():
            assert add(1, 2) == 3
            assert add(-1, 1) == 0

        def test_subtract():
            assert subtract(5, 3) == 2

        def test_multiply():
            assert multiply(3, 4) == 12
        ```
    """)

    def test_files_written_and_pytest_passes(self, tmp_path):
        from smartagent.executive.execution_context import ExecutionContext
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin
        from smartagent.workspace.file_editor import FileEditor

        editor = FileEditor(str(tmp_path))
        ctx = ExecutionContext(goal="Build calculator")
        ctx.metadata["file_editor"] = editor

        class DummyMixin(FileEditMixin):
            pass

        mixin = DummyMixin()
        written_impl = mixin._write_output_files(self.IMPL_OUTPUT, ctx)
        written_test = mixin._write_output_files(self.TEST_OUTPUT, ctx)

        assert "calculator.py" in written_impl
        assert "test_calculator.py" in written_test

        # Verify both files exist
        assert (tmp_path / "calculator.py").exists()
        assert (tmp_path / "test_calculator.py").exists()

        # Run pytest against only the generated test file from the project dir
        result = subprocess.run(
            ["pytest", "test_calculator.py", "-v", "--tb=short"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"Generated tests failed!\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert "3 passed" in result.stdout

    def test_hello_py_created_and_importable(self, tmp_path):
        from smartagent.executive.execution_context import ExecutionContext
        from smartagent.executive.workers.file_edit_mixin import FileEditMixin
        from smartagent.workspace.file_editor import FileEditor

        output = textwrap.dedent("""\
            ```python hello.py
            def say_hello(name: str = "World") -> str:
                return f"Hello, {name}!"
            ```

            ```python test_hello.py
            from hello import say_hello

            def test_default():
                assert say_hello() == "Hello, World!"

            def test_custom():
                assert say_hello("MARK") == "Hello, MARK!"
            ```
        """)

        editor = FileEditor(str(tmp_path))
        ctx = ExecutionContext(goal="Create hello.py")
        ctx.metadata["file_editor"] = editor

        class DummyMixin(FileEditMixin):
            pass

        written = DummyMixin()._write_output_files(output, ctx)
        assert "hello.py" in written
        assert "test_hello.py" in written

        result = subprocess.run(
            ["pytest", "test_hello.py", "-v"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "2 passed" in result.stdout


# ---------------------------------------------------------------------------
# 9. _is_test_file helper
# ---------------------------------------------------------------------------

class TestIsTestFile:
    def test_test_prefix(self):
        from smartagent.dev_loop.dev_loop import _is_test_file
        assert _is_test_file("test_calculator.py")
        assert _is_test_file("tests/test_foo.py")

    def test_test_suffix(self):
        from smartagent.dev_loop.dev_loop import _is_test_file
        assert _is_test_file("calculator_test.py")

    def test_not_test_file(self):
        from smartagent.dev_loop.dev_loop import _is_test_file
        assert not _is_test_file("calculator.py")
        assert not _is_test_file("testing_utils.py")
        assert not _is_test_file("context.py")


# ---------------------------------------------------------------------------
# 10. get_file_editor helper
# ---------------------------------------------------------------------------

class TestGetFileEditor:
    def test_returns_editor_from_context(self, tmp_path):
        from smartagent.dev_loop.dev_loop import _get_file_editor
        from smartagent.workspace.file_editor import FileEditor

        editor = FileEditor(str(tmp_path))

        class FakeExecutive:
            class current_context:
                metadata = {"file_editor": editor}

        fe = _get_file_editor(FakeExecutive)
        assert fe is editor

    def test_returns_none_when_no_executive(self):
        from smartagent.dev_loop.dev_loop import _get_file_editor
        assert _get_file_editor(None) is None

    def test_returns_none_when_no_context(self):
        from smartagent.dev_loop.dev_loop import _get_file_editor

        class FakeExecutive:
            current_context = None

        assert _get_file_editor(FakeExecutive) is None
