from __future__ import annotations

from forgeagent.core.engine_loop import persist_tool_results, tool_result_messages
from forgeagent.toolkit import ToolResult


def test_persist_tool_results_replaces_output_with_persisted_reference():
    results = [ToolResult("call-1", "read_file", "large output")]

    persist_tool_results(
        "session-1",
        results,
        persist=lambda session_id, name, output: f"{session_id}:{name}:{output}",
    )

    assert results[0].output == "session-1:read_file:large output"


def test_persist_tool_results_keeps_original_output_when_persist_fails():
    warnings = []
    results = [ToolResult("call-1", "read_file", "raw output")]

    def persist(session_id, name, output):
        raise OSError("disk full")

    persist_tool_results(
        "session-1",
        results,
        persist=persist,
        warn=warnings.append,
    )

    assert results[0].output == "raw output"
    assert warnings == ["工具结果持久化失败: read_file — disk full"]


def test_tool_result_messages_builds_transcript_messages():
    results = [
        ToolResult("call-1", "read_file", "one"),
        ToolResult("call-2", "write_file", "two", ok=False),
    ]

    assert tool_result_messages(results) == [
        {"role": "tool", "tool_call_id": "call-1", "content": "one"},
        {"role": "tool", "tool_call_id": "call-2", "content": "two"},
    ]
