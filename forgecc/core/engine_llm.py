"""Engine LLM invocation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..context.compaction import _prune
from .errors import ContextWindowError


PruneFn = Callable[[list[dict], int], object]


@dataclass(frozen=True)
class GenerateRecoveryResult:
    completion: object
    collapse_reset: bool = False


def generate_with_context_recovery(
    *,
    provider: object,
    wire_messages: list[dict],
    tool_schemas: list[dict],
    on_token: Callable[[str], None] | None,
    directive: str,
    transcript: list[dict],
    prune: PruneFn = _prune,
) -> GenerateRecoveryResult:
    try:
        completion = provider.generate(
            messages=wire_messages,
            tool_schemas=tool_schemas,
            on_token=on_token,
        )
        return GenerateRecoveryResult(completion)
    except ContextWindowError:
        prune(transcript, 4)
        completion = provider.generate(
            messages=[{"role": "system", "content": directive}] + transcript,
            tool_schemas=tool_schemas,
            on_token=on_token,
        )
        return GenerateRecoveryResult(completion, collapse_reset=True)
