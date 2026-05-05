"""Engine tool logging format helpers."""

from __future__ import annotations


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
