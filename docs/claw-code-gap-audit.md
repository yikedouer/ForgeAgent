# claw-code vs ForgeCC 核心缺口审计

更新时间：2026-05-05

## 结论

ForgeCC 已从教学型 Agent Loop 扩展到接近 claw-code 核心工作流的实现：工具系统、子 Agent、计划模式、记忆、上下文压缩、会话恢复、Hook、JSON/JSONL 导出、prompt cache 标记和 MCP 工具接入都已有代码路径和测试覆盖。

当前仍是 Python 学习实现，不追求逐项复刻 claw-code 的 Rust 工程化细节。剩余弱项主要是长期运行稳定性与上游行为等价性审计。

## 已补齐的核心能力

| 能力 | ForgeCC 状态 | 证据 |
|------|--------------|------|
| Agent Loop + 工具调用 | 已实现 Think -> Act -> Observe 循环、单轮输入准备、prompt/schema 构建、LLM 上下文恢复、用量统计、工具调用准备、工具执行编排、工具日志格式化、批量执行、大结果持久化和结果回填 | `forgecc/core/engine.py`, `forgecc/core/engine_loop.py`, `forgecc/core/engine_tools.py`, `forgecc/toolkit.py`, `forgecc/toolkit_schema.py`, `tests/core/test_engine.py`, `tests/core/test_engine_loop_*.py`, `tests/core/test_engine_tools_*.py`, `tests/test_toolkit.py`, `tests/test_toolkit_schema.py`, `tests/test_toolkit_schema_value.py` |
| 权限与计划模式 | 已有 readonly/write/prompt/danger/plan 权限矩阵，计划工具、结果回填和审批回调 | `forgecc/core/permissions.py`, `forgecc/core/plan_mode.py`, `forgecc/core/engine_tools.py`, `tests/core/test_permissions.py`, `tests/core/test_plan_mode.py`, `tests/core/test_engine_tools_plan.py` |
| 子 Agent / 并行 Agent | 已有 agent/team 工具、自定义 agent 发现和描述、工具集解析、runtime 准备、执行编排、运行记录持久化、team 并行执行、结果归集和子 Agent 用量汇聚 | `forgecc/core/subagent.py`, `forgecc/core/subagent_runtime.py`, `forgecc/tools/agent.py`, `forgecc/tools/team.py`, `tests/core/test_subagent.py`, `tests/core/test_subagent_discovery.py`, `tests/core/test_subagent_tools.py`, `tests/core/test_subagent_runtime_*.py` |
| 上下文管理 | 已有压缩管道、无 LLM 压缩层、token 估算、Autocompact 摘要压缩、可逆 collapse、工具裁剪条目解析、工具大结果落盘、主 Agent 记忆预取、记忆注入状态统计和会话状态重置 | `forgecc/context/compaction.py`, `forgecc/context/compaction_tiers.py`, `forgecc/context/compaction_autocompact.py`, `forgecc/context/compaction_messages.py`, `forgecc/context/compaction_tokens.py`, `forgecc/context/compaction_tool_entries.py`, `forgecc/context/collapse.py`, `forgecc/context/tool_storage.py`, `forgecc/core/engine_session.py`, `tests/context/test_compaction.py`, `tests/context/test_compaction_tiers.py`, `tests/context/test_compaction_autocompact.py`, `tests/context/test_compaction_tokens.py`, `tests/context/test_compaction_tool_entries.py`, `tests/core/test_engine_session_*.py` |
| 会话持久化 | 已有 checkpoint、`resume latest`、自动保存、runtime JSONL event stream、离线 export、单次 prompt 输出封装 | `forgecc/context/checkpoint.py`, `forgecc/core/engine_session.py`, `forgecc/interface/repl.py`, `forgecc/interface/one_shot.py`, `forgecc/interface/cli_startup.py`, `forgecc/interface/export_command.py`, `forgecc/interface/export.py`, `forgecc/interface/plan_approval.py`, `forgecc/interface/stats.py`, `tests/context/test_checkpoint.py`, `tests/core/test_engine_session_checkpoint.py`, `tests/interface/test_repl.py`, `tests/interface/test_one_shot.py`, `tests/interface/test_cli_startup.py`, `tests/interface/test_export_command.py`, `tests/interface/test_export.py`, `tests/interface/test_plan_approval.py`, `tests/interface/test_stats.py` |
| Hook | 已有 hook 注册、payload 隔离、本地 hook 文件加载、工具 before/after 事件 | `forgecc/core/hooks.py`, `forgecc/toolkit.py`, `tests/core/test_hooks.py`, `tests/test_toolkit.py` |
| Prompt cache | 已支持通过 `FORGECC_PROMPT_CACHE` 为 system prompt 添加 cache_control 标记，Provider 响应类型和错误分类已独立测试 | `forgecc/core/providers.py`, `tests/core/test_providers.py`, `tests/core/test_provider_types.py`, `tests/core/test_provider_errors.py` |
| MCP | 已支持 `FORGECC_MCP_SERVERS`、MCP JSON-RPC client、stdio transport、远端 tool 桥接、Engine 初始化和关闭清理 | `forgecc/core/mcp/`, `forgecc/core/engine.py`, `forgecc/toolkit.py`, `forgecc/toolkit_mcp.py`, `tests/core/test_mcp.py`, `tests/core/test_engine.py`, `tests/test_toolkit.py`, `tests/test_toolkit_mcp.py` |

## 剩余弱项

| 弱项 | 当前处理 | 后续建议 |
|------|----------|----------|
| 真实 MCP server 端到端验证 | 已用本地最小 MCP stdio server 覆盖 initialize -> tools/list -> tools/call | 后续可补官方常见 MCP server 的手动冒烟脚本 |
| 长时进程韧性 | MCP 初始化失败不打断主流程，退出时关闭 transport | 增加超时、stderr 采集和进程 wait/kill 梯度清理 |
| claw-code 完全等价性 | 重点对齐核心 Coding Agent 能力，不复刻 Rust 内部实现 | 若需要等价性，应建立逐项功能矩阵并关联 upstream commit |

## 当前验证门槛

- `uv run --extra test python -m pytest`：870 passed
- `uv run python -m compileall -q forgecc`：通过
- 文档统计已同步到 README / AGENTS / testing conventions
