"""引擎——编排 思考 → 行动 → 观察 循环的核心指挥器。

引擎管理：
  * 对话记录（消息列表）
  * Provider（LLM 连接）
  * 工具目录（通过 toolkit）
  * 压缩管道（通过 context.compaction）

公开 API 刻意保持精简：
  engine.run(user_input) → str   # 一次用户轮次，可能跨越多个循环
"""

from __future__ import annotations

import uuid
from typing import Callable

from .providers import Provider
from .settings import Settings
from .permissions import PermissionMode
from ..context.collapse import CollapseState
from ..memory.prefetch import MemoryPrefetch
from .log import get_logger
from .subagent_runtime import (
    execute_sub_agent_entry,
    execute_sub_agents_parallel_entry,
)
from .engine_loop import run_agent_loop
from .engine_session import (
    EngineCheckpointApiMixin,
    EnginePlanApiMixin,
    ManualCompactionReport,
    initialize_engine_runtime,
    inject_recalled_memories,
    reset_conversation_state,
    run_manual_compaction,
    start_configured_runtime,
)

# 确保首次导入时注册所有工具
from .. import tools as _tools  # noqa: F401

log = get_logger(__name__)


# ── 子 Agent 生成用单例引用 ────────────────────────────

_active_engine: Engine | None = None


class Engine(EnginePlanApiMixin, EngineCheckpointApiMixin):
    """核心 Agent 循环——思考、行动、观察、重复。"""

    def __init__(
        self,
        settings: Settings,
        provider: Provider,
        *,
        is_sub_agent: bool = False,
        custom_system_prompt: str | None = None,
        custom_tool_names: set[str] | None = None,
    ):
        global _active_engine

        self._log = log
        self._provider_factory = lambda settings: Provider(settings)
        self.settings = settings
        self.provider = provider
        self.transcript: list[dict] = []
        self.session_id = uuid.uuid4().hex[:12]
        self._round = 0
        self._collapse: CollapseState | None = None
        self._autocompact_failures: list[int] = [0]
        self._is_sub_agent = is_sub_agent

        # 子 Agent 覆盖配置
        self._custom_system_prompt: str | None = custom_system_prompt
        self._custom_tool_names: set[str] | None = custom_tool_names

        # 累计 token 计数器（用于子 Agent 汇聚）
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

        # 压缩跟踪
        self._last_input_tokens: int = 0
        self._last_api_call_time: float | None = None

        # 记忆状态
        self._already_surfaced: set[str] = set()
        self._session_memory_bytes: int = 0
        self._pending_prefetch: MemoryPrefetch | None = None
        initialize_engine_runtime(
            self,
            settings=settings,
            is_sub_agent=is_sub_agent,
        )
        if not is_sub_agent:
            start_configured_runtime(self)

        _active_engine = self
        log.info(
            "Engine 初始化  session=%s  model=%s  budget=%d  "
            "sub_agent=%s  permission=%s",
            self.session_id, settings.model, settings.context_budget,
            is_sub_agent, settings.permission_mode,
        )

    def close(self) -> None:
        """Release long-lived engine resources."""
        self._mcp_manager.close()

    def _append_message(self, message: dict) -> None:
        """Append to transcript and, for main agents, stream a JSONL event."""
        self._runtime.append(self.transcript, message)

    def clear_conversation(self) -> None:
        if self.enforcer.mode == PermissionMode.PLAN:
            self.toggle_plan_mode()
        reset_conversation_state(self)

    def compact_conversation(self) -> ManualCompactionReport:
        report = run_manual_compaction(
            self.transcript,
            budget=self.settings.context_budget,
            provider=self.provider,
            session_id=self.session_id,
            collapse_state=self._collapse,
            failure_count=self._autocompact_failures,
        )
        if report.result.collapse is not None:
            self._collapse = report.result.collapse
        return report

    def run(self, user_input: str,
            on_token: Callable[[str], None] | None = None,
            on_tool: Callable[[str, dict], None] | None = None) -> str:
        """处理一条用户消息，执行完整的 Agent 循环。

        循环持续运行，直到模型返回纯文本（无工具调用）
        或耗尽循环预算。
        """
        return run_agent_loop(
            self,
            user_input=user_input,
            on_token=on_token,
            on_tool=on_tool,
        )

    def _autosave_checkpoint(self) -> None:
        """主 Agent 成功结束一轮后自动保存；失败不打断响应。"""
        if self._is_sub_agent:
            return
        try:
            self.save_checkpoint()
        except Exception as exc:
            log.warning("自动保存 checkpoint 失败: %s", exc)

    def _inject_recalled_memories(self, wire_messages: list[dict]) -> list[dict]:
        """如果预取已完成，将召回的记忆注入 wire_messages。

        记忆追加到最后一条用户消息中，以保持大多数
        API 要求的 user/assistant 交替顺序。
        """
        result = inject_recalled_memories(wire_messages, self._pending_prefetch)
        self._already_surfaced.update(result.surfaced_paths)
        self._session_memory_bytes += result.additional_memory_bytes
        return result.messages

    @classmethod
    def execute_sub_agent(
        cls, agent_type: str, description: str, prompt: str,
        model: str | None = None,
        allowed_tools: tuple[str, ...] | list[str] | set[str] | None = None,
    ) -> str:
        """生成并执行子 Agent，返回其输出文本。

        子 Agent 获得类型专属的系统提示词和过滤后的工具集。
        Token 用量会汇聚回父引擎的累计计数器。
        运行记录会持久化到 ``.forgecc/agent-runs/`` 目录。

        参数:
            model: 可选，子 Agent 使用的模型名。未指定时继承父 Agent。
                   例如主 Agent 用 qwen3.6-plus，子 Agent 用 qwen3.5-flash。
        """
        global _active_engine
        parent = _active_engine

        try:
            return execute_sub_agent_entry(
                engine_cls=cls,
                parent=parent,
                agent_type=agent_type,
                description=description,
                prompt=prompt,
                model=model,
                allowed_tools=allowed_tools,
            )
        finally:
            _active_engine = parent  # 恢复父引擎为活跃引擎

    @classmethod
    def execute_sub_agents_parallel(
        cls,
        agent_specs: list[dict],
    ) -> list[dict]:
        """并行执行多个子 Agent（用于 team 工具）。

        每个 spec 包含 ``{type, description, prompt}``。
        返回 ``[{description, result, tokens_in, tokens_out}]`` 列表。

        对齐 claw-code 的 TeamCreate 后台线程并行模式：
        使用 ThreadPoolExecutor，每个子 Agent 在独立线程运行。
        """
        global _active_engine
        parent = _active_engine

        try:
            return execute_sub_agents_parallel_entry(
                engine_cls=cls,
                parent=parent,
                agent_specs=agent_specs,
            )
        finally:
            _active_engine = parent
