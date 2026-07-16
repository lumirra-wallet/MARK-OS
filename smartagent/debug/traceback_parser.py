"""
TracebackParser — Milestone 20: Self Debugging.

Parses Python tracebacks from test runner output (pytest, unittest, or raw
Python interpreter) into structured :class:`ParsedTraceback` objects.

Supported formats
-----------------
* Standard Python interpreter tracebacks:
  ``Traceback (most recent call last): …``
* pytest ``--tb=long`` and ``--tb=short`` output
* pytest ``FAILED`` / ``ERROR`` markers

Output
------
:class:`ParsedTraceback` with:

  * ``frames``        — stack frames, outermost first
  * ``error_type``    — e.g. ``"AssertionError"``
  * ``error_message`` — the message string after the colon
  * ``root_cause_frame`` — last non-library frame (property)
  * ``raw``           — the original text chunk

Usage::

    parser = TracebackParser()
    tbs    = parser.parse_all(pytest_output)
    first  = parser.parse(output)   # → ParsedTraceback | None
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TracebackFrame:
    """One frame in a Python traceback."""
    filepath: str        # may be absolute or relative
    lineno: int
    function: str
    code: str            # the source line at that frame (may be empty)


@dataclass
class ParsedTraceback:
    """
    Structured representation of a single Python traceback.

    Attributes:
        frames:        Stack frames, outermost first.
        error_type:    Exception class name, e.g. ``"AssertionError"``.
        error_message: Full message string after the colon.
        raw:           The raw traceback text chunk.
        test_name:     Pytest test node id if present (e.g. ``"tests/test_foo.py::test_bar"``).
    """

    frames:        list[TracebackFrame] = field(default_factory=list)
    error_type:    str = ""
    error_message: str = ""
    raw:           str = ""
    test_name:     str = ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def root_cause_frame(self) -> Optional[TracebackFrame]:
        """
        Return the last user-code frame (not stdlib / site-packages).

        Heuristics:
          - Skip frames whose path contains ``site-packages``.
          - Skip frames whose path contains ``/lib/python``.
          - Skip pseudo-paths ``"<string>"`` and ``"<stdin>"``.

        If all frames look like library frames, returns the last frame.
        """
        user_frames = [
            f for f in self.frames
            if _is_user_frame(f.filepath)
        ]
        if user_frames:
            return user_frames[-1]
        return self.frames[-1] if self.frames else None

    def one_line(self) -> str:
        """Return a short one-line summary of the traceback."""
        rcf = self.root_cause_frame
        loc = f" [{rcf.filepath}:{rcf.lineno}]" if rcf else ""
        msg = self.error_message[:80]
        if self.error_type:
            return f"{self.error_type}: {msg}{loc}"
        return f"Error: {msg}{loc}"

    def as_display_lines(self) -> list[str]:
        """Format the traceback for console display."""
        lines: list[str] = []
        if self.test_name:
            lines.append(f"  Test: {self.test_name}")
        lines.append(f"  Error: {self.error_type}: {self.error_message[:120]}")
        rcf = self.root_cause_frame
        if rcf:
            lines.append(f"  File : {rcf.filepath}, line {rcf.lineno}, in {rcf.function}")
            if rcf.code:
                lines.append(f"  Code : {rcf.code}")
        if len(self.frames) > 1:
            lines.append(f"  Depth: {len(self.frames)} frames")
        return lines

    def __str__(self) -> str:
        return self.one_line()


def _is_user_frame(filepath: str) -> bool:
    """Return True if *filepath* looks like user code rather than a library."""
    p = filepath.replace("\\", "/")
    return (
        "site-packages" not in p
        and "/lib/python" not in p
        and not p.startswith("<")
    )


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches:  File "/path/to/file.py", line 42, in function_name
_FRAME_HEADER_RE = re.compile(
    r'^\s{0,4}File\s+"(?P<path>[^"]+)",\s+line\s+(?P<lineno>\d+),\s+in\s+(?P<func>\S+)',
)

# Matches the final error line after the frames.
# Handles:
#   AssertionError: message
#   E   AssertionError: message   (pytest short mode)
#   smartagent.foo.CustomError: message
_ERROR_LINE_RE = re.compile(
    r'^(?:E\s+)?'
    r'(?P<type>'
    r'(?:[A-Za-z_][A-Za-z0-9_]*\.)*'   # optional dotted prefix
    r'(?:[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning|Interrupt|Stop|Exit)'
    r'|AssertionError|KeyboardInterrupt|StopIteration|SystemExit)'
    r')'
    r'(?::\s*(?P<msg>.*))?$',
)

# Matches pytest FAILED/ERROR markers
_PYTEST_MARKER_RE = re.compile(
    r'^(?:FAILED|ERROR)\s+(?P<node>[^\s]+)',
)

# Split text on traceback start markers
_TB_START_RE = re.compile(
    r'(?=Traceback \(most recent call last\):)',
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class TracebackParser:
    """
    Parse Python tracebacks from raw test/interpreter output.

    Usage::

        parser = TracebackParser()

        # Parse all tracebacks in a block of text
        all_tb = parser.parse_all(output)

        # Parse just the first one
        first  = parser.parse(output)   # → ParsedTraceback | None
    """

    def parse(self, text: str) -> Optional[ParsedTraceback]:
        """Return the first :class:`ParsedTraceback` found in *text*, or None."""
        results = self.parse_all(text)
        return results[0] if results else None

    def parse_all(self, text: str) -> list[ParsedTraceback]:
        """Return all :class:`ParsedTraceback` objects found in *text*."""
        results: list[ParsedTraceback] = []

        # Split on the traceback start sentinel
        parts = _TB_START_RE.split(text)
        for part in parts:
            if "Traceback (most recent call last):" not in part:
                continue
            tb = self._parse_one(part)
            if tb is not None:
                results.append(tb)

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_one(self, text: str) -> Optional[ParsedTraceback]:
        """Parse a single traceback chunk into a :class:`ParsedTraceback`."""
        lines = text.splitlines()
        tb    = ParsedTraceback(raw=text)

        in_frames = False
        i = 0
        while i < len(lines):
            line = lines[i]

            # Detect pytest test markers near the start
            pm = _PYTEST_MARKER_RE.match(line)
            if pm and not tb.test_name:
                tb.test_name = pm.group("node")
                i += 1
                continue

            # Detect the traceback start sentinel
            if "Traceback (most recent call last):" in line:
                in_frames = True
                i += 1
                continue

            if not in_frames:
                i += 1
                continue

            # Try to match a frame header:  File "…", line N, in func
            fm = _FRAME_HEADER_RE.match(line)
            if fm:
                frame = TracebackFrame(
                    filepath=fm.group("path"),
                    lineno=int(fm.group("lineno")),
                    function=fm.group("func"),
                    code="",
                )
                # The next line is the source code at that frame (if present)
                j = i + 1
                if j < len(lines):
                    next_line = lines[j]
                    # It's a source line if it doesn't start with another frame header
                    if not _FRAME_HEADER_RE.match(next_line) and next_line.strip():
                        frame.code = next_line.strip()
                        i = j  # consumed one extra line
                tb.frames.append(frame)
                i += 1
                continue

            # Try to match the error type line (after all frames)
            em = _ERROR_LINE_RE.match(line.strip())
            if em and tb.frames:
                tb.error_type    = em.group("type")
                tb.error_message = (em.group("msg") or "").strip()
                in_frames = False
                i += 1
                continue

            i += 1

        # A valid traceback needs at least a frame or an error type
        if not tb.frames and not tb.error_type:
            return None
        return tb
