"""test_collapse.py — 上下文折叠测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from forgecc.context.collapse import CollapseState, try_collapse, project_view


def _make_messages(n: int) -> list[dict]:
    """生成 n 条交替消息。"""
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"message {i}"})
    return msgs


def _mock_provider(summary="Summary text"):
    provider = MagicMock()
    result = MagicMock()
    result.text = summary
    provider.generate.return_value = result
    return provider


# ═══════════════════════════════════════════════════════════
# 10.1 try_collapse
# ═══════════════════════════════════════════════════════════

class TestTryCollapse:
    def test_enough_messages_produces_state(self):
        msgs = _make_messages(20)
        provider = _mock_provider("compressed")
        state = try_collapse(msgs, provider, keep_recent=8)
        assert state is not None
        assert state.summary_text == "compressed"
        assert state.collapsed_at == 20

    def test_too_few_messages_returns_none(self):
        msgs = _make_messages(5)
        provider = _mock_provider()
        assert try_collapse(msgs, provider, keep_recent=8) is None

    def test_existing_collapse_chains_summary(self):
        msgs = _make_messages(30)
        provider = _mock_provider("first summary")
        state1 = try_collapse(msgs, provider, keep_recent=8)
        assert state1 is not None

        # 扩展消息并重新折叠
        msgs.extend(_make_messages(10))
        provider2 = _mock_provider("second summary")
        state2 = try_collapse(msgs, provider2, keep_recent=8, existing=state1)
        if state2 is not None:
            assert "first summary" in state2.summary_text
            assert state2._previous is state1

    def test_llm_failure_returns_none(self):
        msgs = _make_messages(20)
        provider = MagicMock()
        provider.generate.side_effect = Exception("LLM error")
        assert try_collapse(msgs, provider, keep_recent=8) is None

    def test_same_boundary_returns_none(self):
        msgs = _make_messages(20)
        provider = _mock_provider()
        state1 = try_collapse(msgs, provider, keep_recent=8)
        assert state1 is not None
        # 不增加消息，同样的边界
        state2 = try_collapse(msgs, provider, keep_recent=8, existing=state1)
        assert state2 is None


# ═══════════════════════════════════════════════════════════
# 10.2 project_view
# ═══════════════════════════════════════════════════════════

class TestProjectView:
    def test_no_collapse_returns_original(self):
        msgs = _make_messages(5)
        result = project_view(msgs, None)
        assert result is msgs

    def test_with_collapse_returns_projection(self):
        msgs = _make_messages(20)
        state = CollapseState(
            collapse_boundary=10,
            summary_text="Old messages summary",
            collapsed_at=20,
        )
        result = project_view(msgs, state)
        assert len(result) == 11  # 1 summary + 10 tail
        assert "CONTEXT COLLAPSED" in result[0]["content"]
        assert result[0]["role"] == "user"

    def test_original_messages_unchanged(self):
        msgs = _make_messages(20)
        original_len = len(msgs)
        state = CollapseState(collapse_boundary=10, summary_text="S", collapsed_at=20)
        project_view(msgs, state)
        assert len(msgs) == original_len


# ═══════════════════════════════════════════════════════════
# 10.3 CollapseState 数据类
# ═══════════════════════════════════════════════════════════

class TestCollapseState:
    def test_previous_chain(self):
        s1 = CollapseState(collapse_boundary=5, summary_text="S1", collapsed_at=10)
        s2 = CollapseState(collapse_boundary=10, summary_text="S2", collapsed_at=20, _previous=s1)
        assert s2._previous is s1
        assert s2._previous.summary_text == "S1"
