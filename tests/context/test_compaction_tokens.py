from __future__ import annotations

from forgeagent.context.compaction_tokens import (
    conversation_tokens,
    estimate_tokens,
    msg_tokens,
)


def test_estimate_tokens_uses_tiktoken_with_minimum_one():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 40) == 5
    assert estimate_tokens("你好世界abcd") == 6


def test_estimate_tokens_falls_back_to_rough_count(monkeypatch):
    import forgeagent.context.compaction_tokens as tokens

    monkeypatch.setattr(tokens, "_encoder", lambda: None)
    assert tokens.estimate_tokens("a" * 40) == 10


def test_msg_tokens_counts_content_and_tool_calls_and_skips_bad_messages():
    assert msg_tokens("not-a-message") == 0
    assert msg_tokens({"role": "user"}) == 0
    assert msg_tokens({"role": "user", "content": "a" * 40}) == 5
    assert msg_tokens({
        "role": "assistant",
        "content": "abcd",
        "tool_calls": [{"id": "c1", "function": {"name": "read_file"}}],
    }) > 1


def test_conversation_tokens_sums_message_tokens():
    messages = [
        {"role": "user", "content": "a" * 40},
        {"role": "user", "content": "b" * 80},
        "not-a-message",
    ]

    assert conversation_tokens(messages) == 25
