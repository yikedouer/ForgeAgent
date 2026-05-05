from __future__ import annotations

from forgecc.context.compaction_tokens import (
    conversation_tokens,
    estimate_tokens,
    msg_tokens,
)


def test_estimate_tokens_uses_four_chars_per_token_with_minimum_one():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 40) == 10


def test_msg_tokens_counts_content_and_tool_calls_and_skips_bad_messages():
    assert msg_tokens("not-a-message") == 0
    assert msg_tokens({"role": "user"}) == 0
    assert msg_tokens({"role": "user", "content": "a" * 40}) == 10
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

    assert conversation_tokens(messages) == 30
