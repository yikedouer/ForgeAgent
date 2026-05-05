# 架构总览

ForgeAgent 是一个同步主循环的 Coding Agent。核心对象是 `Engine`：它持有配置、Provider、transcript、权限器、计划模式、MCP 生命周期和上下文状态。

## 分层

```text
interface/
  repl.py, repl_commands.py, directive.py
  用户输入、命令、系统提示词、导出

core/
  engine.py, engine_loop.py, engine_session.py
  providers.py, settings.py, permissions.py
  plan_mode.py, subagent.py, subagent_runtime.py, mcp/
  Agent 编排、Provider、权限、计划、子 Agent、MCP

toolkit.py, toolkit_schema.py, toolkit_mcp.py
  工具注册、schema 生成、参数校验、执行入口、MCP tool 桥接

tools/
  reader, writer, editor, finder, shell, memory, skill, agent, team
  内置工具实现

context/
  checkpoint, compaction, collapse, tool_storage
  会话持久化、上下文压缩、大工具结果落盘

memory/
  store, recall, prefetch
  跨会话记忆存储与召回

skills/
  playbook
  Markdown Skill 发现和渲染
```

## 主链路

```text
ForgeREPL.default()
  -> Engine.run(user_input)
  -> run_agent_loop()
  -> prepare_round_inputs()
       - maybe_compact()
       - build directive
       - inject recalled memories
       - select tool schemas
  -> Provider.generate(messages, tools)
  -> append assistant message
  -> toolkit.run_batch(tool calls)
       - validate schema
       - enforce permissions
       - execute handlers
  -> append tool results
  -> repeat until no tool calls
```

## 关键状态

| 状态 | 位置 | 说明 |
|---|---|---|
| `settings` | `Engine` | API、模型、权限、workspace、MCP 配置 |
| `provider` | `Engine` | OpenAI-compatible client 封装 |
| `transcript` | `Engine` | 完整对话历史 |
| `_collapse` | `Engine` | 可逆上下文折叠状态 |
| `_plan` | `Engine` | 计划模式控制器 |
| `_mcp_manager` | `Engine` | MCP server 生命周期 |
| `_active_engine` | `core.engine` | 工具执行时找到当前 workspace/parent engine |

## 工具系统

工具通过 `@tool(...)` 注册到 `toolkit._CATALOG`。LLM 看到的是 `toolkit.schemas()` 生成的 OpenAI function schema；真正执行时走 `toolkit.run_one()` / `run_batch()`。

执行步骤：

1. 查找工具。
2. 校验参数 schema。
3. 按 `risk_level` 和路径参数执行权限检查。
4. 触发 `tool.before` hook。
5. 调用 handler。
6. 捕获异常并封装为工具结果。
7. 触发 `tool.after` hook。

只读工具可并发执行；写入和高风险工具保持顺序执行。

## 上下文管理

每轮发送给模型前都会估算 token 并尝试压缩：

1. 大工具结果预算裁剪。
2. 长工具结果 snip。
3. 过期结果清理。
4. 空闲微压缩。
5. 可逆 collapse 投影视图。
6. LLM autocompact 摘要。
7. 紧急 prune。

`collapse.py` 不修改原始 transcript，只生成发送给 Provider 的投影视图。`autocompact` 和 `prune` 才会破坏性修改历史。

## 子 Agent

`agent` 和 `team` 工具通过 `Engine.execute_sub_agent()` 创建子 Engine。子 Agent 有独立 transcript、可选模型覆盖、过滤后的工具集和运行记录。执行结果以文本返回父对话，token 用量回传父 Engine。

## MCP

MCP 配置来自 `FORGEAGENT_MCP_SERVERS`。`MCPServerManager` 启动 stdio server，`MCPClient` 使用官方 MCP SDK 获取工具列表，`toolkit_mcp.py` 将远程工具转换成本地 `ToolSpec`。
