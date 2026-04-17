"""Search-and-replace file editor with diff output.

The editing model is deliberately constrained:
  * The search string must appear exactly once in the file.
  * If it appears zero times → mismatch error.
  * If it appears more than once → ambiguity error.

This uniqueness constraint prevents the model from accidentally
modifying the wrong location — a critical safety property.
"""

from __future__ import annotations

import difflib
import os

from ..toolkit import instrument


def _unified_diff(before: str, after: str, path: str) -> str:
    a_lines = before.splitlines(keepends=True)
    b_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(a_lines, b_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    return "".join(diff)


@instrument(
    name="edit_file",
    description=(
        "Apply a search-and-replace edit to a file. The `old_text` must match "
        "exactly one location in the file (including whitespace). Returns a "
        "unified diff of the change."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit"},
            "old_text": {"type": "string", "description": "Exact text to find (must be unique)"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_text", "new_text"],
    },
    risk_level="write",
)
def edit_file(path: str, old_text: str, new_text: str) -> str:
    path = os.path.expanduser(path)

    if not os.path.isfile(path):
        return f"NOT FOUND: {path}"

    try:
        original = open(path, "r", encoding="utf-8").read()
    except UnicodeDecodeError:
        return f"BINARY FILE: {path}"

    occurrences = original.count(old_text)
    if occurrences == 0:
        # try a whitespace-relaxed match as a fallback hint
        stripped_old = old_text.strip()
        if stripped_old and stripped_old in original:
            return (
                f"EXACT MATCH FAILED in {path}. "
                "A whitespace-relaxed match exists — check indentation."
            )
        return f"NO MATCH for the given text in {path}."

    if occurrences > 1:
        return (
            f"AMBIGUOUS — '{old_text[:60]}...' appears {occurrences} times in {path}. "
            "Provide more surrounding context to make the match unique."
        )

    modified = original.replace(old_text, new_text, 1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(modified)

    diff = _unified_diff(original, modified, path)
    return diff if diff else "(no visible diff — content unchanged)"
