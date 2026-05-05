"""Local compaction tiers that do not require LLM calls."""

from __future__ import annotations

import time

from .compaction_messages import (
    iter_tool_calls as _iter_tool_calls,
    safe_split_point as _safe_split_point,
    string_id as _string_id,
    tool_function as _tool_function,
)
from .compaction_tool_entries import (
    SNIP_PLACEHOLDER,
    collect_snippable_tool_entries,
)


KEEP_RECENT_RESULTS = 3
MICROCOMPACT_IDLE_S = 5 * 60


def _build_tool_name_map(messages: list[dict]) -> dict[str, str]:
    """Build a tool_call_id -> function name map from assistant messages."""
    mapping: dict[str, str] = {}
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") != "assistant":
            continue
        for tc in _iter_tool_calls(m):
            call_id = _string_id(tc.get("id"))
            fn_name = _tool_function(tc).get("name", "")
            if call_id and isinstance(fn_name, str) and fn_name:
                mapping[call_id] = fn_name
    return mapping


def _budget_tool_results(messages: list[dict], utilization: float) -> bool:
    """Apply utilization-based head/tail truncation to large tool results."""
    if utilization < 0.5:
        return False
    budget = 15_000 if utilization > 0.7 else 30_000
    changed = False
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") != "tool" or not isinstance(m.get("content"), str):
            continue
        content = m["content"]
        if len(content) > budget:
            keep = (budget - 80) // 2
            m["content"] = (
                content[:keep]
                + f"\n\n[... budgeted: {len(content) - keep * 2} chars truncated ...]\n\n"
                + content[-keep:]
            )
            changed = True
    return changed


def _snip(messages: list[dict], session_id: str, keep_recent: int = 6) -> bool:
    """Persist huge tool results, then summarize old tool outputs."""
    changed = False
    from .tool_storage import apply_result_budget
    changed |= apply_result_budget(messages, session_id)

    cutoff = len(messages) - keep_recent
    for i in range(max(cutoff, 0)):
        m = messages[i]
        if not isinstance(m, dict):
            continue
        if m.get("role") == "tool" and len(str(m.get("content", ""))) > 200:
            original = str(m["content"])
            lines = original.splitlines()
            if len(lines) > 3:
                digest = (
                    f"{lines[0]}  ... [{len(lines)} lines snipped] ...  {lines[-1]}"
                )
                messages[i] = {**m, "content": digest}
                changed = True
    return changed


def _snip_stale_results(
    messages: list[dict],
    utilization: float,
    *,
    build_tool_name_map=_build_tool_name_map,
) -> bool:
    """Replace stale tool results, deduplicating read_file by latest path."""
    if utilization < 0.6:
        return False

    tool_entries = collect_snippable_tool_entries(
        messages,
        build_tool_name_map=build_tool_name_map,
    )
    if len(tool_entries) <= KEEP_RECENT_RESULTS:
        return False

    to_snip: set[int] = set()
    seen_files: dict[str, list[int]] = {}
    for ei, entry in enumerate(tool_entries):
        if entry["name"] == "read_file" and entry["file_path"]:
            seen_files.setdefault(entry["file_path"], []).append(ei)
    for indices in seen_files.values():
        if len(indices) > 1:
            for j in indices[:-1]:
                to_snip.add(j)

    snip_before = len(tool_entries) - KEEP_RECENT_RESULTS
    for i in range(snip_before):
        to_snip.add(i)

    changed = False
    for idx in to_snip:
        msg_idx = tool_entries[idx]["idx"]
        if messages[msg_idx].get("content") != SNIP_PLACEHOLDER:
            messages[msg_idx] = {**messages[msg_idx], "content": SNIP_PLACEHOLDER}
            changed = True
    return changed


def _microcompact_idle(
    messages: list[dict],
    last_api_call_time: float | None,
) -> bool:
    """Clear all but recent tool results after prompt cache cools down."""
    if not last_api_call_time or (time.time() - last_api_call_time) < MICROCOMPACT_IDLE_S:
        return False

    tool_indices: list[int] = []
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            content = m["content"]
            if content not in (SNIP_PLACEHOLDER, "[Old result cleared]"):
                tool_indices.append(i)

    clear_count = len(tool_indices) - KEEP_RECENT_RESULTS
    if clear_count <= 0:
        return False

    changed = False
    for j in range(clear_count):
        idx = tool_indices[j]
        messages[idx] = {**messages[idx], "content": "[Old result cleared]"}
        changed = True
    return changed


def _prune(messages: list[dict], keep_recent: int = 4) -> bool:
    """Last resort: drop everything except system plus recent tail."""
    if len(messages) <= keep_recent + 1:
        return False

    split = _safe_split_point(messages, len(messages) - keep_recent)
    tail = messages[split:]
    header = {
        "role": "user",
        "content": "[CONTEXT PRUNED — earlier messages removed to fit budget]",
    }

    if (
        messages
        and isinstance(messages[0], dict)
        and messages[0].get("role") == "system"
    ):
        messages[:] = [messages[0], header] + tail
    else:
        messages[:] = [header] + tail
    return True
