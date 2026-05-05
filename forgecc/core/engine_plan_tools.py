"""Engine plan-mode tool result helpers."""

from __future__ import annotations

from collections.abc import Callable


ToolCall = tuple[object, object, object]


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
