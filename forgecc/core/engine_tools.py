"""Engine tool call preparation, logging, execution, and transcript feedback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Iterable

from ..context.tool_storage import persist_if_large


ToolCall = tuple[str, object, object]
RunBatchFn = Callable[[list[ToolCall]], list[object]]
AppendMessageFn = Callable[[dict], object]
PersistResultFn = Callable[[str, str, str], str]
LogFn = Callable[..., object]
WarnFn = Callable[[str], None]


def build_tool_calls(invocations: Iterable[object]) -> list[ToolCall]:
    return [
        (inv.call_id, inv.fn_name, inv.fn_args)
        for inv in invocations
    ]


def split_plan_tool_calls(
    calls: list[ToolCall],
    *,
    plan_tool_names: set[str],
) -> tuple[list[ToolCall], list[ToolCall]]:
    plan_calls = [
        call for call in calls
        if isinstance(call[1], str) and call[1] in plan_tool_names
    ]
    normal_calls = [
        call for call in calls
        if not (isinstance(call[1], str) and call[1] in plan_tool_names)
    ]
    return plan_calls, normal_calls


def notify_instrument_callbacks(
    invocations: Iterable[object],
    callback: Callable[[str, dict], None] | None,
    *,
    warn: WarnFn | None = None,
) -> None:
    if callback is None:
        return
    for inv in invocations:
        try:
            callback(inv.fn_name, inv.fn_args)
        except Exception as exc:
            if warn:
                warn(f"工具回调异常: {exc}")


def _tool_call_id(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def append_plan_tool_results(
    calls: list[ToolCall],
    *,
    execute_plan_tool: Callable[[str], str],
    append_message: Callable[[dict], object],
) -> None:
    """Execute plan-mode tool calls and append their tool messages."""
    for idx, (call_id, fn_name, _args) in enumerate(calls):
        result_text = execute_plan_tool(str(fn_name))
        append_message({
            "role": "tool",
            "tool_call_id": _tool_call_id(call_id, f"call_{idx}"),
            "content": result_text,
        })


def format_tool_call_log(call: tuple[object, object, object]) -> tuple[str, tuple[object, ...]]:
    _call_id, fn_name, args = call
    if isinstance(args, dict):
        args_preview = ", ".join(
            f"{key}={repr(value)[:80]}" for key, value in args.items()
        )
    else:
        args_preview = f"<invalid args: {type(args).__name__}>"
    return "工具调用: %s(%s)", (fn_name, args_preview)


def format_tool_result_log(result: object) -> tuple[str, tuple[object, ...]]:
    status = "✓" if result.ok else "✗"
    return "工具结果: %s %s → %d 字符", (
        status,
        result.name,
        len(result.output),
    )


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
