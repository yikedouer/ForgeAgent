"""多层上下文窗口压缩管道。

问题：模型有有限的上下文窗口，但复杂任务可能跨越几十个轮次并
产生大量工具输出。若不压缩，对话终将超出预算并失败。

解决方案：渐进式压缩管道，每层比前一层更激进（也更耗资源）。
引擎在每次 LLM 调用前触发 ``maybe_compact()``，
应用最轻量且足够的层级后停止。

  Tier 1a — BUDGET (50%)：
      基于上下文利用率的动态按结果截断（头尾保留）。
      50-70%：30 K 预算；70%+：15 K 预算。

  Tier 1b — SNIP (50%)：
      将超大工具结果持久化到磁盘（旧版 50 K 阈值），
      然后将旧工具输出压缩为单行摘要。

  Tier 2 — SNIP STALE (60%)：
      去重 read_file 调用（仅保留每个路径的最新读取），
      清除除最近 3 个外的所有工具结果。

  Tier 2b — MICROCOMPACT IDLE（缓存冷却）：
      空闲 > 5 分钟时，激进清除除最新 3 个外的
      所有旧工具结果。

  Tier 3 — CONTEXT COLLAPSE (75%)：
      通过 LLM 生成旧消息摘要，但**不修改原始对话
      记录**。可逆。参见 ``collapse.py``。

  Tier 4 — AUTOCOMPACT (90%)：
      发起子调用生成结构化两阶段摘要，
      然后破坏性地替换旧消息。熔断器防护连续失败。

  紧急裁剪 (95%)：
      硬回退——丢弃除系统 + 近期尾部外的所有内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.providers import Provider

from .collapse import CollapseState, try_collapse, project_view  # noqa: F401
from .compaction_autocompact import (
    MAX_CONSECUTIVE_FAILURES,
    _autocompact,
    _extract_recent_file_paths,
)
from .compaction_messages import safe_split_point as _safe_split_point
from .compaction_tool_entries import (
    SNIPPABLE_TOOLS,
    SNIP_PLACEHOLDER,
)
from .compaction_tokens import (
    conversation_tokens as _conversation_tokens,
    estimate_tokens as _estimate_tokens,
    msg_tokens as _msg_tokens,
)
from .compaction_tiers import (
    KEEP_RECENT_RESULTS,
    MICROCOMPACT_IDLE_S,
    _build_tool_name_map,
    _budget_tool_results,
    _microcompact_idle,
    _prune,
    _snip,
    _snip_stale_results,
)

import logging
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 公开入口 — 渐进式管道
# ═══════════════════════════════════════════════════════════════

@dataclass
class CompactionResult:
    """压缩轮次的结果。"""
    performed: bool
    collapse: CollapseState | None = None


def maybe_compact(
    messages: list[dict],
    budget: int,
    provider: Provider | None = None,
    session_id: str = "",
    collapse_state: CollapseState | None = None,
    failure_count: list[int] | None = None,
    last_input_tokens: int = 0,
    last_api_call_time: float | None = None,
) -> CompactionResult:
    """应用能将对话压到预算内的最轻量压缩层。
    返回 ``CompactionResult`` 指示发生了什么
    （以及是否创建了新的折叠）。"""

    # 优先使用 API 返回的真实 token 数；回退到估算
    if last_input_tokens > 0:
        utilization = last_input_tokens / budget
    else:
        utilization = _conversation_tokens(messages) / budget

    if utilization <= 0.50:
        log.debug("压缩检查: utilization=%.1f%% ≤ 50%% — 跳过", utilization * 100)
        return CompactionResult(False)

    current = _conversation_tokens(messages)
    log.info("压缩管道启动: utilization=%.1f%%  est_tokens=%d  budget=%d  msgs=%d",
             utilization * 100, current, budget, len(messages))

    # ── Tier 1a: Budget (50%) — 动态按结果截断 ──
    if utilization > 0.50:
        changed = _budget_tool_results(messages, utilization)
        if changed:
            log.info("  Tier 1a BUDGET: 截断大结果")
        current = _conversation_tokens(messages)

    # ── Tier 1b: Snip (50%) — 旧版持久化 + 摘要 ─────────
    if current > budget * 0.50:
        if _snip(messages, session_id):
            current = _conversation_tokens(messages)
            log.info("  Tier 1b SNIP: 压缩后 est_tokens=%d", current)
            if current <= budget * 0.60:
                return CompactionResult(True)

    # ── Tier 2: Snip stale (60%) — 去重 + 清除 ──────────────
    if current > budget * 0.60:
        if _snip_stale_results(messages, utilization):
            current = _conversation_tokens(messages)
            log.info("  Tier 2 SNIP_STALE: 去重后 est_tokens=%d", current)
            if current <= budget * 0.75:
                return CompactionResult(True)

    # ── Tier 2b: Microcompact idle（缓存冷却）───────────────
    if _microcompact_idle(messages, last_api_call_time):
        log.info("  Tier 2b MICROCOMPACT_IDLE: 空闲清理触发")
    current = _conversation_tokens(messages)

    # ── Tier 3: Context Collapse (75%) — 可逆 ───────────
    if current > budget * 0.75 and provider is not None:
        log.info("  Tier 3 COLLAPSE: 尝试可逆上下文折叠...")
        new_collapse = try_collapse(
            messages, provider, existing=collapse_state,
        )
        if new_collapse:
            projected = project_view(messages, new_collapse)
            proj_tokens = _conversation_tokens(projected)
            log.info("  Tier 3 COLLAPSE: 投影后 est_tokens=%d", proj_tokens)
            if proj_tokens <= budget * 0.90:
                return CompactionResult(True, collapse=new_collapse)

    # ── Tier 4: Autocompact (90%) — 破坏性 ───────────────
    if current > budget * 0.90 and provider is not None:
        log.info("  Tier 4 AUTOCOMPACT: 尝试 LLM 摘要压缩...")
        if _autocompact(messages, provider, failure_count=failure_count):
            return CompactionResult(True)

    # ── 紧急裁剪 (95%) ───────────────────────────────────────
    if _conversation_tokens(messages) > budget * 0.95:
        log.warning("  紧急裁剪: 丢弃旧消息，仅保留近期尾部")
        _prune(messages)
        return CompactionResult(True)

    return CompactionResult(False)
