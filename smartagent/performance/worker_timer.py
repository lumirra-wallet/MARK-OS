"""
WorkerTimer — per-worker execution timing for MARK's performance audit.

Records:
  - worker name
  - model used
  - prompt size (chars + estimated tokens)
  - response size (chars + estimated tokens)
  - total generation time
  - tokens/sec estimate

Usage (inside OllamaWorkerMixin)::

    import time
    from smartagent.performance.worker_timer import WorkerTiming, format_timing_table

    t0 = time.perf_counter()
    text = self._stream_response(context, messages)
    elapsed = time.perf_counter() - t0

    timing = WorkerTiming.record(
        worker_name="Coding Worker",
        model_id="qwen2.5-coder:7b",
        prompt_text=joined_prompt,
        response_text=text or "",
        generation_time=elapsed,
    )

    # Stored in context.metadata["worker_timings"] list
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Characters per token — rough BPE estimate; good enough for display
_CHARS_PER_TOKEN: int = 4


@dataclass
class WorkerTiming:
    """Timing record for one worker execution."""

    worker_name: str
    model: str
    prompt_chars: int
    prompt_tokens: int
    response_chars: int
    response_tokens: int
    generation_time: float    # seconds total
    tokens_per_sec: float
    was_cached: bool = False
    was_stub: bool = False

    @classmethod
    def record(
        cls,
        *,
        worker_name: str,
        model_id: str | None,
        prompt_text: str,
        response_text: str,
        generation_time: float,
        was_cached: bool = False,
        was_stub: bool = False,
    ) -> "WorkerTiming":
        """Construct a :class:`WorkerTiming` from raw measurements."""
        p_chars = len(prompt_text)
        r_chars = len(response_text)
        p_tok = max(1, p_chars // _CHARS_PER_TOKEN)
        r_tok = max(1, r_chars // _CHARS_PER_TOKEN)
        tps = r_tok / max(generation_time, 0.001)
        return cls(
            worker_name=worker_name,
            model=model_id or "unknown",
            prompt_chars=p_chars,
            prompt_tokens=p_tok,
            response_chars=r_chars,
            response_tokens=r_tok,
            generation_time=generation_time,
            tokens_per_sec=round(tps, 1),
            was_cached=was_cached,
            was_stub=was_stub,
        )

    def as_display_lines(self) -> list[str]:
        """Return a compact display block for this worker."""
        status = ""
        if self.was_cached:
            status = " [CACHED]"
        elif self.was_stub:
            status = " [STUB]"

        lines = [
            f"  {self.worker_name}{status}",
            f"    Prompt  : {self.prompt_tokens:>5} tokens  ({self.prompt_chars} chars)",
            f"    Output  : {self.response_tokens:>5} tokens  ({self.response_chars} chars)",
            f"    Time    : {self.generation_time:>6.2f}s   ({self.tokens_per_sec} tok/s)",
        ]
        return lines


def format_timing_table(timings: list[WorkerTiming]) -> str:
    """
    Format a list of :class:`WorkerTiming` records into a display table.

    Example output::

        ── Worker Timing Report ──────────────────────────
          Research Worker
            Prompt  :   155 tokens  (620 chars)
            Output  :    90 tokens  (360 chars)
            Time    :   3.80s   (23.7 tok/s)
          Coding Worker
            Prompt  :   275 tokens  (1100 chars)
            Output  :   320 tokens  (1280 chars)
            Time    :   6.20s   (51.6 tok/s)
        ── Total ─────────────────────────────────────────
          Workers   :   2
          Tokens in :   430
          Tokens out:   410
          Wall time :  10.00s
        ──────────────────────────────────────────────────
    """
    if not timings:
        return "  (no timing data)"

    lines: list[str] = ["── Worker Timing Report ──────────────────────────"]
    for t in timings:
        lines.extend(t.as_display_lines())

    total_in = sum(t.prompt_tokens for t in timings)
    total_out = sum(t.response_tokens for t in timings)
    total_time = sum(t.generation_time for t in timings)
    cached = sum(1 for t in timings if t.was_cached)

    lines.append("── Total ─────────────────────────────────────────")
    lines.append(f"  Workers   : {len(timings)}")
    lines.append(f"  Tokens in : {total_in}")
    lines.append(f"  Tokens out: {total_out}")
    lines.append(f"  Wall time : {total_time:>6.2f}s")
    if cached:
        lines.append(f"  Cache hits: {cached}")
    lines.append("──────────────────────────────────────────────────")
    return "\n".join(lines)
