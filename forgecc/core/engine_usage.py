"""Engine token usage accounting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompletionUsageReport:
    input_tokens: int
    output_tokens: int
    text_chars: int
    invocation_count: int


def record_completion_usage(
    state: Any,
    completion: Any,
    *,
    now: float,
) -> CompletionUsageReport:
    """Update engine usage counters from a provider completion."""
    state._last_input_tokens = completion.usage_in
    state._last_api_call_time = now
    state._total_input_tokens += completion.usage_in
    state._total_output_tokens += completion.usage_out
    return CompletionUsageReport(
        input_tokens=completion.usage_in,
        output_tokens=completion.usage_out,
        text_chars=len(completion.text),
        invocation_count=len(completion.invocations),
    )
