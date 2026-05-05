from __future__ import annotations

from forgecc.core.engine_loop import (
    format_tool_call_log,
    format_tool_result_log,
)
from forgecc.toolkit import ToolResult


def test_format_tool_call_log_summarizes_dict_args():
    message, args = format_tool_call_log(
        ("call-1", "read_file", {"path": "a.py", "limit": 10})
    )

    assert message == "工具调用: %s(%s)"
    assert args == ("read_file", "path='a.py', limit=10")


def test_format_tool_call_log_truncates_long_values_and_marks_invalid_args():
    _, args = format_tool_call_log(("call-1", "write_file", {"content": "x" * 200}))
    assert args == ("write_file", "content=" + repr("x" * 200)[:80])

    _, args = format_tool_call_log(("call-2", "bad_args", ["not", "dict"]))
    assert args == ("bad_args", "<invalid args: list>")


def test_format_tool_result_log_reports_status_and_output_length():
    ok_message, ok_args = format_tool_result_log(
        ToolResult("call-1", "read_file", "hello")
    )
    fail_message, fail_args = format_tool_result_log(
        ToolResult("call-2", "write_file", "no", ok=False)
    )

    assert ok_message == "工具结果: %s %s → %d 字符"
    assert ok_args == ("✓", "read_file", 5)
    assert fail_message == "工具结果: %s %s → %d 字符"
    assert fail_args == ("✗", "write_file", 2)
