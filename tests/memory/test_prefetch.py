"""异步预取测试 — forgeagent.memory.prefetch"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forgeagent.memory.prefetch import (
    is_query_substantial,
    start_memory_prefetch,
    MemoryPrefetch,
)
from forgeagent.memory.recall import MAX_SESSION_MEMORY_BYTES


# ═══════════════════════════════════════════════════════════════
# 1. is_query_substantial
# ═══════════════════════════════════════════════════════════════

class TestIsQuerySubstantial:
    def test_cjk_substantial(self):
        assert is_query_substantial("你好世界") is True

    def test_single_char_not_substantial(self):
        assert is_query_substantial("a") is False

    def test_multi_word_substantial(self):
        assert is_query_substantial("hello world") is True

    def test_empty_not_substantial(self):
        assert is_query_substantial("") is False

    def test_whitespace_only(self):
        assert is_query_substantial("   ") is False

    def test_non_string_not_substantial(self):
        assert is_query_substantial(123) is False

    def test_single_cjk_not_substantial(self):
        assert is_query_substantial("你") is False


# ═══════════════════════════════════════════════════════════════
# 2. start_memory_prefetch — 门控
# ═══════════════════════════════════════════════════════════════

class TestStartMemoryPrefetch:
    def test_gate1_insubstantial_query(self, tmp_memory_dir):
        result = start_memory_prefetch("a", "/ws", MagicMock(), set(), 0)
        assert result is None

    def test_gate2_budget_exceeded(self, tmp_memory_dir):
        result = start_memory_prefetch(
            "hello world", "/ws", MagicMock(), set(),
            session_memory_bytes=MAX_SESSION_MEMORY_BYTES,
        )
        assert result is None

    def test_gate2_non_integer_budget_skips_prefetch(self, tmp_memory_dir):
        result = start_memory_prefetch(
            "hello world", "/ws", MagicMock(), set(),
            session_memory_bytes="full",
        )

        assert result is None

    def test_gate2_boolean_budget_skips_prefetch(self, monkeypatch):
        def fail_get_memory_dir(workspace):
            raise AssertionError("get_memory_dir should not be called")

        monkeypatch.setattr(
            "forgeagent.memory.prefetch.get_memory_dir",
            fail_get_memory_dir,
        )

        result = start_memory_prefetch(
            "hello world", "/ws", MagicMock(), set(),
            session_memory_bytes=True,
        )

        assert result is None

    def test_invalid_workspace_skips_prefetch(self, monkeypatch):
        def fail_get_memory_dir(workspace):
            raise AssertionError("get_memory_dir should not be called")

        monkeypatch.setattr(
            "forgeagent.memory.prefetch.get_memory_dir",
            fail_get_memory_dir,
        )

        result = start_memory_prefetch(
            "hello world", 123, MagicMock(), set(), 0,
        )

        assert result is None

    def test_gate3_no_memory_files(self, tmp_memory_dir):
        # tmp_memory_dir 存在但没有 .md 文件
        result = start_memory_prefetch(
            "hello world", "/ws", MagicMock(), set(), 0,
        )
        assert result is None

    def test_all_gates_pass(self, tmp_memory_dir):
        # 创建一个记忆文件以通过门控 3
        text = "---\nname: test\ntype: user\n---\nbody"
        (tmp_memory_dir / "user_test.md").write_text(text)

        provider = MagicMock()
        provider.side_query.return_value = '{"selected_memories": []}'

        result = start_memory_prefetch(
            "hello world", "/ws", provider, set(), 0,
        )
        assert result is not None
        assert isinstance(result, MemoryPrefetch)
        # 等待完成
        result.future.result(timeout=5)
        assert result.settled is True

    def test_handle_dataclass(self):
        from concurrent.futures import Future
        f = Future()
        f.set_result([])
        handle = MemoryPrefetch(future=f)
        assert handle.settled is False
        assert handle.consumed is False
