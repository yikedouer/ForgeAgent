"""No-LLM compaction tier helpers."""

from __future__ import annotations

import time

from forgecc.context.compaction_tiers import (
    MICROCOMPACT_IDLE_S,
    SNIP_PLACEHOLDER,
    _build_tool_name_map,
    _budget_tool_results,
    _microcompact_idle,
    _prune,
    _snip_stale_results,
)


def _tool_call(call_id: str, name: str, arguments: str = "{}") -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _assistant_msg(tool_calls: list | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": ""}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _tool_msg(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _user_msg(text: str) -> dict:
    return {"role": "user", "content": text}


def test_tool_name_map_and_stale_snip_live_in_tier_module():
    msgs = [
        _assistant_msg([_tool_call("c1", "read_file", '{"file_path": "/a.py"}')]),
        _tool_msg("c1", "old"),
        _assistant_msg([_tool_call("c2", "read_file", '{"file_path": "/a.py"}')]),
        _tool_msg("c2", "new"),
        _assistant_msg([_tool_call("c3", "shell")]),
        _tool_msg("c3", "out"),
        _assistant_msg([_tool_call("c4", "read_file", '{"file_path": "/b.py"}')]),
        _tool_msg("c4", "other"),
    ]

    assert _build_tool_name_map(msgs) == {
        "c1": "read_file",
        "c2": "read_file",
        "c3": "shell",
        "c4": "read_file",
    }
    assert _snip_stale_results(msgs, 0.7) is True
    assert msgs[1]["content"] == SNIP_PLACEHOLDER


def test_budget_tool_results_truncates_in_tier_module():
    msgs = [_tool_msg("c1", "x" * 100_000)]

    assert _budget_tool_results(msgs, 0.8) is True
    assert len(msgs[0]["content"]) < 20_000
    assert "budgeted" in msgs[0]["content"]


def test_microcompact_idle_keeps_recent_tool_results():
    msgs = [_tool_msg(f"c{i}", f"data{i}") for i in range(5)]
    old_time = time.time() - MICROCOMPACT_IDLE_S - 1

    assert _microcompact_idle(msgs, old_time) is True
    assert [m["content"] for m in msgs] == [
        "[Old result cleared]",
        "[Old result cleared]",
        "data2",
        "data3",
        "data4",
    ]


def test_prune_keeps_system_and_safe_tail():
    msgs = [{"role": "system", "content": "sys"}] + [
        _user_msg(f"msg{i}") for i in range(8)
    ]

    assert _prune(msgs, keep_recent=3) is True
    assert msgs[0]["role"] == "system"
    assert "PRUNED" in msgs[1]["content"]
    assert [m["content"] for m in msgs[-3:]] == ["msg5", "msg6", "msg7"]
