"""文件写入工具——创建或覆写文件。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..toolkit import instrument
from .paths import active_workspace_boundary_error, resolve_workspace_path

log = logging.getLogger(__name__)


@instrument(
    name="write_file",
    description=(
        "Write content to a file, creating parent directories as needed. "
        "Overwrites the file if it already exists."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Target file path"},
            "content": {"type": "string", "description": "Full content to write"},
        },
        "required": ["path", "content"],
    },
    risk_level="write",
)
def write_file(path: str, content: str) -> str:
    if not isinstance(path, str) or not path.strip():
        return "INVALID PATH: path must be non-empty."
    path = path.strip()
    path = resolve_workspace_path(path)
    boundary_err = active_workspace_boundary_error(path)
    if boundary_err:
        return boundary_err
    if not isinstance(content, str):
        return "INVALID CONTENT: content must be a string."
    log.debug("write_file: path=%s  content=%d字符", path, len(content))
    if os.path.isdir(path):
        return f"INVALID PATH: target is a directory: {path}"
    parent_dir = os.path.dirname(path) or "."
    if os.path.exists(parent_dir) and not os.path.isdir(parent_dir):
        return f"INVALID PATH: parent is not a directory: {parent_dir}"
    os.makedirs(parent_dir, exist_ok=True)

    existed = os.path.isfile(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)

    # 如果写入目标是记忆目录，自动更新索引
    _maybe_update_memory_index(path)

    line_count = 0 if content == "" else content.count("\n") + (0 if content.endswith("\n") else 1)
    verb = "Updated" if existed else "Created"
    return f"{verb} {path} ({line_count} lines)"


def _maybe_update_memory_index(path: str) -> None:
    """如果 *path* 在活跃引擎的记忆目录内，重建索引。"""
    try:
        from ..core.engine import _active_engine
        from ..memory.store import get_memory_dir, update_index

        if _active_engine is None:
            return
        filepath = Path(path).expanduser().resolve()
        mem_dir = get_memory_dir(_active_engine.settings.workspace).resolve()
        try:
            filepath.relative_to(mem_dir)
        except ValueError:
            return
        if filepath.suffix == ".md" and filepath.name != "MEMORY.md":
            update_index(_active_engine.settings.workspace)
    except Exception:
        pass
