"""Message helpers shared by compaction tiers."""

from __future__ import annotations


def iter_tool_calls(message: dict):
    """Yield well-formed tool call dicts from an assistant message."""
    if not isinstance(message, dict):
        return
    tool_calls = message.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        return
    for tc in tool_calls:
        if isinstance(tc, dict):
            yield tc


def tool_function(tc: dict) -> dict:
    fn = tc.get("function", {})
    return fn if isinstance(fn, dict) else {}


def string_id(value: object) -> str:
    return value if isinstance(value, str) and value else ""


def safe_split_point(messages: list[dict], desired: int) -> int:
    """Adjust split point to avoid cutting between tool use and result."""
    idx = min(desired, len(messages))
    while idx > 1:
        msg = messages[idx - 1] if idx <= len(messages) else None
        if msg is None:
            break
        if not isinstance(msg, dict):
            break
        if msg.get("role") == "tool":
            idx -= 1
            continue
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            idx -= 1
            continue
        break
    return max(idx, 1)
