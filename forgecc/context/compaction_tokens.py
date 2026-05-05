"""Token estimation helpers for context compaction."""

from __future__ import annotations

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _encoder():
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _fallback_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_tokens(text: str) -> int:
    """Count tokens with tiktoken, falling back to the old rough estimate."""
    encoder = _encoder()
    if encoder is None:
        return _fallback_estimate(text)
    return max(1, len(encoder.encode(text)))


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
