"""Engine normal tool execution orchestration."""

from __future__ import annotations

from collections.abc import Callable

from ..context.tool_storage import persist_if_large
from .engine_tool_logging import format_tool_call_log, format_tool_result_log
from .engine_tool_results import persist_tool_results, tool_result_messages


ToolCall = tuple[str, object, object]
RunBatchFn = Callable[[list[ToolCall]], list[object]]
AppendMessageFn = Callable[[dict], object]
PersistResultFn = Callable[[str, str, str], str]
LogFn = Callable[..., object]


def execute_normal_tool_calls(
    *,
    session_id: str,
    calls: list[ToolCall],
    run_batch: RunBatchFn,
    append_message: AppendMessageFn,
    persist: PersistResultFn = persist_if_large,
    info: LogFn | None = None,
    warn: Callable[[str], object] | None = None,
) -> list[object]:
    """Run normal tool calls and feed persisted results back to transcript."""
    for call in calls:
        message, args = format_tool_call_log(call)
        if info is not None:
            info(message, *args)

    results = run_batch(calls)

    for result in results:
        message, args = format_tool_result_log(result)
        if info is not None:
            info(message, *args)

    persist_tool_results(
        session_id,
        results,
        persist=persist,
        warn=warn,
    )
    for message in tool_result_messages(results):
        append_message(message)

    return results
