"""压缩管道测试 — forgeagent.context.compaction"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from forgeagent.context.compaction import (
    _estimate_tokens,
    _msg_tokens,
    _conversation_tokens,
    _safe_split_point,
    _build_tool_name_map,
    _budget_tool_results,
    _snip,
    _snip_stale_results,
    _microcompact_idle,
    _prune,
    maybe_compact,
    CompactionResult,
    SNIP_PLACEHOLDER,
    KEEP_RECENT_RESULTS,
    MICROCOMPACT_IDLE_S,
)


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def _tool_call(call_id: str, name: str, arguments: str = "{}") -> dict:
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _assistant_msg(text: str = "", tool_calls: list | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": text}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _tool_msg(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _user_msg(text: str) -> dict:
    return {"role": "user", "content": text}


def _system_msg(text: str = "You are a helpful assistant.") -> dict:
    return {"role": "system", "content": text}


# ═══════════════════════════════════════════════════════════════
# 1. _estimate_tokens
# ═══════════════════════════════════════════════════════════════

class TestEstimateTokens:
    def test_ascii(self):
        assert _estimate_tokens("abcd") == 1

    def test_longer_ascii(self):
        text = "a" * 100
        assert _estimate_tokens(text) == 13

    def test_empty_string(self):
        assert _estimate_tokens("") == 1

    def test_cjk_mixed(self):
        assert _estimate_tokens("你好世界abcd") == 6


# ═══════════════════════════════════════════════════════════════
# 2. _msg_tokens / _conversation_tokens
# ═══════════════════════════════════════════════════════════════

class TestMsgTokens:
    def test_content_only(self):
        msg = _user_msg("a" * 40)
        assert _msg_tokens(msg) == 5

    def test_with_tool_calls(self):
        msg = _assistant_msg("text", [_tool_call("c1", "read_file")])
        tokens = _msg_tokens(msg)
        assert tokens > 0

    def test_empty_msg(self):
        msg = {"role": "user"}
        assert _msg_tokens(msg) == 0


class TestConversationTokens:
    def test_sum(self):
        msgs = [_user_msg("a" * 40), _user_msg("b" * 80)]
        assert _conversation_tokens(msgs) == 25

    def test_skips_non_object_messages(self):
        msgs = [_user_msg("a" * 40), "not-a-message"]

        assert _conversation_tokens(msgs) == 5


# ═══════════════════════════════════════════════════════════════
# 3. _safe_split_point
# ═══════════════════════════════════════════════════════════════

class TestSafeSplitPoint:
    def test_no_tool_boundary(self):
        msgs = [_system_msg(), _user_msg("a"), _user_msg("b"), _user_msg("c")]
        assert _safe_split_point(msgs, 2) == 2

    def test_avoids_tool_role(self):
        msgs = [_system_msg(), _user_msg("a"),
                _assistant_msg("", [_tool_call("c1", "fn")]),
                _tool_msg("c1", "result"),
                _user_msg("b")]
        # desired=3 落在 tool_msg 上，应回退
        point = _safe_split_point(msgs, 3)
        assert point < 3

    def test_avoids_assistant_tool_calls(self):
        # idx-1 检查的是 messages[idx-1]
        # desired=3: messages[2] 是 assistant+tool_calls → 回退
        # desired=2: messages[1] 是 user → 停止
        msgs = [_system_msg(), _user_msg("a"),
                _assistant_msg("", [_tool_call("c1", "fn")]),
                _tool_msg("c1", "result"),
                _user_msg("b")]
        point = _safe_split_point(msgs, 3)
        # 从 3 回退：messages[2]=assistant+tc → idx=2, messages[1]=user → 停止
        assert point == 2

    def test_minimum_one(self):
        msgs = [_tool_msg("c1", "r")]
        assert _safe_split_point(msgs, 0) >= 1

    def test_ignores_non_object_messages(self):
        msgs = [_system_msg(), "not-a-message", _user_msg("b")]

        assert _safe_split_point(msgs, 2) == 2


# ═══════════════════════════════════════════════════════════════
# 4. _build_tool_name_map
# ═══════════════════════════════════════════════════════════════

class TestBuildToolNameMap:
    def test_maps_tool_calls(self):
        msgs = [_assistant_msg("", [_tool_call("c1", "read_file"),
                                    _tool_call("c2", "shell")])]
        mapping = _build_tool_name_map(msgs)
        assert mapping == {"c1": "read_file", "c2": "shell"}

    def test_ignores_non_assistant(self):
        msgs = [_user_msg("hello")]
        assert _build_tool_name_map(msgs) == {}

    def test_ignores_non_object_messages(self):
        msgs = [
            "not-a-message",
            _assistant_msg("", [_tool_call("c1", "read_file")]),
        ]

        mapping = _build_tool_name_map(msgs)

        assert mapping == {"c1": "read_file"}

    def test_ignores_malformed_tool_calls(self):
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": {"bad": "shape"}},
            {"role": "assistant", "content": "", "tool_calls": ["bad"]},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "bad", "function": "bad"}]},
            _assistant_msg("", [_tool_call("c1", "read_file")]),
        ]

        mapping = _build_tool_name_map(msgs)

        assert mapping == {"c1": "read_file"}

    def test_ignores_non_string_call_ids(self):
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": ["bad"], "function": {"name": "read_file"}}]},
            _assistant_msg("", [_tool_call("c1", "read_file")]),
        ]

        mapping = _build_tool_name_map(msgs)

        assert mapping == {"c1": "read_file"}


# ═══════════════════════════════════════════════════════════════
# 5. _budget_tool_results — Tier 1a
# ═══════════════════════════════════════════════════════════════

class TestBudgetToolResults:
    def test_low_utilization_noop(self):
        msgs = [_tool_msg("c1", "x" * 100_000)]
        assert _budget_tool_results(msgs, 0.4) is False
        assert len(msgs[0]["content"]) == 100_000

    def test_high_utilization_truncates(self):
        msgs = [_tool_msg("c1", "x" * 100_000)]
        assert _budget_tool_results(msgs, 0.8) is True
        # 15K budget
        assert len(msgs[0]["content"]) < 20_000
        assert "budgeted" in msgs[0]["content"]

    def test_medium_utilization_truncates(self):
        msgs = [_tool_msg("c1", "x" * 100_000)]
        assert _budget_tool_results(msgs, 0.6) is True
        # 30K budget
        assert len(msgs[0]["content"]) < 35_000
        assert "budgeted" in msgs[0]["content"]

    def test_small_content_unchanged(self):
        msgs = [_tool_msg("c1", "small")]
        assert _budget_tool_results(msgs, 0.8) is False
        assert msgs[0]["content"] == "small"

    def test_skips_non_object_messages(self):
        msgs = ["not-a-message", _tool_msg("c1", "x" * 100_000)]

        assert _budget_tool_results(msgs, 0.8) is True
        assert "budgeted" in msgs[1]["content"]

    def test_ignores_malformed_function_payloads(self):
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "bad", "function": "bad"}]},
            _tool_msg("c1", "x" * 100_000),
        ]

        assert _budget_tool_results(msgs, 0.8) is True
        assert "budgeted" in msgs[1]["content"]


# ═══════════════════════════════════════════════════════════════
# 6. _snip — Tier 1b
# ═══════════════════════════════════════════════════════════════

class TestSnip:
    @patch("forgeagent.context.tool_storage.apply_result_budget", return_value=False)
    def test_old_long_tool_summarized(self, mock_budget):
        # 10 条消息，keep_recent=2 → 前 8 条视为旧消息
        # 内容需超过 200 字符且超过 3 行才会被摘要
        lines = "\n".join([f"line-content-padded-{i:04d}" for i in range(20)])
        msgs = [_tool_msg(f"c{i}", lines if i == 0 else "ok") for i in range(10)]
        result = _snip(msgs, "sess", keep_recent=2)
        assert result is True
        # 第一条被摘要
        assert "snipped" in msgs[0]["content"]

    @patch("forgeagent.context.tool_storage.apply_result_budget", return_value=False)
    def test_recent_kept(self, mock_budget):
        lines = "\n".join([f"line{i}" for i in range(20)])
        msgs = [_tool_msg(f"c{i}", lines) for i in range(4)]
        _snip(msgs, "sess", keep_recent=4)
        # 全部在 keep_recent 内，不应被修改
        for m in msgs:
            assert "snipped" not in m["content"]

    @patch("forgeagent.context.tool_storage.apply_result_budget", return_value=True)
    def test_apply_budget_propagates(self, mock_budget):
        msgs = [_tool_msg("c1", "ok")]
        result = _snip(msgs, "sess")
        assert result is True  # apply_result_budget 返回 True

    @patch("forgeagent.context.tool_storage.apply_result_budget", return_value=False)
    def test_skips_non_object_messages(self, mock_budget):
        lines = "\n".join([f"line-content-padded-{i:04d}" for i in range(20)])
        msgs = ["not-a-message", _tool_msg("c1", lines)]

        result = _snip(msgs, "sess", keep_recent=0)

        assert result is True
        assert "snipped" in msgs[1]["content"]


# ═══════════════════════════════════════════════════════════════
# 7. _snip_stale_results — Tier 2
# ═══════════════════════════════════════════════════════════════

class TestSnipStaleResults:
    def _make_read_file_pair(self, call_id: str, path: str, content: str):
        """返回 (assistant_msg, tool_msg) 对。"""
        args = f'{{"file_path": "{path}"}}'
        return (
            _assistant_msg("", [_tool_call(call_id, "read_file", args)]),
            _tool_msg(call_id, content),
        )

    def test_low_utilization_noop(self):
        msgs = [_user_msg("hi")]
        assert _snip_stale_results(msgs, 0.5) is False

    def test_dedup_read_file(self):
        # 同一路径读两次，应保留最新
        pair1 = self._make_read_file_pair("c1", "/a.py", "old content")
        pair2 = self._make_read_file_pair("c2", "/a.py", "new content")
        pair3 = self._make_read_file_pair("c3", "/b.py", "b content")
        pair4 = self._make_read_file_pair("c4", "/c.py", "c content")
        msgs = list(pair1) + list(pair2) + list(pair3) + list(pair4)
        result = _snip_stale_results(msgs, 0.7)
        assert result is True
        # pair1 的 tool_msg（索引 1）应被 snip
        assert msgs[1]["content"] == SNIP_PLACEHOLDER

    def test_keep_recent(self):
        # 只有 3 个工具结果，不会裁剪
        pair1 = self._make_read_file_pair("c1", "/a.py", "a")
        pair2 = self._make_read_file_pair("c2", "/b.py", "b")
        pair3 = self._make_read_file_pair("c3", "/c.py", "c")
        msgs = list(pair1) + list(pair2) + list(pair3)
        assert _snip_stale_results(msgs, 0.7) is False

    def test_already_snipped_skipped(self):
        pair1 = self._make_read_file_pair("c1", "/a.py", SNIP_PLACEHOLDER)
        pair2 = self._make_read_file_pair("c2", "/b.py", "b")
        pair3 = self._make_read_file_pair("c3", "/c.py", "c")
        pair4 = self._make_read_file_pair("c4", "/d.py", "d")
        msgs = list(pair1) + list(pair2) + list(pair3) + list(pair4)
        # c1 已是 placeholder，只有 c2/c3/c4 三个有效工具结果
        assert _snip_stale_results(msgs, 0.7) is False

    def test_non_object_tool_arguments_do_not_crash(self):
        bad_pair = (
            _assistant_msg("", [_tool_call("c1", "read_file", '["bad"]')]),
            _tool_msg("c1", "bad args content"),
        )
        pair2 = self._make_read_file_pair("c2", "/b.py", "b")
        pair3 = self._make_read_file_pair("c3", "/c.py", "c")
        pair4 = self._make_read_file_pair("c4", "/d.py", "d")
        msgs = list(bad_pair) + list(pair2) + list(pair3) + list(pair4)

        result = _snip_stale_results(msgs, 0.7)

        assert result is True
        assert msgs[1]["content"] == SNIP_PLACEHOLDER

    def test_skips_non_object_messages(self):
        pair1 = self._make_read_file_pair("c1", "/a.py", "old content")
        pair2 = self._make_read_file_pair("c2", "/a.py", "new content")
        pair3 = self._make_read_file_pair("c3", "/b.py", "b content")
        pair4 = self._make_read_file_pair("c4", "/c.py", "c content")
        msgs = ["not-a-message"] + list(pair1) + list(pair2) + list(pair3) + list(pair4)

        result = _snip_stale_results(msgs, 0.7)

        assert result is True
        assert msgs[2]["content"] == SNIP_PLACEHOLDER

    def test_ignores_non_string_call_ids(self):
        pair1 = self._make_read_file_pair("c1", "/a.py", "old content")
        pair2 = self._make_read_file_pair("c2", "/a.py", "new content")
        pair3 = self._make_read_file_pair("c3", "/b.py", "b content")
        pair4 = self._make_read_file_pair("c4", "/c.py", "c content")
        msgs = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": ["bad"], "function": {"name": "read_file"}}]},
            {"role": "tool", "tool_call_id": ["bad"], "content": "bad id content"},
            *list(pair1),
            *list(pair2),
            *list(pair3),
            *list(pair4),
        ]

        result = _snip_stale_results(msgs, 0.7)

        assert result is True
        assert msgs[3]["content"] == SNIP_PLACEHOLDER


# ═══════════════════════════════════════════════════════════════
# 8. _microcompact_idle — Tier 2b
# ═══════════════════════════════════════════════════════════════

class TestMicrocompactIdle:
    def test_no_last_api_call(self):
        msgs = [_tool_msg("c1", "data")]
        assert _microcompact_idle(msgs, None) is False

    def test_recent_activity(self):
        msgs = [_tool_msg("c1", "data")]
        assert _microcompact_idle(msgs, time.time()) is False

    def test_idle_clears_old(self):
        # 5 个工具消息，空闲 >5 分钟
        msgs = [_tool_msg(f"c{i}", f"data{i}") for i in range(6)]
        old_time = time.time() - MICROCOMPACT_IDLE_S - 10
        result = _microcompact_idle(msgs, old_time)
        assert result is True
        # 前 3 个被清除（6 - 3 = 3 个清除）
        for i in range(3):
            assert msgs[i]["content"] == "[Old result cleared]"
        # 后 3 个保留
        for i in range(3, 6):
            assert msgs[i]["content"] == f"data{i}"

    def test_too_few_noop(self):
        # 只有 2 个工具消息（< KEEP_RECENT_RESULTS），不清除
        msgs = [_tool_msg(f"c{i}", f"data{i}") for i in range(2)]
        old_time = time.time() - MICROCOMPACT_IDLE_S - 10
        assert _microcompact_idle(msgs, old_time) is False

    def test_skips_non_object_messages(self):
        msgs = ["not-a-message"] + [_tool_msg(f"c{i}", f"data{i}") for i in range(6)]
        old_time = time.time() - MICROCOMPACT_IDLE_S - 10

        result = _microcompact_idle(msgs, old_time)

        assert result is True
        assert msgs[1]["content"] == "[Old result cleared]"


# ═══════════════════════════════════════════════════════════════
# 11. _prune — 紧急裁剪
# ═══════════════════════════════════════════════════════════════

class TestPrune:
    def test_normal_prune(self):
        msgs = [_system_msg()] + [_user_msg(f"msg{i}") for i in range(10)]
        result = _prune(msgs, keep_recent=3)
        assert result is True
        assert msgs[0]["role"] == "system"
        assert "PRUNED" in msgs[1]["content"]
        # 系统 + header + 尾部 3 条 = 5 条
        assert len(msgs) <= 6

    def test_too_few_messages(self):
        msgs = [_system_msg(), _user_msg("hi")]
        assert _prune(msgs, keep_recent=4) is False

    def test_no_system_msg(self):
        msgs = [_user_msg(f"msg{i}") for i in range(10)]
        result = _prune(msgs, keep_recent=3)
        assert result is True
        assert "PRUNED" in msgs[0]["content"]

    def test_non_object_first_message_is_not_system(self):
        msgs = ["not-a-message"] + [_user_msg(f"msg{i}") for i in range(10)]

        result = _prune(msgs, keep_recent=3)

        assert result is True
        assert "PRUNED" in msgs[0]["content"]


# ═══════════════════════════════════════════════════════════════
# 11. maybe_compact — 主入口
# ═══════════════════════════════════════════════════════════════

class TestMaybeCompact:
    def test_low_utilization_noop(self):
        # 利用率 < 50% → 不压缩
        msgs = [_user_msg("a" * 40)]
        result = maybe_compact(msgs, budget=1_000_000)
        assert result.performed is False
        assert result.collapse is None

    def test_tier1a_budget(self):
        # 大工具结果 + 中等利用率
        big_content = "x" * 100_000
        msgs = [_tool_msg("c1", big_content)]
        # budget 设小使 utilization > 0.5
        result = maybe_compact(msgs, budget=100, last_input_tokens=80)
        assert result.performed is True or len(msgs[0]["content"]) < 100_000

    def test_emergency_prune(self):
        # 利用率 > 95% → 紧急裁剪
        msgs = [_system_msg()] + [_user_msg("x" * 400) for _ in range(20)]
        result = maybe_compact(msgs, budget=100, last_input_tokens=96)
        assert result.performed is True

    def test_result_dataclass(self):
        r = CompactionResult(performed=True, collapse=None)
        assert r.performed is True
        assert r.collapse is None
