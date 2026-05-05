"""Engine-facing compaction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..context.compaction import CompactionResult, _conversation_tokens, maybe_compact
from ..context.collapse import CollapseState


@dataclass(frozen=True)
class ManualCompactionReport:
    result: CompactionResult
    before_messages: int
    after_messages: int
    before_tokens: int
    after_tokens: int
    context_budget: int


def run_manual_compaction(
    messages: list[dict],
    *,
    budget: int,
    provider: object,
    session_id: str,
    collapse_state: CollapseState | None,
    failure_count: list[int],
    compact: Callable[..., CompactionResult] = maybe_compact,
) -> ManualCompactionReport:
    """Run manual compaction and return before/after statistics."""
    before_messages = len(messages)
    before_tokens = _conversation_tokens(messages)
    result = compact(
        messages,
        budget,
        provider,
        session_id=session_id,
        collapse_state=collapse_state,
        failure_count=failure_count,
    )
    return ManualCompactionReport(
        result=result,
        before_messages=before_messages,
        after_messages=len(messages),
        before_tokens=before_tokens,
        after_tokens=_conversation_tokens(messages),
        context_budget=budget,
    )
