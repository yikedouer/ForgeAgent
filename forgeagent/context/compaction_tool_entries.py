"""Tool-call entry helpers for context compaction."""

from __future__ import annotations

import json
from typing import Callable


SNIPPABLE_TOOLS = {"read_file", "shell", "grep_search", "glob_search"}
SNIP_PLACEHOLDER = "[Content snipped - re-read if needed]"


def _iter_tool_calls(message: dict):
    if not isinstance(message, dict):
        return
    tool_calls = message.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        return
    for tc in tool_calls:
        if isinstance(tc, dict):
            yield tc


def _tool_function(tc: dict) -> dict:
    fn = tc.get("function", {})
    return fn if isinstance(fn, dict) else {}


def _string_id(value: object) -> str:
    return value if isinstance(value, str) and value else ""


def parse_tool_args_map(messages: list[dict]) -> dict[str, dict]:
    """Build tool_call_id -> parsed JSON arguments for object-shaped args."""
    tool_args_map: dict[str, dict] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "assistant":
            continue
        for tc in _iter_tool_calls(message):
            call_id = _string_id(tc.get("id"))
            raw_args = _tool_function(tc).get("arguments", "")
            if not call_id or not isinstance(raw_args, str):
                continue
            try:
                parsed_args = json.loads(raw_args)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed_args, dict):
                tool_args_map[call_id] = parsed_args
    return tool_args_map


def collect_snippable_tool_entries(
    messages: list[dict],
    *,
    build_tool_name_map: Callable[[list[dict]], dict[str, str]] | None = None,
) -> list[dict]:
    """Collect tool result entries that can be replaced by a placeholder."""
    if build_tool_name_map is None:
        from .compaction import _build_tool_name_map
        build_tool_name_map = _build_tool_name_map

    tool_name_map = build_tool_name_map(messages)
    tool_args_map = parse_tool_args_map(messages)

    tool_entries: list[dict] = []
    for idx, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "tool":
            continue
        call_id = _string_id(message.get("tool_call_id"))
        name = tool_name_map.get(call_id, "")
        if name not in SNIPPABLE_TOOLS:
            continue
        content = str(message.get("content", ""))
        if content == SNIP_PLACEHOLDER:
            continue
        args = tool_args_map.get(call_id, {})
        file_path = args.get("path") or args.get("file_path")
        tool_entries.append({"idx": idx, "name": name, "file_path": file_path})
    return tool_entries
