from __future__ import annotations

from forgecc.context.compaction_tool_entries import (
    collect_snippable_tool_entries,
    parse_tool_args_map,
)
from forgecc.context.compaction import SNIP_PLACEHOLDER


def _tool_call(call_id: object, name: str, arguments: object = "{}") -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _assistant_msg(tool_calls: list) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": tool_calls}


def _tool_msg(call_id: object, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_parse_tool_args_map_collects_json_object_arguments():
    messages = [
        _assistant_msg([
            _tool_call("c1", "read_file", '{"file_path": "/a.py"}'),
            _tool_call("bad-list", "read_file", '["bad"]'),
            _tool_call("bad-json", "read_file", "{"),
            _tool_call(["bad-id"], "read_file", '{"file_path": "/bad.py"}'),
        ])
    ]

    assert parse_tool_args_map(messages) == {"c1": {"file_path": "/a.py"}}


def test_collect_snippable_tool_entries_uses_tool_names_args_and_skips_placeholders():
    messages = [
        _assistant_msg([
            _tool_call("c1", "read_file", '{"file_path": "/a.py"}'),
            _tool_call("c2", "shell"),
            _tool_call("c3", "write_file"),
            _tool_call("c4", "grep_search", '{"path": "/b.py"}'),
        ]),
        _tool_msg("c1", "old read"),
        _tool_msg("c2", SNIP_PLACEHOLDER),
        _tool_msg("c3", "write output"),
        _tool_msg("c4", "grep output"),
        "not-a-message",
    ]

    entries = collect_snippable_tool_entries(messages)

    assert entries == [
        {"idx": 1, "name": "read_file", "file_path": "/a.py"},
        {"idx": 4, "name": "grep_search", "file_path": "/b.py"},
    ]
