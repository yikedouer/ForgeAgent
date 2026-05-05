"""持久化记忆系统 — 基于文件、跨会话、支持语义召回。

公开 API:
  * 存储:   get_memory_dir, list_memories, save_memory, delete_memory,
            load_memory_index, update_index, MemoryEntry
  * 召回:   select_relevant_memories, scan_memory_headers,
            memory_age, freshness_warning, RelevantMemory, MemoryHeader
  * 预取:   start_memory_prefetch, MemoryPrefetch, is_query_substantial
  * 元数据: parse_frontmatter, format_frontmatter
"""

from .store import (
    get_memory_dir,
    list_memories,
    save_memory,
    delete_memory,
    load_memory_index,
    update_index,
    MemoryEntry,
)
from .recall import (
    select_relevant_memories,
    scan_memory_headers,
    format_memories_for_injection,
    memory_age,
    freshness_warning,
    RelevantMemory,
    MemoryHeader,
)
from .prefetch import (
    start_memory_prefetch,
    MemoryPrefetch,
    is_query_substantial,
)
from ..frontmatter import parse_frontmatter, format_frontmatter

__all__ = [
    "get_memory_dir", "list_memories", "save_memory", "delete_memory",
    "load_memory_index", "update_index", "MemoryEntry",
    "select_relevant_memories", "scan_memory_headers",
    "format_memories_for_injection",
    "memory_age", "freshness_warning", "RelevantMemory", "MemoryHeader",
    "start_memory_prefetch", "MemoryPrefetch", "is_query_substantial",
    "parse_frontmatter", "format_frontmatter",
]
