"""Engine tool call preparation helpers."""

from __future__ import annotations

from typing import Callable, Iterable


ToolCall = tuple[str, object, object]
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
