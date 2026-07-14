"""
ResponseParser — Milestone 5, Part 7.

Normalizes whatever raw shape a provider's `generate()`/`stream()` returns
into one provider-agnostic `ParsedResponse`, so `ModelManager` (and, above
it, the Brain) never has to know whether a response came from
`MockModelProvider` or (eventually) a real provider with its own JSON
shape (`choices[0].message.content` vs `content` vs `output_text`, etc.).

Design decision: rather than hardcoding a single raw shape, `parse()`
checks a small, ordered list of common key names for each field (text,
tool calls, usage). This is deliberately generous — Milestone 5 only ships
`MockModelProvider`, which uses `content`/`tool_calls`/`usage`, but every
future provider stub documented in `future_providers.py` uses a subtly
different vendor shape, and this keeps `ModelManager` from needing a
per-provider branch when those land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Keys checked, in order, for each normalized field. Not provider-specific —
# just the union of shapes a JSON API response is plausible to use.
_TEXT_KEYS = ("content", "text", "output_text", "message")
_TOOL_CALL_KEYS = ("tool_calls", "tool_requests", "function_calls")
_USAGE_KEYS = ("usage", "usage_stats", "token_usage")
_CONFIDENCE_KEYS = ("confidence",)
_FINISH_REASON_KEYS = ("finish_reason", "stop_reason")


@dataclass(frozen=True)
class ToolRequest:
    """A single tool/function-call request surfaced by a model's response."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedResponse:
    """
    Normalized shape of a model response, regardless of which provider produced it.

    Attributes:
        text: The generated text, or `""` if the provider returned none
            (e.g. a pure tool-call response).
        tool_requests: Tool/function calls the model asked to make.
        confidence: Self-reported or inferred confidence, 0.0-1.0. Defaults
            to `1.0` for a successful generation with no provider-reported
            value — Milestone 5 does not implement any real confidence
            estimation, so this is intentionally a simple default, not a
            computed score.
        metadata: Anything else the provider returned that didn't map to a
            known field (model id, finish reason, raw provider name, etc.).
        timing_ms: Wall-clock time the call took, in milliseconds. Supplied
            by the caller (`ModelManager` times the call), not derived here.
        usage: Token usage stats, normalized to `prompt_tokens`/
            `completion_tokens`/`total_tokens` when the provider reports
            them under any of `_USAGE_KEYS`.
        provider: Which provider produced the raw response, for logging.
        parsed_at: ISO-8601 UTC timestamp of when parsing occurred.
    """

    text: str
    tool_requests: tuple[ToolRequest, ...] = ()
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timing_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = "unknown"
    parsed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class ResponseParser:
    """Normalizes raw provider responses into `ParsedResponse`."""

    def parse(self, raw: Any, *, provider: str = "unknown", timing_ms: float = 0.0) -> ParsedResponse:
        """
        Normalize `raw` (whatever a `BaseModel.generate()` implementation returned) into a `ParsedResponse`.

        Args:
            raw: The provider's raw response. Handles `dict`-shaped
                responses (what every provider documented so far returns);
                any other type is coerced to text via `str()` so parsing
                never raises on an unexpected shape.
            provider: Provider id, recorded on the result for logging/audit.
            timing_ms: Wall-clock generation time, supplied by the caller.

        Returns:
            A `ParsedResponse`. Never raises — an unparseable `raw` becomes
            a `ParsedResponse` with `text=str(raw)` and empty everything else.
        """
        if not isinstance(raw, dict):
            return ParsedResponse(text=str(raw), provider=provider, timing_ms=timing_ms)

        text = ""
        for key in _TEXT_KEYS:
            value = raw.get(key)
            if isinstance(value, str):
                text = value
                break

        tool_requests = tuple(self._parse_tool_requests(raw))
        confidence = self._first_float(raw, _CONFIDENCE_KEYS, default=1.0)
        usage = self._normalize_usage(raw)

        known_keys = set(_TEXT_KEYS) | set(_TOOL_CALL_KEYS) | set(_USAGE_KEYS) | set(_CONFIDENCE_KEYS)
        metadata = {k: v for k, v in raw.items() if k not in known_keys}
        for key in _FINISH_REASON_KEYS:
            if key in raw:
                metadata.setdefault("finish_reason", raw[key])

        return ParsedResponse(
            text=text,
            tool_requests=tool_requests,
            confidence=confidence,
            metadata=metadata,
            timing_ms=timing_ms,
            usage=usage,
            provider=provider,
        )

    @staticmethod
    def _parse_tool_requests(raw: dict[str, Any]) -> list[ToolRequest]:
        for key in _TOOL_CALL_KEYS:
            calls = raw.get(key)
            if not calls:
                continue
            requests: list[ToolRequest] = []
            for call in calls:
                if isinstance(call, dict):
                    requests.append(
                        ToolRequest(
                            name=str(call.get("name", "")),
                            arguments=dict(call.get("arguments", {}) or {}),
                        )
                    )
            return requests
        return []

    @staticmethod
    def _first_float(raw: dict[str, Any], keys: tuple[str, ...], *, default: float) -> float:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return default

    @staticmethod
    def _normalize_usage(raw: dict[str, Any]) -> dict[str, int]:
        for key in _USAGE_KEYS:
            usage = raw.get(key)
            if isinstance(usage, dict):
                return {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                    "total_tokens": int(
                        usage.get("total_tokens", usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
                    ),
                }
        return {}
