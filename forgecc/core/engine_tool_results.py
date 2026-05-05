"""Engine tool result persistence and transcript helpers."""

from __future__ import annotations

from typing import Callable, Iterable

from ..context.tool_storage import persist_if_large


PersistResultFn = Callable[[str, str, str], str]
WarnFn = Callable[[str], None]


def persist_tool_results(
    session_id: str,
    results: Iterable[object],
    *,
    persist: PersistResultFn = persist_if_large,
    warn: WarnFn | None = None,
) -> None:
    for result in results:
        try:
            result.output = persist(session_id, result.name, result.output)
        except Exception as exc:
            if warn:
                warn(f"工具结果持久化失败: {result.name} — {exc}")


def tool_result_messages(results: Iterable[object]) -> list[dict]:
    return [
        {
            "role": "tool",
            "tool_call_id": result.call_id,
            "content": result.output,
        }
        for result in results
    ]
