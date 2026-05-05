"""Autocompact tier for the context compaction pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .compaction_messages import iter_tool_calls, safe_split_point, tool_function

if TYPE_CHECKING:
    from ..core.providers import Provider


MAX_CONSECUTIVE_FAILURES = 3

_AUTOCOMPACT_PROMPT = """\
Summarize this conversation for context continuity.

First, analyze internally:
- What is the user's primary request and intent?
- What files were modified/created and key code changes?
- What errors occurred and how were they fixed?
- What tasks remain pending?

Then produce a structured summary with these sections:
1. Primary Request: user's explicit goal
2. Key Decisions: important technical choices made
3. Files Modified: paths and what changed
4. Current State: what was just completed
5. Pending Tasks: what remains to be done
6. User Preferences: any expressed preferences or corrections

IMPORTANT: Preserve exact file paths, function names, and error messages.\
"""


def _autocompact(
    messages: list[dict],
    provider: "Provider",
    keep_recent: int = 8,
    failure_count: list[int] | None = None,
) -> bool:
    """Generate a structured summary with the LLM and replace old messages."""
    if failure_count and failure_count[0] >= MAX_CONSECUTIVE_FAILURES:
        return False

    if len(messages) <= keep_recent + 2:
        return False

    split = safe_split_point(messages, len(messages) - keep_recent)
    old_slice = messages[1:split]
    if not old_slice:
        return False

    segment_text = "\n".join(
        f"[{m.get('role', '?')}] {str(m.get('content', ''))[:400]}"
        for m in old_slice
        if isinstance(m, dict)
    )

    summary_input = [
        {"role": "user", "content": _AUTOCOMPACT_PROMPT},
        {"role": "user", "content": segment_text},
    ]

    try:
        result = provider.generate(summary_input)
        summary_text = result.text or "(no summary produced)"
    except Exception:
        if failure_count is not None:
            failure_count[0] += 1
        return False

    if failure_count is not None:
        failure_count[0] = 0

    summary_msg = {
        "role": "user",
        "content": f"[AUTOCOMPACT SUMMARY]\n{summary_text}",
    }
    messages[1:split] = [summary_msg]

    file_paths = _extract_recent_file_paths(messages)
    if file_paths:
        recovery_msg = {
            "role": "user",
            "content": (
                "[POST-COMPACT CONTEXT RECOVERY]\n"
                "Recently modified files:\n"
                + "\n".join(f"  - {p}" for p in file_paths[:10])
            ),
        }
        messages.insert(2, recovery_msg)

    return True


def _extract_recent_file_paths(messages: list[dict]) -> list[str]:
    """Scan recent tool calls for file paths used after compaction."""
    paths: list[str] = []
    seen: set[str] = set()
    for m in reversed(messages[-20:]):
        for tc in iter_tool_calls(m):
            args = tool_function(tc).get("arguments", "")
            if isinstance(args, str):
                for token in args.split('"'):
                    if "/" in token and len(token) < 200 and token not in seen:
                        paths.append(token)
                        seen.add(token)
    return paths
