"""Token estimation helpers for context compaction."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough estimate for mixed content: about four chars per token."""
    return max(1, len(text) // 4)


def msg_tokens(message: dict) -> int:
    if not isinstance(message, dict):
        return 0
    total = 0
    if message.get("content"):
        total += estimate_tokens(str(message["content"]))
    if message.get("tool_calls"):
        total += estimate_tokens(str(message["tool_calls"]))
    return total


def conversation_tokens(messages: list[dict]) -> int:
    return sum(msg_tokens(message) for message in messages)
