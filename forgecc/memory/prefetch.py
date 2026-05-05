"""异步记忆预取 — 与首次 LLM 调用并行执行召回。

三个门控条件（对齐 Claude Code）:
  1. 查询必须有实质内容（CJK >= 2 字符或多词）。
  2. 会话记忆预算未超限（60 KB）。
  3. 记忆文件必须存在。

预取任务提交到线程池，Engine 可无阻塞轮询 ``handle.settled``。
"""

from __future__ import annotations

import re
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

from .recall import (
    RelevantMemory,
    MAX_SESSION_MEMORY_BYTES,
    select_relevant_memories,
)
from .store import get_memory_dir

import logging
log = logging.getLogger(__name__)

# 模块级单线程池（延迟初始化以避免启动开销）
_pool: ThreadPoolExecutor | None = None


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mem-prefetch")
    return _pool


# ── 查询门控 ──────────────────────────────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def is_query_substantial(query: str) -> bool:
    """判断 *query* 是否包含足够有意义的内容。

    满足以下任一条件即可:
    - 2+ 个 CJK 字符（中 / 日 / 韩），或
    - 多词输入（包含空白字符）。
    """
    if not isinstance(query, str):
        return False
    trimmed = query.strip()
    if not trimmed:
        return False
    cjk_matches = _CJK_RE.findall(trimmed)
    if len(cjk_matches) >= 2:
        return True
    if re.search(r"\s", trimmed):
        return True
    return False


# ── 预取句柄 ─────────────────────────────────────────

@dataclass
class MemoryPrefetch:
    """由 :func:`start_memory_prefetch` 返回的句柄。

    Engine 在每次循环中轮询 ``settled``，为 True 后
    读取 ``future.result()`` 获取召回的记忆。
    """
    future: Future  # Future[list[RelevantMemory]]
    settled: bool = False
    consumed: bool = False


def start_memory_prefetch(
    query: str,
    workspace: str,
    provider,                   # Provider (duck-typed)
    already_surfaced: set[str],
    session_memory_bytes: int,
) -> MemoryPrefetch | None:
    """当所有门控条件通过时启动异步召回。

    任一门控未通过则返回 ``None``（调用方直接跳过即可）。
    """
    # 门控 1: 查询必须有实质内容
    if not is_query_substantial(query):
        log.debug("记忆预取跳过: 查询不充分")
        return None

    if not isinstance(workspace, str) or not workspace.strip():
        log.debug("记忆预取跳过: workspace 无效")
        return None

    # 门控 2: 会话预算
    if not isinstance(session_memory_bytes, int) or isinstance(session_memory_bytes, bool):
        log.debug("记忆预取跳过: 会话预算无效")
        return None
    if session_memory_bytes >= MAX_SESSION_MEMORY_BYTES:
        log.debug("记忆预取跳过: 会话预算已满 (%d bytes)", session_memory_bytes)
        return None

    # 门控 3: 记忆文件必须存在
    mem_dir = get_memory_dir(workspace)
    has_memories = any(
        f.suffix == ".md" and f.name != "MEMORY.md"
        for f in mem_dir.iterdir()
    )
    if not has_memories:
        log.debug("记忆预取跳过: 无记忆文件")
        return None

    log.info("启动异步记忆预取: query=%s", query[:60])
    handle = MemoryPrefetch(
        future=_get_pool().submit(
            select_relevant_memories,
            query, workspace, provider, already_surfaced,
        ),
    )
    # 通过回调无阻塞地设置 settled 标志
    handle.future.add_done_callback(lambda _: setattr(handle, "settled", True))
    return handle
