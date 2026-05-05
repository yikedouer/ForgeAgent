"""记忆工具——Agent 可调用的持久化记忆 CRUD。

三个工具：
  * memory_save   — 创建或更新记忆
  * memory_list   — 列出所有记忆（只读）
  * memory_delete — 按文件名删除记忆
"""

from __future__ import annotations

import logging

from ..toolkit import instrument
from ..memory.store import (
    save_memory,
    list_memories,
    delete_memory,
    VALID_TYPES,
)

log = logging.getLogger(__name__)


def _get_workspace() -> str:
    """从活跃引擎解析工作区。"""
    from ..core.engine import _active_engine
    if _active_engine is None:
        raise RuntimeError("No active engine — cannot resolve workspace")
    return _active_engine.settings.workspace


# ── memory_save ─────────────────────────────────────────────

@instrument(
    name="memory_save",
    description=(
        "Save a persistent memory that will be available across sessions. "
        "Use this to remember user preferences, feedback, project decisions, "
        "or external references. Do NOT save code patterns, git history, "
        "or anything derivable from the codebase."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short name for the memory (e.g. 'user prefers Chinese')",
            },
            "description": {
                "type": "string",
                "description": (
                    "One-line description — this is the primary field used "
                    "for semantic recall, so be specific."
                ),
            },
            "memory_type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": (
                    "Category: user (identity/preferences), feedback (corrections), "
                    "project (decisions/deadlines), reference (external pointers)"
                ),
            },
            "content": {
                "type": "string",
                "description": "The memory content (Markdown supported).",
            },
        },
        "required": ["name", "description", "memory_type", "content"],
    },
    risk_level="write",
)
def memory_save(
    name: str,
    description: str,
    memory_type: str,
    content: str,
    ) -> str:
    if not isinstance(name, str) or not name.strip():
        return "INVALID NAME: name must be non-empty."
    if not isinstance(description, str) or not description.strip():
        return "INVALID DESCRIPTION: description must be non-empty."
    if not isinstance(content, str) or not content.strip():
        return "INVALID CONTENT: content must be non-empty."
    if not isinstance(memory_type, str):
        allowed = ", ".join(sorted(VALID_TYPES))
        return f"INVALID TYPE: memory_type must be one of: {allowed}."
    name = name.strip()
    description = description.strip()
    memory_type = memory_type.strip()
    if memory_type not in VALID_TYPES:
        allowed = ", ".join(sorted(VALID_TYPES))
        return f"INVALID TYPE: memory_type must be one of: {allowed}."
    workspace = _get_workspace()
    log.info("保存记忆: name=%s  type=%s", name, memory_type)
    filename = save_memory(workspace, name, description, memory_type, content)
    return f"Memory saved → {filename}"


# ── memory_list ─────────────────────────────────────────────

@instrument(
    name="memory_list",
    description="List all persistent memories for the current project.",
    parameters={
        "type": "object",
        "properties": {},
    },
    readonly=True,
    risk_level="read",
)
def memory_list() -> str:
    workspace = _get_workspace()
    entries = list_memories(workspace)
    if not entries:
        return "No memories saved yet."

    lines = [f"Found {len(entries)} memories:\n"]
    for e in entries:
        lines.append(f"  [{e.type}] {e.filename}")
        lines.append(f"    name: {e.name}")
        lines.append(f"    desc: {e.description}")
        lines.append("")
    return "\n".join(lines)


# ── memory_delete ───────────────────────────────────────────

@instrument(
    name="memory_delete",
    description="Delete a persistent memory by its filename.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "The memory filename to delete (e.g. 'feedback_use_chinese.md')",
            },
        },
        "required": ["filename"],
    },
    risk_level="write",
)
def memory_delete(filename: str) -> str:
    if not isinstance(filename, str) or not filename.strip():
        return "INVALID FILENAME: filename must be non-empty."
    filename = filename.strip()
    workspace = _get_workspace()
    log.info("删除记忆: %s", filename)
    ok = delete_memory(workspace, filename)
    if ok:
        return f"Deleted memory: {filename}"
    return f"Memory not found: {filename}"
