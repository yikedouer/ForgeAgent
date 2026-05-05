"""test_tool_storage.py — 工具结果持久化测试。"""

from __future__ import annotations

import pytest

import forgecc.context.tool_storage as ts
from forgecc.context.tool_storage import (
    persist_if_large,
    persist_large_result,
    load_persisted_result,
    apply_result_budget,
    reset_persisted_tracking,
    PERSIST_THRESHOLD,
    MAX_RESULT_SIZE_CHARS,
)


@pytest.fixture(autouse=True)
def _reset_tracking():
    reset_persisted_tracking()
    yield
    reset_persisted_tracking()


# ═══════════════════════════════════════════════════════════
# 11.1 persist_if_large
# ═══════════════════════════════════════════════════════════

class TestPersistIfLarge:
    def test_large_content_uses_env_session_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        content = "x" * (PERSIST_THRESHOLD + 1)

        result = persist_if_large("s_env", "read_file", content)

        assert f"saved to {tmp_path / 's_env' / 'tool-results'}" in result
        assert list((tmp_path / "s_env" / "tool-results").glob("*-read_file.txt"))

    def test_small_content_returned_as_is(self):
        content = "small output"
        result = persist_if_large("s1", "read_file", content)
        assert result == content

    def test_large_content_persisted(self):
        content = "x" * (PERSIST_THRESHOLD + 1)
        result = persist_if_large("s1", "read_file", content)
        assert "Result too large" in result
        assert "saved to" in result
        assert "Preview" in result

    def test_tool_name_path_separators_do_not_break_persistence(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        content = "x" * (PERSIST_THRESHOLD + 1)

        result = persist_if_large("s1", "custom/tool", content)

        assert "Result too large" in result
        files = list((tmp_path / "s1" / "tool-results").glob("*.txt"))
        assert len(files) == 1
        assert files[0].name.endswith("-custom_tool.txt")

    def test_rejects_blank_tool_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        content = "x" * (PERSIST_THRESHOLD + 1)

        with pytest.raises(ValueError, match="Invalid tool_name"):
            persist_if_large("s1", "   ", content)

        assert not (tmp_path / "s1" / "tool-results").exists()

    def test_rejects_session_id_path_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        content = "x" * (PERSIST_THRESHOLD + 1)

        with pytest.raises(ValueError, match="Invalid session_id"):
            persist_if_large("../escape", "read_file", content)

        assert not (tmp_path.parent / "escape").exists()

    def test_same_second_large_results_do_not_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        monkeypatch.setattr(ts._time, "time", lambda: 1234567890)
        first = "a" * (PERSIST_THRESHOLD + 1)
        second = "b" * (PERSIST_THRESHOLD + 1)

        persist_if_large("s1", "read_file", first)
        persist_if_large("s1", "read_file", second)

        files = sorted((tmp_path / "s1" / "tool-results").glob("*.txt"))
        assert len(files) == 2
        assert {f.read_text(encoding="utf-8")[0] for f in files} == {"a", "b"}

    def test_long_tool_name_is_capped_for_filesystem(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        content = "x" * (PERSIST_THRESHOLD + 1)

        result = persist_if_large("s1", "tool_" + "x" * 300, content)

        assert "Result too large" in result
        files = list((tmp_path / "s1" / "tool-results").glob("*.txt"))
        assert len(files) == 1
        assert len(files[0].name.encode("utf-8")) <= 255
        assert files[0].read_text(encoding="utf-8") == content

    def test_preview_limited(self):
        lines = [f"line {i}" for i in range(500)]
        content = "\n".join(lines)
        # 确保超过阈值
        while len(content.encode("utf-8")) <= PERSIST_THRESHOLD:
            content += "\n" + "x" * 1000
        result = persist_if_large("s1", "tool", content)
        assert "200 lines" in result


# ═══════════════════════════════════════════════════════════
# 11.2 apply_result_budget
# ═══════════════════════════════════════════════════════════

class TestApplyResultBudget:
    def test_large_result_replaced(self):
        big = "x" * (MAX_RESULT_SIZE_CHARS + 1)
        messages = [
            {"role": "tool", "tool_call_id": "tc1", "content": big},
        ]
        changed = apply_result_budget(messages, "s1")
        assert changed is True
        assert "persisted" in messages[0]["content"].lower()

    def test_small_result_unchanged(self):
        messages = [
            {"role": "tool", "tool_call_id": "tc2", "content": "small"},
        ]
        changed = apply_result_budget(messages, "s1")
        assert changed is False
        assert messages[0]["content"] == "small"

    def test_idempotent(self):
        big = "x" * (MAX_RESULT_SIZE_CHARS + 1)
        messages = [
            {"role": "tool", "tool_call_id": "tc3", "content": big},
        ]
        apply_result_budget(messages, "s1")
        first_content = messages[0]["content"]
        # 第二次不应重复处理
        changed = apply_result_budget(messages, "s1")
        assert changed is False

    def test_tracking_is_scoped_by_session_id(self):
        big = "x" * (MAX_RESULT_SIZE_CHARS + 1)
        first = [{"role": "tool", "tool_call_id": "tc_same", "content": big}]
        second = [{"role": "tool", "tool_call_id": "tc_same", "content": big}]

        assert apply_result_budget(first, "s1") is True
        assert apply_result_budget(second, "s2") is True

    def test_no_session_id(self):
        messages = [{"role": "tool", "tool_call_id": "tc4", "content": "x" * 100000}]
        assert apply_result_budget(messages, "") is False

    def test_skips_non_string_tool_call_id(self):
        messages = [
            {
                "role": "tool",
                "tool_call_id": 123,
                "content": "x" * (MAX_RESULT_SIZE_CHARS + 1),
            },
        ]

        changed = apply_result_budget(messages, "s_bad")

        assert changed is False

    def test_skips_non_object_messages(self):
        messages = ["not-a-message"]

        changed = apply_result_budget(messages, "s_bad")

        assert changed is False


# ═══════════════════════════════════════════════════════════
# 11.3 load_persisted_result
# ═══════════════════════════════════════════════════════════

class TestLoadPersistedResult:
    def test_exists(self):
        big = "x" * (MAX_RESULT_SIZE_CHARS + 1)
        persist_large_result("s_load", "tc_load", big)
        loaded = load_persisted_result("s_load", "tc_load")
        assert loaded == big

    def test_persist_large_result_rejects_empty_tool_call_id(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        big = "x" * (MAX_RESULT_SIZE_CHARS + 1)

        with pytest.raises(ValueError, match="Invalid tool_call_id"):
            persist_large_result("s_load", "", big)

        assert not (tmp_path / "s_load" / "tool-results" / ".txt").exists()

    def test_persist_large_result_rejects_whitespace_tool_call_id(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        big = "x" * (MAX_RESULT_SIZE_CHARS + 1)

        with pytest.raises(ValueError, match="Invalid tool_call_id"):
            persist_large_result("s_load", "   ", big)

        assert not (tmp_path / "s_load" / "tool-results" / "   .txt").exists()

    def test_not_exists(self):
        assert load_persisted_result("no_session", "no_call") is None

    def test_long_tool_call_ids_do_not_collide_after_capping(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGECC_SESSION_DIR", str(tmp_path))
        big_a = "a" * (MAX_RESULT_SIZE_CHARS + 1)
        big_b = "b" * (MAX_RESULT_SIZE_CHARS + 1)
        first_id = "call_" + "x" * 300 + "a"
        second_id = "call_" + "x" * 300 + "b"

        persist_large_result("s_load", first_id, big_a)
        persist_large_result("s_load", second_id, big_b)

        assert load_persisted_result("s_load", first_id) == big_a
        assert load_persisted_result("s_load", second_id) == big_b


# ═══════════════════════════════════════════════════════════
# 11.4 reset_persisted_tracking
# ═══════════════════════════════════════════════════════════

class TestResetTracking:
    def test_reset_allows_re_persist(self):
        big = "x" * (MAX_RESULT_SIZE_CHARS + 1)
        messages = [
            {"role": "tool", "tool_call_id": "tc_reset", "content": big},
        ]
        apply_result_budget(messages, "s_reset")
        assert "persisted" in messages[0]["content"].lower()

        # 重新设置内容
        messages[0] = {"role": "tool", "tool_call_id": "tc_reset", "content": big}
        # 第二次不应替换（已跟踪）
        changed = apply_result_budget(messages, "s_reset")
        assert changed is False

        # 清除跟踪后应重新触发
        reset_persisted_tracking()
        changed = apply_result_budget(messages, "s_reset")
        assert changed is True
