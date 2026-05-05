"""语义记忆召回 — 通过 sideQuery 由模型辅助选择。

不使用关键词匹配，而是将精简清单（文件名 + 描述）发送给模型，
由其挑选最相关的记忆。对齐 Claude Code 的 ``selectRelevantMemories`` 方案。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..frontmatter import parse_frontmatter
from .store import get_memory_dir, VALID_TYPES

import logging
log = logging.getLogger(__name__)

# ── 常量 ───────────────────────────────────────────────

MAX_MEMORY_FILES = 200
MAX_MEMORY_BYTES_PER_FILE = 4096
MAX_SESSION_MEMORY_BYTES = 60 * 1024  # 60 KB cumulative per session
_MEMORY_FILE_TRUNCATION_MARKER = "\n\n[... truncated, memory file too large ...]"


# ── 数据类 ────────────────────────────────────────────

@dataclass
class MemoryHeader:
    """单个记忆文件的轻量元数据（仅 frontmatter）。"""
    filename: str
    filepath: str
    mtime: float
    description: str | None
    type: str | None


@dataclass
class RelevantMemory:
    """经模型选择的记忆，已加载完整内容。"""
    path: str
    content: str
    mtime: float
    header: str   # 包含新鲜度信息的可读头部


# ── 新鲜度工具 ───────────────────────────────────────

def memory_age(mtime: float) -> str:
    """可读时间距离: 'today'、'yesterday' 或 'N days ago'。"""
    days = max(0, int((time.time() - mtime) / 86_400))
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def freshness_warning(mtime: float) -> str:
    """超过 1 天的记忆的警告文本。若仍新鲜则返回空字符串。"""
    days = max(0, int((time.time() - mtime) / 86_400))
    if days <= 1:
        return ""
    return (
        f"This memory is {days} days old.  Memories are point-in-time "
        "observations, not live state — claims about code behavior may "
        "be outdated.  Verify against current code before asserting as fact."
    )


# ── 头部扫描 ────────────────────────────────────────

def scan_memory_headers(workspace: str) -> list[MemoryHeader]:
    """快速扫描: 仅读取每个文件的 frontmatter（前 30 行）。

    返回最多 ``MAX_MEMORY_FILES`` 条记录，按 mtime 降序排列。
    """
    if not isinstance(workspace, str) or not workspace.strip():
        return []
    mem_dir = get_memory_dir(workspace)
    headers: list[MemoryHeader] = []

    for f in mem_dir.iterdir():
        if not f.suffix == ".md" or f.name == "MEMORY.md":
            continue
        try:
            raw = f.read_text(encoding="utf-8")
            first30 = "\n".join(raw.split("\n")[:30])
            meta, _ = parse_frontmatter(first30)
            headers.append(MemoryHeader(
                filename=f.name,
                filepath=str(f),
                mtime=f.stat().st_mtime,
                description=meta.get("description"),
                type=meta["type"] if meta.get("type") in VALID_TYPES else None,
            ))
        except Exception:
            continue

    headers.sort(key=lambda h: h.mtime, reverse=True)
    return headers[:MAX_MEMORY_FILES]


def format_memory_manifest(headers: list[MemoryHeader]) -> str:
    """为语义选择器生成每行一条记忆的清单。"""
    lines = []
    for h in headers:
        tag = f"[{h.type}] " if h.type else ""
        ts = datetime.fromtimestamp(h.mtime).isoformat()
        if h.description:
            lines.append(f"- {tag}{h.filename} ({ts}): {h.description}")
        else:
            lines.append(f"- {tag}{h.filename} ({ts})")
    return "\n".join(lines)


def _truncate_utf8_bytes(text: str, max_bytes: int, marker: str) -> str:
    marker_bytes = marker.encode("utf-8")
    budget = max(max_bytes - len(marker_bytes), 0)
    clipped = text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return clipped + marker


def _first_json_object(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# ── 语义选择 ──────────────────────────────────────

_SELECT_PROMPT = (
    "You are selecting memories that will be useful to an AI coding "
    "assistant as it processes a user's query.  You will be given the "
    "user's query and a list of available memory files with their "
    "filenames and descriptions.\n\n"
    "Return a JSON object with a \"selected_memories\" array of filenames "
    "for the memories that will clearly be useful (up to 5).  Only "
    "include memories that you are certain will be helpful based on "
    "their name and description.\n"
    "- If you are unsure if a memory will be useful, do not include it.\n"
    "- If no memories would clearly be useful, return an empty array."
)


def select_relevant_memories(
    query: str,
    workspace: str,
    provider,          # Provider (avoid circular import by duck-typing)
    already_surfaced: set[str],
) -> list[RelevantMemory]:
    """使用模型为 *query* 挑选最相关的记忆。

    发送仅包含清单（而非完整内容）的轻量 sideQuery，
    然后读取并返回选中的文件（最多 5 个，每个 4 KB）。
    """
    headers = scan_memory_headers(workspace)
    if not headers:
        log.debug("记忆召回: 无记忆文件")
        return []

    # 过滤已展示过的记忆
    candidates = [h for h in headers if h.filepath not in already_surfaced]
    if not candidates:
        return []

    manifest = format_memory_manifest(candidates)

    try:
        text = provider.side_query(
            system=_SELECT_PROMPT,
            user_message=f"Query: {query}\n\nAvailable memories:\n{manifest}",
        )

        # 从响应中提取 JSON（模型可能用 Markdown 代码块包裹或追加解释）
        parsed = _first_json_object(text)
        if parsed is None:
            return []

        selected_raw = parsed.get("selected_memories", [])
        if isinstance(selected_raw, str):
            selected_filenames = [selected_raw]
        elif isinstance(selected_raw, list):
            selected_filenames = [name for name in selected_raw if isinstance(name, str)]
        else:
            selected_filenames = []

        fname_set = set(selected_filenames)
        selected = [h for h in candidates if h.filename in fname_set]

        results: list[RelevantMemory] = []
        for h in selected[:5]:
            content = Path(h.filepath).read_text(encoding="utf-8")
            # 单文件字节截断
            if len(content.encode("utf-8")) > MAX_MEMORY_BYTES_PER_FILE:
                content = _truncate_utf8_bytes(
                    content,
                    MAX_MEMORY_BYTES_PER_FILE,
                    _MEMORY_FILE_TRUNCATION_MARKER,
                )

            warning = freshness_warning(h.mtime)
            if warning:
                header_text = f"{warning}\n\nMemory: {h.filepath}:"
            else:
                header_text = f"Memory (saved {memory_age(h.mtime)}): {h.filepath}:"

            results.append(RelevantMemory(
                path=h.filepath,
                content=content,
                mtime=h.mtime,
                header=header_text,
            ))
        log.info("记忆召回完成: 选中 %d 条记忆", len(results))
        return results

    except Exception:
        # 记忆召回不应阻塞主循环
        log.debug("记忆召回异常，静默跳过")
        return []


def format_memories_for_injection(memories: list[RelevantMemory]) -> str:
    """将召回的记忆包装为用户消息注入格式。"""
    if not isinstance(memories, list):
        return ""
    parts: list[str] = []
    for memory in memories:
        content = getattr(memory, "content", None)
        if not isinstance(content, str):
            continue
        header = getattr(memory, "header", None)
        if not isinstance(header, str):
            path = getattr(memory, "path", "(unknown)")
            header = f"Memory: {path}:"
        parts.append(
            f"<system-reminder>\n{header}\n\n{content}\n</system-reminder>"
        )
    return "\n\n".join(parts)
