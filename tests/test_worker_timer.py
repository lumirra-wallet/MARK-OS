"""Tests for smartagent.performance.worker_timer — v2.0 Phase 1."""

import pytest
from smartagent.performance.worker_timer import WorkerTiming, format_timing_table


class TestWorkerTiming:
    def _make(self, **kwargs):
        defaults = dict(
            worker_name="Coding Worker",
            model_id="qwen2.5-coder:7b",
            prompt_text="a" * 400,    # 100 estimated tokens
            response_text="b" * 200,  # 50 estimated tokens
            generation_time=2.0,
        )
        defaults.update(kwargs)
        return WorkerTiming.record(**defaults)

    def test_record_returns_timing(self):
        t = self._make()
        assert isinstance(t, WorkerTiming)

    def test_prompt_tokens_estimated(self):
        t = self._make(prompt_text="a" * 400)
        assert t.prompt_tokens == 100

    def test_response_tokens_estimated(self):
        t = self._make(response_text="b" * 200)
        assert t.response_tokens == 50

    def test_tokens_per_sec(self):
        t = self._make(response_text="b" * 200, generation_time=1.0)
        # 50 tokens / 1.0s = 50.0
        assert t.tokens_per_sec == 50.0

    def test_zero_time_no_crash(self):
        t = self._make(generation_time=0.0)
        assert t.tokens_per_sec >= 0

    def test_was_cached_flag(self):
        t = self._make(was_cached=True)
        assert t.was_cached is True

    def test_was_stub_flag(self):
        t = self._make(was_stub=True)
        assert t.was_stub is True

    def test_model_stored(self):
        t = self._make(model_id="llama3:8b")
        assert t.model == "llama3:8b"

    def test_model_none_becomes_unknown(self):
        t = self._make(model_id=None)
        assert t.model == "unknown"

    def test_as_display_lines_list(self):
        t = self._make()
        lines = t.as_display_lines()
        assert isinstance(lines, list)
        assert len(lines) >= 3

    def test_as_display_lines_contains_worker_name(self):
        t = self._make(worker_name="Research Worker")
        text = "\n".join(t.as_display_lines())
        assert "Research Worker" in text

    def test_as_display_lines_cached_label(self):
        t = self._make(was_cached=True)
        text = "\n".join(t.as_display_lines())
        assert "CACHED" in text

    def test_as_display_lines_stub_label(self):
        t = self._make(was_stub=True)
        text = "\n".join(t.as_display_lines())
        assert "STUB" in text

    def test_prompt_chars_stored(self):
        t = self._make(prompt_text="hello")
        assert t.prompt_chars == 5

    def test_response_chars_stored(self):
        t = self._make(response_text="hi")
        assert t.response_chars == 2


class TestFormatTimingTable:
    def _make_timing(self, name="Worker", gen_time=2.0):
        return WorkerTiming.record(
            worker_name=name,
            model_id="llama3:8b",
            prompt_text="a" * 400,
            response_text="b" * 200,
            generation_time=gen_time,
        )

    def test_empty_list(self):
        result = format_timing_table([])
        assert "no timing data" in result.lower()

    def test_single_entry(self):
        result = format_timing_table([self._make_timing("Coding Worker")])
        assert "Coding Worker" in result
        assert "Worker Timing Report" in result

    def test_multiple_entries(self):
        timings = [
            self._make_timing("Research Worker", 1.5),
            self._make_timing("Coding Worker", 3.0),
        ]
        result = format_timing_table(timings)
        assert "Research Worker" in result
        assert "Coding Worker" in result

    def test_total_section_present(self):
        result = format_timing_table([self._make_timing()])
        assert "Total" in result

    def test_total_time(self):
        timings = [self._make_timing(gen_time=3.5)]
        result = format_timing_table(timings)
        assert "3.50" in result

    def test_returns_string(self):
        result = format_timing_table([self._make_timing()])
        assert isinstance(result, str)
