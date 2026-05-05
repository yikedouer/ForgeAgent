from __future__ import annotations

from forgecc.core.engine_loop import execute_normal_tool_calls
from forgecc.toolkit import ToolResult


def test_execute_normal_tool_calls_logs_runs_persists_and_appends_messages():
    calls = [("call-1", "read_file", {"path": "a.py"})]
    logs = []
    appended = []

    results = execute_normal_tool_calls(
        session_id="session-1",
        calls=calls,
        run_batch=lambda received: [ToolResult("call-1", "read_file", "raw")]
        if received == calls else [],
        append_message=appended.append,
        persist=lambda session_id, name, output: f"{session_id}:{name}:{output}",
        info=lambda message, *args: logs.append((message, args)),
    )

    assert [result.output for result in results] == ["session-1:read_file:raw"]
    assert appended == [{
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "session-1:read_file:raw",
    }]
    assert logs == [
        ("工具调用: %s(%s)", ("read_file", "path='a.py'")),
        ("工具结果: %s %s → %d 字符", ("✓", "read_file", 3)),
    ]


def test_execute_normal_tool_calls_warns_when_persist_fails_and_appends_raw_output():
    warnings = []
    appended = []

    def persist(_session_id, _name, _output):
        raise OSError("disk full")

    results = execute_normal_tool_calls(
        session_id="session-1",
        calls=[("call-1", "read_file", {})],
        run_batch=lambda _calls: [ToolResult("call-1", "read_file", "raw")],
        append_message=appended.append,
        persist=persist,
        warn=warnings.append,
    )

    assert [result.output for result in results] == ["raw"]
    assert appended == [{
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "raw",
    }]
    assert warnings == ["工具结果持久化失败: read_file — disk full"]
