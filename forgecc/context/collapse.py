"""上下文折叠——可逆的读时投影。

与破坏性压缩（用摘要替换旧消息）不同，上下文折叠保持
*原始*对话记录不变，生成一个**投影视图**用于 API 调用。
投影将边界之前的内容替换为紧凑摘要，显著减少
token 数量，同时保持完整历史可恢复。

这是四层压缩管道的第 3 层：

  第 1 层  Snip          — 将大型工具结果持久化到磁盘
  第 2 层  Microcompact  — 清除旧的可压缩工具结果
  第 3 层  **折叠**      — 可逆投影（本模块）
  第 4 层  Autocompact   — LLM 生成摘要（破坏性）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.providers import Provider


# ── 折叠提示词 ──────────────────────────────────────────────

_COLLAPSE_PROMPT = (
    "You are a context compression assistant. "
    "Summarize the following conversation segment into a concise paragraph. "
    "Preserve:\n"
    "- The user's primary goal and intent\n"
    "- All file paths that were read, modified, or created\n"
    "- Key technical decisions and their rationale\n"
    "- Any errors encountered and how they were resolved\n"
    "- Pending or incomplete tasks\n"
    "- User-expressed preferences or corrections\n\n"
    "Omit verbose tool output details. Keep exact file paths and function names."
)


# ── 数据结构 ────────────────────────────────────────────────

@dataclass
class CollapseState:
    """跟踪单次折叠投影。

    *原始*消息列表不会被修改——折叠仅存储
    构建投影视图所需的元数据。
    """

    collapse_boundary: int
    """对话记录索引：messages[0:boundary] 被折叠。"""

    summary_text: str
    """折叠片段的 LLM 生成摘要。"""

    collapsed_at: int
    """折叠时的 len(messages)（用于过时检测）。"""

    _previous: CollapseState | None = field(default=None, repr=False)
    """链接到先前的折叠（用于增量重新折叠）。"""


# ── 核心函数 ─────────────────────────────────────────────────

def try_collapse(
    messages: list[dict],
    provider: Provider,
    keep_recent: int = 8,
    existing: CollapseState | None = None,
) -> CollapseState | None:
    """尝试为旧消息生成折叠摘要。

    成功时返回新的 CollapseState，不可行时返回 None
    （消息太少、LLM 失败等）。

    *messages* 列表**不会被修改**。
    """
    from .compaction import _safe_split_point

    if len(messages) <= keep_recent + 2:
        return None

    # 确定边界——此前的内容都被折叠
    desired = len(messages) - keep_recent
    boundary = _safe_split_point(messages, desired)

    # 不重复折叠相同的边界
    if existing and existing.collapse_boundary >= boundary:
        return None

    # 从已有折叠之后开始
    start = existing.collapse_boundary if existing else 0
    old_slice = messages[start:boundary]
    if not old_slice:
        return None

    # 构建摘要请求
    segment_text = "\n".join(
        f"[{m.get('role', '?')}] {str(m.get('content', ''))[:400]}"
        for m in old_slice
    )

    summary_input = [
        {"role": "user", "content": _COLLAPSE_PROMPT},
        {"role": "user", "content": segment_text},
    ]

    try:
        result = provider.generate(summary_input)
        summary_text = result.text or "(no summary produced)"
    except Exception:
        return None  # 优雅降级

    # 如果有先前的折叠，链接摘要
    if existing:
        combined = (
            f"{existing.summary_text}\n\n"
            f"[Additional context collapsed]\n{summary_text}"
        )
    else:
        combined = summary_text

    return CollapseState(
        collapse_boundary=boundary,
        summary_text=combined,
        collapsed_at=len(messages),
        _previous=existing,
    )


def project_view(
    messages: list[dict],
    collapse: CollapseState | None,
) -> list[dict]:
    """使用折叠状态构建 *messages* 的投影视图。

    无活跃折叠时返回原始 messages（同一列表）。
    否则返回**新列表**：
        [折叠摘要消息] + messages[boundary:]

    原始 *messages* 列表不会被修改。
    """
    if collapse is None:
        return messages

    summary_msg = {
        "role": "user",
        "content": (
            f"[CONTEXT COLLAPSED]\n"
            f"{collapse.summary_text}\n"
            f"[End of collapsed context — "
            f"{collapse.collapse_boundary} messages archived]"
        ),
    }

    return [summary_msg] + messages[collapse.collapse_boundary:]


def reset_collapse() -> None:
    """空操作占位——调用方直接将折叠引用设为 None 即可。"""
    pass  # 引擎设置 self._collapse = None
