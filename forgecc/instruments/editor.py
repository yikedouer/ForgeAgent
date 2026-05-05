"""搜索替换文件编辑器，输出 diff。

编辑模型刻意受限：
  * 搜索字符串必须在文件中恰好出现一次。
  * 出现零次 → 不匹配错误。
  * 出现多次 → 歧义错误。

这种唯一性约束防止模型意外修改错误位置——
这是一个关键的安全属性。
"""

from __future__ import annotations

import difflib
import logging
import os

from ..toolkit import instrument
from .paths import active_workspace_boundary_error, resolve_workspace_path

log = logging.getLogger(__name__)


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
    if not isinstance(path, str) or not path.strip():
        return "INVALID PATH: path must be non-empty."
    path = path.strip()
    path = resolve_workspace_path(path)
    boundary_err = active_workspace_boundary_error(path)
    if boundary_err:
        return boundary_err
    if not isinstance(old_text, str):
        return "INVALID OLD_TEXT: old_text must be a string."
    if not isinstance(new_text, str):
        return "INVALID NEW_TEXT: new_text must be a string."
    log.debug("edit_file: path=%s  old=%d字符  new=%d字符", path, len(old_text), len(new_text))

    if old_text == "":
        return "EMPTY old_text — provide the exact text to replace."

    if not os.path.isfile(path):
        return f"NOT FOUND: {path}"

    try:
        original = open(path, "r", encoding="utf-8").read()
    except UnicodeDecodeError:
        return f"BINARY FILE: {path}"

    occurrences = original.count(old_text)
    if occurrences == 0:
        # 尝试空白宽松匹配作为提示
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
