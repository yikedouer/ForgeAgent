"""工具结果持久化——将大型工具输出保存到磁盘。

两层持久化机制：

  1. **即时持久化** (``persist_if_large``)：在每次工具执行后、
     结果进入对话记录前调用。阈值 30 KB，预览 200 行。
     确保大型输出不会撤大上下文窗口。

  2. **压缩时持久化** (``apply_result_budget``)：在
     ``maybe_compact()`` 的 Tier 1 Snip 阶段调用。
     使用旧版 50 K 字符阈值捕获漏网项目（如旧会话）。

存储位置：``~/.forgeagent/sessions/{session_id}/tool-results/``
"""

from __future__ import annotations

import hashlib
import time as _time
from pathlib import Path

from .checkpoint import session_dir, validate_session_id

# ── 常量 ──────────────────────────────────────────────────────

PERSIST_THRESHOLD = 30 * 1024     # 超过 30 KB 立即持久化
PREVIEW_LINES = 200               # 即时持久化的行级预览数

MAX_RESULT_SIZE_CHARS = 50_000    # 旧版压缩时阈值
PREVIEW_SIZE_CHARS = 2_000        # 旧版字符级预览数
MAX_FILENAME_PART_BYTES = 120


# ── 存储目录 ────────────────────────────────────────────────

def _storage_dir(session_id: str) -> Path:
    """返回（并创建）会话的工具结果存储目录。"""
    validate_session_id(session_id)
    d = session_dir() / session_id / "tool-results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _result_path(session_id: str, tool_call_id: str) -> Path:
    """单个持久化工具结果的文件路径。"""
    _validate_filename_part(tool_call_id, "tool_call_id")
    safe_id = _safe_filename_part(tool_call_id)
    return _storage_dir(session_id) / f"{safe_id}.txt"


def _validate_filename_part(value: str, label: str) -> None:
    """拒绝无法形成有意义文件名片段的动态值。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {label}: {value!r}")


def _safe_filename_part(value: str) -> str:
    """将动态片段压成单个文件名组件。"""
    safe = value.replace("/", "_").replace("\\", "_")
    if len(safe.encode("utf-8")) <= MAX_FILENAME_PART_BYTES:
        return safe
    suffix = "_" + hashlib.sha256(value.encode()).hexdigest()[:8]
    prefix_budget = MAX_FILENAME_PART_BYTES - len(suffix)
    prefix = safe.encode("utf-8")[:prefix_budget].decode(
        "utf-8", errors="ignore"
    )
    return prefix + suffix


def _unique_txt_path(directory: Path, stem: str) -> Path:
    """返回不会覆盖既有文件的 .txt 路径。"""
    path = directory / f"{stem}.txt"
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = directory / f"{stem}-{counter}.txt"
        if not candidate.exists():
            return candidate
        counter += 1


# ── 即时持久化（执行时调用）─────────────────────────────

def persist_if_large(session_id: str, tool_name: str, content: str) -> str:
    """超过 30 KB 的内容持久化到磁盘，返回 200 行预览。

    未超阈值则原样返回。
    由 ``Engine.run()`` 在工具执行后立即调用。
    """
    byte_size = len(content.encode("utf-8"))
    if byte_size <= PERSIST_THRESHOLD:
        return content

    _validate_filename_part(tool_name, "tool_name")
    safe_tool_name = _safe_filename_part(tool_name)
    path = _unique_txt_path(
        _storage_dir(session_id), f"{int(_time.time())}-{safe_tool_name}"
    )
    path.write_text(content, encoding="utf-8")

    lines = content.split("\n")
    preview = "\n".join(lines[:PREVIEW_LINES])
    size_kb = byte_size / 1024

    return (
        f"[Result too large ({size_kb:.1f} KB, {len(lines)} lines). "
        f"Full output saved to {path}. "
        f"Use read_file to see the full result.]\n\n"
        f"Preview (first {PREVIEW_LINES} lines):\n{preview}"
    )


# ── 旧版压缩时持久化 ────────────────────────────────────

def persist_large_result(
    session_id: str,
    tool_call_id: str,
    content: str,
) -> str | None:
    """内容超过旧版阈值时持久化到磁盘，返回替代预览字符串。
    未超阈值返回 None。

    幂等：文件已存在时跳过写入，但仍返回预览
    （消息内容应始终被替换）。
    """
    if len(content) <= MAX_RESULT_SIZE_CHARS:
        return None

    path = _result_path(session_id, tool_call_id)

    # 仅写入一次
    if not path.exists():
        path.write_text(content, encoding="utf-8")

    preview = content[:PREVIEW_SIZE_CHARS]
    size = len(content)
    return (
        f"[Output persisted ({size:,} chars). "
        f"Full result saved to: {path}]\n"
        f"Preview (first {PREVIEW_SIZE_CHARS:,} chars):\n{preview}"
    )


def load_persisted_result(
    session_id: str,
    tool_call_id: str,
) -> str | None:
    """从磁盘加载完整的持久化结果，不存在返回 None。"""
    path = _result_path(session_id, tool_call_id)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


# ── 批量预算应用 ──────────────────────────────────────────────

# 记录已替换的 (session_id, tool_call_id)，避免后续压缩轮次重复持久化
_persisted_ids: set[tuple[str, str]] = set()


def apply_result_budget(messages: list[dict], session_id: str) -> bool:
    """遍历 *messages* 原地修改；将超过阈值的工具结果持久化。
    有替换发生时返回 True。"""
    if not session_id:
        return False

    changed = False
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        if m.get("role") != "tool":
            continue
        call_id = m.get("tool_call_id", "")
        tracking_key = (session_id, call_id)
        if (
            not isinstance(call_id, str)
            or not call_id
            or tracking_key in _persisted_ids
        ):
            continue

        content = str(m.get("content", ""))
        replacement = persist_large_result(session_id, call_id, content)
        if replacement is not None:
            messages[i] = {**m, "content": replacement}
            _persisted_ids.add(tracking_key)
            changed = True

    return changed


def reset_persisted_tracking() -> None:
    """清除内存中的跟踪集合（在 /clear 时调用）。"""
    _persisted_ids.clear()
