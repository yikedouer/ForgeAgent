# ForgeAgent 源码学习文档

本文面向第一次阅读 ForgeAgent 源码的朋友。目标不是简单列目录，而是说明每个模块为什么存在、核心代码在哪里、如何把这些代码串成一个完整 Agent 系统。

推荐先读 `README.md` 和 `docs/architecture-overview.md` 建立整体概念，再按本文顺序阅读源码。

## 1. 项目定位

ForgeAgent 是一个 Python 实现的 Coding Agent。核心思想是：

1. 用户输入一个任务。
2. `Engine` 把系统提示词、历史消息、工具 schema、记忆、计划模式等组装成 LLM 请求。
3. LLM 返回自然语言或工具调用。
4. 工具调用经过权限系统检查后执行。
5. 工具结果写回对话，继续下一轮，直到模型不再调用工具。

最短运行链路是：

```text
forgeagent/__main__.py
  -> forgeagent.interface.repl.main()
  -> Settings.resolve()
  -> Provider(settings)
  -> Engine(settings, provider)
  -> ForgeREPL.run()
  -> Engine.run(user_input)
  -> run_agent_loop()
  -> provider.generate()
  -> toolkit.run_batch()
```

## 2. 建议阅读顺序

不要从所有工具文件开始读。更好的顺序是：

1. `forgeagent/interface/repl.py`：看 CLI 如何启动。
2. `forgeagent/core/settings.py`：看配置如何进入系统。
3. `forgeagent/core/engine.py`：看 Engine 拿到哪些依赖。
4. `forgeagent/core/engine_loop.py`：看一轮 Agent 循环。
5. `forgeagent/toolkit.py`：看工具如何注册和执行。
6. `forgeagent/tools/*.py`：看具体工具。
7. `forgeagent/context/*.py`：看上下文压缩和持久化。
8. `forgeagent/memory/*.py`：看记忆系统。
9. `forgeagent/core/subagent*.py`：看子 Agent。
10. `forgeagent/core/mcp/*.py`：看 MCP 外部工具接入。

## 3. 顶层入口和通用工具

### `forgeagent/__main__.py`

这是 `python -m forgeagent` 的入口。它通常只做一件事：调用 CLI 主函数。

学习重点：

- Python 包的命令入口如何转发到业务入口。
- 不在入口文件里放业务逻辑，便于测试和复用。

### `forgeagent/__init__.py`

包元信息模块，主要暴露版本号。

学习重点：

- 版本号被 `repl.py` 的 `--version` 和启动面板使用。
- 这类模块应保持轻量，避免导入时触发重逻辑。

### `forgeagent/filewalk.py`

封装文件遍历逻辑，供 `finder.py` 和 `stats.py` 复用。

核心代码：

```python
def walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not _skip_dir(name)]
        ...
```

设计点：

- 统一跳过 `.git`、虚拟环境、缓存目录等。
- 返回 `(relative_path, full_path)`，调用方既能展示相对路径，也能读取绝对路径。
- 比每个工具各写一套 `os.walk` 更简单。

### `forgeagent/frontmatter.py`

解析和生成 Markdown frontmatter。记忆、Skill、自定义 Agent 都依赖它。

核心结构：

```python
@dataclass(frozen=True)
class Frontmatter:
    meta: dict
    body: str
```

核心函数：

- `parse_frontmatter(text)`：从 Markdown 里解析 `---` 包裹的元数据。
- `format_frontmatter(meta, body)`：把元数据和正文重新写成 Markdown。

学习重点：

- ForgeAgent 把“可编辑配置”尽量放在 Markdown 中，frontmatter 是轻量结构化层。
- 这个模块是跨 memory、skills、subagent 的基础设施。

## 4. Interface：用户交互层

Interface 层负责把命令行输入变成 Engine 调用，不负责 Agent 决策。

### `forgeagent/interface/repl.py`

这是 CLI 主入口，也是用户交互主循环。

关键函数：

- `_build_parser()`：解析 `--model`、`--prompt`、`--resume`、`export` 等参数。
- `main()`：启动配置、Provider、Engine，处理 one-shot、resume、export 和交互模式。
- `ForgeREPL.default()`：把用户输入分流为普通任务、内置命令、Skill。
- `ForgeREPL.run()`：使用 `prompt_toolkit` 读取输入。

核心代码简化版：

```python
settings = Settings.resolve()
provider = Provider(settings)
engine = Engine(settings, provider)

if args.prompt:
    run_prompt_once(engine, args.prompt, ...)
else:
    ForgeREPL(engine).run()
```

`ForgeREPL.default()` 的分发逻辑：

```python
if line.lstrip().startswith("/") and self._dispatch_command(line):
    return
if line.lstrip().startswith("/"):
    self._invoke_skill(line)
else:
    self.engine.run(line, on_token=_on_token, on_tool=_on_tool)
```

学习重点：

- CLI 只做输入、输出、参数解析，不直接操作工具。
- `prompt_toolkit` 只负责交互体验，命令业务仍在 `repl_commands.py`。
- `-p/--prompt` 是非交互模式，方便脚本化和测试。

### `forgeagent/interface/repl_commands.py`

REPL 内置命令集合，作为 mixin 注入 `ForgeREPL`。

核心命令：

- `do_help()`：列出命令。
- `do_save()` / `do_sessions()`：会话保存和列出。
- `do_usage()` / `do_cost()`：token 用量。
- `do_model()`：切换模型。
- `do_plan()`：切换计划模式。
- `do_compact()`：手动触发压缩。
- `do_memory()` / `do_remember()`：查看和保存记忆。
- `do_export()`：导出当前对话。

设计点：

- 命令都写成 `do_xxx(arg)`，便于 `ForgeREPL._dispatch_command()` 通过 `getattr()` 动态分发。
- 只有 `/model xxx` 这类斜杠输入会触发内置命令；裸 `model` 会作为普通用户任务交给 Agent。

### `forgeagent/interface/directive.py`

系统提示词构建器。它决定 LLM “看到的角色、工具说明、项目规则、记忆索引、子 Agent 描述”等。

核心函数：

```python
def build(settings, *, plan_mode_prompt=None) -> str:
    parts = [...]
    return "\n\n".join(parts)
```

主要输入：

- `settings.workspace`：用于读取项目规则和 git 分支。
- `toolkit.schemas()`：生成工具清单。
- `memory.store.load_memory_index()`：加载记忆索引。
- `skills.playbook.describe_for_directive()`：描述可用 Skill。
- `subagent.build_agent_descriptions()`：描述可用子 Agent。
- `plan_mode_prompt`：计划模式下追加额外约束。

学习重点：

- Coding Agent 的“能力边界”很大程度由系统提示词决定。
- 提示词不是一整块硬编码，而是多个模块信息的汇总。

### `forgeagent/interface/cli_startup.py`

CLI 启动前校验和参数覆盖。

核心函数：

- `normalize_resume_id()`：把 `latest` 转成最近会话 ID。
- `apply_cli_settings_overrides()`：让 CLI 参数覆盖 `.env`。
- `validate_prompt_options()`：校验 `--prompt` 和 `--output-format` 组合。

学习重点：

- 参数校验应尽早发生，避免 Provider/Engine 已经构造后才失败。

### `forgeagent/interface/one_shot.py`

单次执行模式。

核心函数：

- `run_prompt_once()`：执行 `engine.run(prompt)`，按 `text/json/jsonl` 输出结果，最后关闭 Engine。
- `close_engine()`：对 Engine 关闭做防御式封装。

学习重点：

- 交互模式和单次模式共用同一个 Engine。
- one-shot 必须保证失败时也释放资源，尤其是 MCP server。

### `forgeagent/interface/export.py`

纯渲染模块。

核心函数：

- `render_transcript_markdown(session_id, messages)`
- `render_events_jsonl(events)`

学习重点：

- 渲染逻辑不依赖 Engine，因此容易测试。

### `forgeagent/interface/export_command.py`

`forgeagent export` 命令实现。

职责：

- 找到指定或最新 checkpoint。
- 调用 `export.py` 渲染。
- 按 `text/json/jsonl` 输出命令结果。

### `forgeagent/interface/plan_approval.py`

计划模式审批交互。

核心函数：

- `build_plan_approval_fn(console)`：返回异步审批函数。

审批结果会交给 `PlanModeController.handle_approval()`，因此 UI 和状态机分离。

### `forgeagent/interface/stats.py`

统计工作区代码行数。

核心结构：

- `ExtensionStats`
- `WorkspaceStats`
- `count_workspace_lines()`

学习重点：

- 复用 `filewalk.walk_files()`，避免重复忽略规则。

## 5. Core：Agent 编排层

### `forgeagent/core/settings.py`

配置系统，是所有运行时参数的唯一入口。

核心数据类：

```python
@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    context_budget: int
    max_rounds: int
    workspace: str
    permission_mode: str
    ...
```

核心函数：

- `_load_env_cascade()`：按用户级 `.env`、项目级 `.env`、真实环境变量级联加载。
- `_resolve_provider()`：根据 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `MODEL` 解析 API 信息。
- `Settings.resolve()`：构造最终配置。
- `Settings.for_model(model)`：切换模型名，复用当前 OpenAI-compatible endpoint。
- `Settings.replace(**kwargs)`：冻结 dataclass 的安全替换方式。

学习重点：

- 其他模块不直接读 `os.environ`，而是依赖 `Settings`。
- Provider 和 Model 分离，降低切换模型的复杂度。

### `forgeagent/core/providers.py`

LLM 调用封装层。它把 OpenAI-compatible SDK 响应转成 ForgeAgent 内部结构。

核心数据结构：

```python
@dataclass
class Invocation:
    call_id: str
    fn_name: str
    fn_args: dict

@dataclass
class Completion:
    text: str
    invocations: list[Invocation]
    usage_in: int
    usage_out: int
```

核心方法：

- `Provider.__init__()`：创建 OpenAI-compatible 客户端。
- `Provider.generate()`：带重试的主调用入口。
- `Provider._call()`：实际发请求并处理流式响应。
- `Provider.side_query()`：用于记忆召回、上下文折叠等轻量辅助查询。

设计点：

- Engine 不直接依赖 OpenAI SDK 的响应结构。
- 错误会归类成 `ContextWindowError`、`AuthenticationError`、`RateLimitedError`、`ProviderError`。
- `Completion.raw_assistant_msg` 可以重建 OpenAI 格式 assistant message，方便写回 transcript。

### `forgeagent/core/engine.py`

Engine 的主对象。它负责持有状态和暴露公开 API。

核心属性：

- `settings`：运行配置。
- `provider`：LLM 连接。
- `transcript`：完整对话记录。
- `session_id`：会话 ID。
- `_collapse`：上下文折叠状态。
- `enforcer`：权限检查器。
- `_plan`：计划模式控制器。
- `_mcp_manager`：MCP server 生命周期。

核心方法：

```python
def run(self, user_input, on_token=None, on_tool=None):
    return run_agent_loop(self, user_input=user_input, ...)
```

Engine 自身不塞满所有循环细节，而是把循环拆到 `engine_loop.py`，把会话/记忆/压缩辅助拆到 `engine_session.py`。

子 Agent 入口：

- `Engine.execute_sub_agent()`
- `Engine.execute_sub_agents_parallel()`

这两个类方法通过 `_active_engine` 找到当前父 Engine，再调用 `subagent_runtime.py`。

### `forgeagent/core/engine_loop.py`

这是最核心的 Agent 循环文件，建议重点阅读。

#### 一轮循环的核心过程

```python
append_message({"role": "user", "content": user_input})

for _ in range(state.settings.max_rounds):
    prepared = prepare_round_inputs(...)
    completion = provider.generate(...)
    append_message(completion.raw_assistant_msg)

    if not completion.invocations:
        return completion.text

    calls = build_tool_calls(completion.invocations)
    execute_normal_tool_calls(...)
```

核心函数分组：

工具处理：

- `build_tool_calls()`：把 Provider 的 `Invocation` 转成 `(call_id, name, args)`。
- `split_plan_tool_calls()`：把 `enter_plan_mode/exit_plan_mode` 和普通工具分开。
- `notify_tool_callbacks()`：让 UI 显示工具调用。
- `append_plan_tool_results()`：执行计划模式特殊工具。
- `execute_normal_tool_calls()`：调用 `toolkit.run_batch()` 并把结果写回 transcript。
- `persist_tool_results()`：大结果持久化前的统一处理。

请求构建：

- `build_directive_text()`：构建系统提示词。
- `build_wire_messages()`：把系统提示词、历史、collapse 投影组合成 API messages。
- `select_tool_schemas()`：选择可用工具，子 Agent 会过滤工具。
- `prepare_round_inputs()`：压缩、提示词、记忆注入、工具 schema 全部在这里完成。

LLM 调用和恢复：

- `generate_with_context_recovery()`：遇到上下文窗口错误时紧急裁剪后重试。
- `record_completion_usage()`：累计 token。
- `run_agent_loop()`：完整 Think → Act → Observe 主循环。

学习重点：

- `engine_loop.py` 是 ForgeAgent 行为的中枢。
- 工具结果必须以 `role=tool` 写回 transcript，下一轮 LLM 才能“观察”到结果。
- 没有工具调用时，说明模型认为任务完成，循环结束。

### `forgeagent/core/engine_session.py`

Engine 会话、运行时依赖、记忆注入、手动压缩、checkpoint API。

核心 mixin：

- `EnginePlanApiMixin`：计划模式公开方法。
- `EngineCheckpointApiMixin`：模型切换、保存、恢复会话。

核心函数：

- `initialize_engine_runtime()`：初始化 MCP manager、RuntimeRecorder、PermissionEnforcer、PlanModeController。
- `start_configured_runtime()`：加载 hook，启动 MCP server。
- `maybe_start_memory_prefetch()`：主 Agent 才异步预取记忆。
- `inject_recalled_memories()`：把召回记忆追加到最后一条 user message。
- `run_manual_compaction()`：手动压缩并返回前后统计。
- `reset_conversation_state()`：清空会话状态。
- `save_engine_checkpoint()` / `restore_engine_checkpoint()`：checkpoint 存取。

学习重点：

- Engine 本体只保留状态和入口，辅助逻辑放在这里降低 `engine.py` 复杂度。
- 记忆注入不直接修改 `transcript`，而是修改即将发送给 LLM 的 `wire_messages`。

### `forgeagent/core/permissions.py`

权限和工作区边界保护。

核心枚举：

```python
class PermissionMode(Enum):
    PLAN = "plan"
    READONLY = "readonly"
    WRITE = "write"
    PROMPT = "prompt"
    DANGER = "danger"
```

核心函数：

- `check_workspace_boundary(filepath, workspace)`：确保文件路径不逃出工作区。
- `PermissionEnforcer.check()`：按权限模式和工具风险级别决定是否允许执行。

学习重点：

- 工具声明 `risk_level`，权限系统不需要知道每个工具内部细节。
- 读写文件都检查工作区边界，防止 Agent 误操作用户主目录。

### `forgeagent/core/plan_mode.py`

计划模式状态机。

核心常量：

- `PLAN_TOOL_NAMES = {"enter_plan_mode", "exit_plan_mode"}`
- `PLAN_TOOL_DEFS`：暴露给 LLM 的两个计划工具定义。
- `EDIT_TOOL_NAMES = {"write_file", "edit_file"}`：计划模式下仅允许写 plan 文件。

核心类：

- `PlanModeController`

核心方法：

- `toggle()`：手动切换计划模式。
- `execute_tool(name)`：处理模型调用的 plan 工具。
- `handle_approval(result, plan_content)`：处理用户审批结果。
- `filter_calls(calls)`：计划模式下过滤普通工具调用。

学习重点：

- Plan mode 不是简单提示词约束，也有权限层和工具过滤层兜底。
- 用户审批结果可以选择清空上下文后执行、保留上下文执行、手动执行、继续规划。

### `forgeagent/core/subagent.py`

子 Agent 类型定义和自定义 Agent 发现。

核心内容：

- 内置类型：`explore`、`plan`、`verification`、`general`。
- 每种类型有专属 system prompt。
- `READ_ONLY_TOOLS`、`VERIFICATION_TOOLS` 控制工具白名单。
- 支持读取 `~/.agents/agents/*.md` 和 `<workspace>/.agents/agents/*.md`，同时兼容旧版 `.forgeagent/agents`。

核心函数：

- `discover_custom_agents()`：扫描自定义 agent。
- `resolve_sub_agent_tool_names()`：计算最终可用工具集。
- `get_sub_agent_config(agent_type)`：返回 `{system_prompt, tool_names}`。
- `build_agent_descriptions()`：把 agent 列表注入 directive。

学习重点：

- 子 Agent 是“隔离上下文 + 限定工具 + 独立模型”的组合。
- 自定义 Agent 也是 Markdown + frontmatter，和 Skill 设计一致。

### `forgeagent/core/subagent_runtime.py`

子 Agent 运行时执行和记录。

核心结构：

- `SubAgentRuntime`：子 Agent 的 settings/provider/model。
- `AgentRunRecord`：运行记录路径。
- `SubAgentExecutionResult`：子 Agent 结果和 token。

核心函数：

- `build_sub_agent_runtime()`：决定继承父 provider 还是按模型创建新 provider。
- `run_configured_sub_agent()`：构造子 Engine，执行 prompt，记录结果。
- `run_sub_agent_team()`：并行执行多个子 Agent。
- `execute_sub_agent_entry()`：`Engine.execute_sub_agent()` 的实际实现。
- `execute_sub_agents_parallel_entry()`：team 的实际实现。

学习重点：

- 子 Agent 创建的是新的 `Engine`，但可以复用父 provider。
- 子 Agent 的 token 会回传给父 Engine 统计。
- `team` 使用线程池并行执行多个子 Agent。

### `forgeagent/core/agent_store.py`

子 Agent 运行记录存储。

核心函数：

- `get_store_dir(workspace)`：定位 `.forgeagent/agent-runs` 存储目录。
- `create_agent_run()`：创建 Markdown 和 JSON 记录。
- `finalize_agent_run()`：写入结果、token、错误信息。

学习重点：

- Agent 运行记录既给人看（Markdown），也给程序处理（JSON）。

### `forgeagent/core/runtime.py`

运行时事件记录器。

核心类：

- `RuntimeRecorder`

职责：

- `append()`：统一向 transcript 追加消息。
- 主 Agent 会额外写 JSONL 事件到 checkpoint；子 Agent 不写主会话事件。

### `forgeagent/core/hooks.py`

Hook 系统。

核心函数：

- `register_hook(event, handler)`：注册 hook。
- `load_hook_file(path)`：动态加载用户 hook 文件。
- `emit_hook(event, payload)`：触发 hook。

Hook 当前主要被 `toolkit.run_one()` 的 `tool.before` 和 `tool.after` 使用。

### `forgeagent/core/errors.py`

统一异常类型。

核心异常：

- `ProviderError`
- `ContextWindowError`
- `AuthenticationError`
- `RateLimitedError`
- `ToolError`
- `PermissionDenied`

学习重点：

- Provider 层把 SDK 异常归一化，Engine 只处理内部异常类型。

### `forgeagent/core/log.py`

日志配置。

核心函数：

- `_setup()`：配置 log level、log file。
- `get_logger(name)`：统一获取 logger。

### `forgeagent/core/mcp/*`

MCP 是外部工具接入层。

#### `mcp/config.py`

解析 `FORGEAGENT_MCP_SERVERS`。

核心结构：

- `MCPServerConfig(name, command, args, env)`

核心函数：

- `parse_mcp_servers(raw)`：支持直接对象或 `{ "mcpServers": ... }` 包装。

#### `mcp/stdio.py`

官方 MCP SDK stdio transport 的同步 wrapper。

核心代码：

```python
self._portal_cm = start_blocking_portal()
self._portal = self._portal_cm.__enter__()
self._stdio_cm = self._portal.wrap_async_context_manager(
    stdio_client(_server_params(config))
)
self.streams = self._stdio_cm.__enter__()
```

学习重点：

- MCP SDK 是 async；ForgeAgent 主链路是 sync。
- 这里用 AnyIO blocking portal 把 async context manager 包成同步对象。

#### `mcp/protocol.py`

MCP client facade。

核心类：

- `MCPClient`
- `MCPTool`
- `MCPProtocolError`

核心方法：

- `initialize()`：初始化 SDK session。
- `list_tools()`：列出远程 MCP 工具并转成 `MCPTool`。
- `call_tool()`：调用远程工具，返回 dict。
- `close()`：关闭 SDK session context。

#### `mcp/lifecycle.py`

MCP server 生命周期。

核心类：

- `MCPServerManager`

职责：

- 根据配置启动 server。
- 创建 `StdioMCPTransport` 和 `MCPClient`。
- 调用 `toolkit.register_mcp_tools()` 把远程工具注册进本地工具目录。
- Engine 关闭时按 client → transport 顺序释放资源。

## 6. Toolkit：工具注册和执行

### `forgeagent/toolkit.py`

工具系统的中心。

核心数据结构：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]
    readonly: bool = False
    risk_level: str = "write"
```

工具注册方式：

```python
@tool(
    name="read_file",
    description="Read a file...",
    parameters={...},
    readonly=True,
    risk_level="read",
)
def read_file(...):
    ...
```

核心函数：

- `tool()`：装饰器，注册工具。
- `catalog()`：返回工具目录副本。
- `lookup(name)`：查找工具。
- `schemas()`：生成 LLM tool schema。
- `set_enforcer()`：设置权限检查器。
- `run_one(call_id, name, args)`：执行单个工具。
- `run_batch(calls)`：批量执行工具；只读工具可并发。
- `register_mcp_tools()`：把 MCP 远程工具注册成本地工具。

`run_one()` 的核心步骤：

1. 校验工具名和参数类型。
2. 检查必填参数。
3. 使用 `toolkit_schema.arg_type_error()` 校验 JSON Schema。
4. 调用 `PermissionEnforcer.check()`。
5. 触发 `tool.before` hook。
6. 执行实际 handler。
7. 捕获异常并转成 `ToolResult`。
8. 触发 `tool.after` hook。

### `forgeagent/toolkit_schema.py`

工具参数校验。

核心函数：

- `arg_type_error(parameters, args)`：返回人类可读的参数错误。
- `_strict_schema()`：把 schema 调整为严格模式。
- `_format_error()`：把 jsonschema 错误转成可读文本。

学习重点：

- LLM 工具调用经常出现参数类型错误；错误信息越清晰，下一轮自我修正越容易。

### `forgeagent/toolkit_mcp.py`

MCP 工具桥接。

核心函数：

- `build_mcp_tool_specs(server_name, client)`：把远程 MCP tool 转成 `MCPToolSpec`。
- `_safe_tool_name()`：把 server/tool 名转换成安全函数名。
- `_format_mcp_result()`：把 MCP 返回结果转成字符串。

生成的本地工具名格式：

```text
mcp__{server_name}__{tool_name}
```

## 7. Tools：内置工具模块

所有工具模块都有一个共同模式：

1. 顶部写工具说明。
2. 使用 `@tool(...)` 声明工具元数据。
3. 函数内部做参数校验。
4. 路径相关工具调用 `resolve_workspace_path()` 和边界检查。
5. 返回字符串给 LLM。

### `tools/__init__.py`

导入所有工具模块，触发 `@tool()` 注册。

核心点：

```python
from . import shell
from . import reader
...
```

如果忘记导入新工具，装饰器不会执行，工具不会进入 catalog。

### `tools/paths.py`

路径辅助模块。

核心函数：

- `active_workspace()`：从活跃 Engine 获取 workspace。
- `resolve_workspace_path(path)`：相对路径转成 workspace 下路径。
- `active_workspace_boundary_error(path)`：检查是否越界。

### `tools/reader.py`

`read_file` 工具。

核心保护：

- 空 path 拒绝。
- 工作区边界检查。
- 行号范围校验。
- 大文件大小限制。
- 二进制文件拒绝。
- 输出长度截断。

返回格式带行号：

```text
     1| line content
     2| another line
```

### `tools/writer.py`

`write_file` 工具。

核心保护：

- 工作区边界检查。
- 不能把目录当文件写。
- 自动创建父目录。
- 写入 memory 目录时自动更新 `MEMORY.md` 索引。

### `tools/editor.py`

`edit_file` 工具。

核心设计：

- `old_text` 必须恰好出现一次。
- 0 次返回 no match。
- 多次返回 ambiguous。
- 成功后返回 unified diff。

这是非常重要的安全设计：避免模型模糊替换导致误改。

### `tools/finder.py`

搜索工具。

工具：

- `glob_search(pattern, root, limit)`
- `grep_search(pattern, root, include, limit)`

核心依赖：

- `filewalk.walk_files()`：统一跳过无关目录。
- `fnmatch`：文件名 glob。
- `re`：内容正则搜索。

### `tools/shell.py`

Shell 执行工具。

核心安全机制：

- `_REJECTION_RULES`：静态拒绝危险命令，如 `rm -rf /`、`mkfs`、fork bomb、远程脚本 pipe shell 等。
- `_track_directory()`：跨调用保留 shell 工作目录。
- `_command_with_pwd_marker()` / `_extract_pwd_marker()`：执行后读取真实 cwd。
- `subprocess.run(... timeout=timeout)`：硬超时。

学习重点：

- Shell 是 `danger` 工具，因为它能力很强。
- 安全扫描不是完美沙箱，只是第一道护栏。

### `tools/memory.py`

给 LLM 使用的记忆 CRUD 工具。

工具：

- `memory_save`
- `memory_list`
- `memory_delete`

核心点：

- 通过 `_active_engine` 获取当前 workspace。
- 实际文件操作委托给 `memory/store.py`。

### `tools/skill.py`

Skill 工具。

核心流程：

1. 调用 `skills.playbook.invoke(skill_name, args)`。
2. 如果 skill 是 `inline`，返回提示词文本。
3. 如果 skill 是 `fork`，通过 `Engine.execute_sub_agent()` 创建隔离子 Agent。

学习重点：

- Skill 是“提示词模板能力”，不是 Python 插件。

### `tools/agent.py`

单个子 Agent 工具。

参数：

- `description`
- `prompt`
- `type`
- `model`

核心代码：

```python
from ..core.engine import Engine
return Engine.execute_sub_agent(type, description, prompt, model=model)
```

### `tools/team.py`

并行子 Agent 工具。

核心限制：

- `agents` 必须是非空 list。
- 最多 8 个并发子 Agent。
- 每个 spec 要有 `description` 和 `prompt`。

最终调用：

```python
Engine.execute_sub_agents_parallel(agents)
```

### `tools/finder.py`、`tools/reader.py`、`tools/writer.py` 的共同模式

它们都通过 `tools/paths.py` 做路径归一化和边界检查。这是文件类工具最重要的共性。

## 8. Context：上下文、checkpoint、压缩

### `context/checkpoint.py`

会话持久化。

核心结构：

```python
@dataclass
class Checkpoint:
    session_id: str
    messages: list[dict]
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
```

核心函数：

- `save(ckpt)`：保存完整 checkpoint JSON。
- `append_message_event()`：追加 JSONL 事件。
- `load(session_id)`：读取 checkpoint。
- `load_events(session_id)`：读取事件流。
- `list_checkpoints()`：列出会话。
- `latest_checkpoint()`：找最近会话。

学习重点：

- 完整快照和事件流同时存在，分别适合恢复和导出。
- session id 会经过严格校验，避免路径穿越。

### `context/compaction.py`

上下文压缩总入口。

核心函数：

- `maybe_compact(messages, budget, provider, ...)`

压缩层级：

1. `_budget_tool_results`
2. `_snip`
3. `_snip_stale_results`
4. `_microcompact_idle`
5. `try_collapse`
6. `_autocompact`
7. `_prune`

学习重点：

- 每次 LLM 调用前都会检查压缩。
- 优先使用 API 真实 token，如果没有则使用本地 token 估算。
- 压缩是渐进式的，能用轻量手段解决就不调用 LLM 摘要。

### `context/compaction_tokens.py`

token 计数。

核心函数：

- `estimate_tokens(text)`：使用 `tiktoken` 的 `cl100k_base`。
- `_fallback_estimate(text)`：tiktoken 不可用时回退到 `len/4`。
- `msg_tokens(message)`：统计 content 和 tool_calls。
- `conversation_tokens(messages)`：统计整段对话。

### `context/compaction_messages.py`

消息结构辅助。

核心函数：

- `iter_tool_calls(message)`
- `tool_function(tc)`
- `string_id(value)`
- `safe_split_point(messages, desired)`

`safe_split_point()` 很重要：压缩时不能把 assistant tool_call 和后面的 tool result 切开，否则会破坏 OpenAI message 格式。

### `context/compaction_tool_entries.py`

工具调用解析和可 snip 条目收集。

核心函数：

- `parse_tool_args_map(messages)`
- `collect_snippable_tool_entries(messages)`

学习重点：

- 压缩工具输出时，需要知道 tool result 对应哪个 tool call。

### `context/compaction_tiers.py`

具体压缩策略。

核心函数：

- `_budget_tool_results()`
- `_snip()`
- `_snip_stale_results()`
- `_microcompact_idle()`
- `_prune()`

学习重点：

- 这些函数大多会原地修改 `messages`。
- 越靠后的策略越激进。

### `context/compaction_autocompact.py`

LLM 自动摘要压缩。

核心函数：

- `_autocompact()`
- `_extract_recent_file_paths()`

学习重点：

- autocompact 是破坏性压缩，会用摘要替换旧消息。
- 有连续失败熔断，避免每轮都浪费调用。

### `context/collapse.py`

可逆上下文折叠。

核心结构：

```python
@dataclass
class CollapseState:
    collapse_boundary: int
    summary_text: str
    collapsed_at: int
```

核心函数：

- `try_collapse(messages, provider, keep_recent, existing)`
- `project_view(messages, collapse)`

学习重点：

- collapse 不改原始 transcript，只构造 API 投影视图。
- 这是和 autocompact 最大的区别。

### `context/tool_storage.py`

大型工具结果持久化。

核心函数：

- `persist_if_large(session_id, tool_name, content)`
- `persist_large_result(...)`
- `load_persisted_result(...)`
- `apply_result_budget(messages, session_id)`
- `reset_persisted_tracking()`

学习重点：

- 大型工具输出不应长期留在上下文里。
- 模型看到的是引用摘要，需要时再读持久化文件。

## 9. Memory：持久记忆系统

### `memory/store.py`

文件型记忆存储。

目录结构：

```text
~/.forgeagent/projects/{project_hash}/memory/
  MEMORY.md
  user_xxx.md
  feedback_xxx.md
```

核心函数：

- `get_memory_dir(workspace)`：定位记忆目录。
- `list_memories(workspace)`：读取所有记忆。
- `save_memory(...)`：保存 Markdown + frontmatter。
- `delete_memory(...)`：删除记忆。
- `load_memory_index(workspace)`：读取 `MEMORY.md`。
- `update_index(workspace)`：重建索引。

学习重点：

- git worktree 会尽量共享同一份记忆。
- 每个记忆文件都有 `name/description/type` frontmatter。

### `memory/recall.py`

语义记忆召回。

核心流程：

1. `scan_memory_headers()` 只读 frontmatter，避免加载所有正文。
2. `format_memory_manifest()` 生成候选清单。
3. `provider.side_query()` 让模型选择相关记忆。
4. 加载选中的记忆正文。
5. `format_memories_for_injection()` 包成 `<system-reminder>`。

学习重点：

- 召回不是关键词匹配，而是 LLM 辅助选择。
- 单文件和单会话都有大小限制，避免记忆污染上下文。

### `memory/prefetch.py`

异步记忆预取。

核心结构：

- `MemoryPrefetch`

核心函数：

- `is_query_substantial(query)`：判断用户输入是否值得召回记忆。
- `start_memory_prefetch(...)`：在线程池中启动 `select_relevant_memories()`。

学习重点：

- 记忆召回不阻塞当前轮主流程；如果准备好了，就在下一次构建 wire messages 时注入。

## 10. Skills：提示词模板系统

### `skills/playbook.py`

Skill 发现、解析和渲染。

核心结构：

```python
@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    mode: str
    path: str
    template: str
    user_invocable: bool
    allowed_tools: tuple[str, ...]
```

核心函数：

- `discover()`：扫描 `.agents/skills/<name>/SKILL.md`，同时兼容旧版 `.forgeagent/skills`。
- `find(name)`：按名称查找。
- `resolve_template(pb, arguments)`：替换 `$ARGUMENTS`。
- `invoke(name, arguments)`：返回 inline/fork 执行信息。
- `describe_for_directive()`：把可用 skill 注入系统提示词。
- `invalidate_cache()`：测试或文件变化后清缓存。

学习重点：

- Skill 和自定义 Agent 都采用 Markdown + frontmatter。
- Skill 可以 inline，也可以 fork 成子 Agent。

## 11. MCP：外部工具生态接入

MCP 模块已经在 core 部分介绍过，这里从数据流角度再串一次。

```text
Settings.resolve()
  -> parse_mcp_servers(FORGEAGENT_MCP_SERVERS)
  -> Engine.__init__()
  -> MCPServerManager.start()
  -> StdioMCPTransport(config)
  -> MCPClient(config, transport)
  -> client.initialize()
  -> toolkit.register_mcp_tools(server_name, client)
  -> LLM 可以调用 mcp__server__tool
```

学习重点：

- 本地工具和远程 MCP 工具最终都进入同一个 `toolkit` catalog。
- Engine 不关心工具来自 Python 函数还是 MCP server。

## 12. 关键设计模式

### 12.1 Facade

`Provider`、`MCPClient` 都是 facade：

- 屏蔽第三方 SDK 细节。
- 对外返回 ForgeAgent 内部数据结构。
- 方便测试时 mock。

### 12.2 Decorator Registry

`@tool(...)` 是装饰器注册表模式：

- 工具定义和注册放在一起。
- 导入模块即注册工具。
- `toolkit.schemas()` 可以动态生成 LLM 工具 schema。

### 12.3 State Holder + Pure Helpers

`Engine` 持有状态，复杂逻辑拆成函数：

- `engine_loop.py`：循环逻辑。
- `engine_session.py`：状态辅助。
- `context/*.py`：压缩策略。

这样测试可以直接测纯函数，不必每次构造完整 Engine。

### 12.4 Progressive Degradation

上下文压缩、记忆召回、MCP 启动都采用“失败不阻塞主流程”的思路：

- 记忆召回失败：跳过。
- collapse 失败：返回 None。
- MCP server 启动失败：记录 warning，主 Agent 继续运行。
- tiktoken 失败：回退粗估。

## 13. 每个目录的测试阅读建议

测试是学习代码行为的最快方式。

| 源码区域 | 推荐测试 |
|---|---|
| `toolkit.py` | `tests/test_toolkit.py` |
| `toolkit_schema.py` | `tests/test_toolkit_schema*.py` |
| `core/engine_loop.py` | `tests/core/test_engine_loop_*.py`、`tests/core/test_engine_tools_*.py` |
| `core/settings.py` | `tests/core/test_settings*.py` |
| `core/providers.py` | `tests/core/test_providers*.py` |
| `core/permissions.py` | `tests/core/test_permissions.py` |
| `core/plan_mode.py` | `tests/core/test_plan_mode*.py` |
| `core/subagent*.py` | `tests/core/test_subagent*.py` |
| `core/mcp/*.py` | `tests/core/test_mcp.py` |
| `context/*.py` | `tests/context/test_compaction*.py`、`tests/context/test_checkpoint.py` |
| `memory/*.py` | `tests/memory/test_*.py` |
| `interface/*.py` | `tests/interface/test_*.py` |
| `tools/*.py` | `tests/tools/test_*.py` |

运行全量测试：

```bash
uv run --extra test python -m pytest -q
```

运行某个模块测试：

```bash
uv run --extra test python -m pytest tests/core/test_mcp.py -q
```

## 14. 推荐动手练习

### 练习 1：新增一个只读工具

目标：新增 `list_dir` 工具。

阅读：

- `tools/reader.py`
- `toolkit.py`
- `tests/tools/`

要点：

- 使用 `@tool(readonly=True, risk_level="read")`。
- 参数 schema 写清楚。
- 路径必须经过 `resolve_workspace_path()`。
- 添加测试验证注册和权限。

### 练习 2：给 REPL 增加一个命令

目标：新增 `whereami` 命令，显示 workspace、model、permission mode。

阅读：

- `interface/repl.py`
- `interface/repl_commands.py`

要点：

- 在 `ForgeReplCommandMixin` 增加 `do_whereami(self, arg)`。
- 在 `COMMANDS` 中加入补全项。
- 加测试验证不会调用 `engine.run()`。

### 练习 3：理解一次工具调用

断点或打印这些位置：

1. `Provider.generate()`
2. `run_agent_loop()`
3. `build_tool_calls()`
4. `toolkit.run_batch()`
5. `toolkit.run_one()`
6. 具体工具函数，如 `read_file()`
7. `tool_result_messages()`

观察 transcript 如何从：

```text
user -> assistant(tool_calls) -> tool -> assistant(final text)
```

逐步增长。

### 练习 4：理解上下文压缩

阅读：

- `context/compaction.py`
- `context/compaction_tiers.py`
- `context/collapse.py`

尝试写一个小测试：

- 构造很多 tool message。
- 设置很小的 budget。
- 调用 `maybe_compact()`。
- 观察哪些消息被 snip 或 prune。

## 15. 常见误解

### 误解 1：Engine 直接执行工具

不是。Engine 只把工具调用转给 `toolkit.run_batch()`。工具注册、权限检查、参数校验都在 toolkit 和 permissions 中。

### 误解 2：Skill 是 Python 插件

不是。Skill 是 Markdown 提示词模板，最多 fork 一个子 Agent 执行。

### 误解 3：上下文压缩会直接丢历史

不总是。`collapse.py` 是可逆投影，不改原始 transcript。只有 autocompact、prune 等策略会破坏性修改消息。

### 误解 4：MCP 工具和本地工具是两套系统

不是。MCP 工具最终也会注册成 `ToolSpec`，进入同一个 `toolkit` catalog。

### 误解 5：权限只靠提示词

不是。提示词只是第一层约束，真正执行前还会走 `PermissionEnforcer.check()` 和路径边界检查。

## 16. 源码导航索引

这一节适合边看源码边查。前面的章节已经按功能讲了核心逻辑，这里按文件列出入口、职责和优先阅读点。

| 文件 | 职责 | 优先看 |
|---|---|---|
| [`forgeagent/__main__.py`](../forgeagent/__main__.py) | `python -m forgeagent` 入口 | 如何转发到 CLI main |
| [`forgeagent/__init__.py`](../forgeagent/__init__.py) | 包元信息 | 版本号暴露 |
| [`forgeagent/filewalk.py`](../forgeagent/filewalk.py) | 统一文件遍历 | 忽略目录规则、相对路径返回 |
| [`forgeagent/frontmatter.py`](../forgeagent/frontmatter.py) | Markdown frontmatter 解析 | `parse_frontmatter()`、`format_frontmatter()` |
| [`forgeagent/interface/__init__.py`](../forgeagent/interface/__init__.py) | interface 包初始化 | 通常无业务逻辑 |
| [`forgeagent/interface/repl.py`](../forgeagent/interface/repl.py) | 交互式 CLI 主循环 | `main()`、`ForgeREPL.default()`、`ForgeREPL.run()` |
| [`forgeagent/interface/repl_commands.py`](../forgeagent/interface/repl_commands.py) | REPL 内置命令 | `do_model()`、`do_plan()`、`do_compact()` |
| [`forgeagent/interface/directive.py`](../forgeagent/interface/directive.py) | 系统提示词组装 | `build()` 如何汇总工具、记忆、规则、skill |
| [`forgeagent/interface/cli_startup.py`](../forgeagent/interface/cli_startup.py) | 启动参数校验 | CLI 覆盖 settings 的方式 |
| [`forgeagent/interface/one_shot.py`](../forgeagent/interface/one_shot.py) | 非交互单次执行 | `run_prompt_once()` |
| [`forgeagent/interface/export.py`](../forgeagent/interface/export.py) | transcript 渲染 | Markdown / JSONL 输出 |
| [`forgeagent/interface/export_command.py`](../forgeagent/interface/export_command.py) | `forgeagent export` 命令 | checkpoint 选择和输出分发 |
| [`forgeagent/interface/plan_approval.py`](../forgeagent/interface/plan_approval.py) | 计划模式审批 UI | `build_plan_approval_fn()` |
| [`forgeagent/interface/stats.py`](../forgeagent/interface/stats.py) | 工作区行数统计 | `count_workspace_lines()` |
| [`forgeagent/core/__init__.py`](../forgeagent/core/__init__.py) | core 包初始化 | 通常无业务逻辑 |
| [`forgeagent/core/settings.py`](../forgeagent/core/settings.py) | 配置解析 | `Settings.resolve()`、OpenAI-compatible endpoint |
| [`forgeagent/core/providers.py`](../forgeagent/core/providers.py) | LLM SDK 封装 | `Provider.generate()`、`Completion` |
| [`forgeagent/core/engine.py`](../forgeagent/core/engine.py) | Agent 状态和公开 API | `Engine.run()`、子 Agent 入口 |
| [`forgeagent/core/engine_loop.py`](../forgeagent/core/engine_loop.py) | Think/Act/Observe 主循环 | `run_agent_loop()`、`prepare_round_inputs()` |
| [`forgeagent/core/engine_session.py`](../forgeagent/core/engine_session.py) | Engine 会话和运行时辅助 | checkpoint、记忆注入、手动压缩 |
| [`forgeagent/core/permissions.py`](../forgeagent/core/permissions.py) | 权限和路径边界 | `PermissionEnforcer.check()` |
| [`forgeagent/core/plan_mode.py`](../forgeagent/core/plan_mode.py) | 计划模式状态机 | `PlanModeController.filter_calls()` |
| [`forgeagent/core/subagent.py`](../forgeagent/core/subagent.py) | 子 Agent 配置和发现 | 内置类型、自定义 Agent frontmatter |
| [`forgeagent/core/subagent_runtime.py`](../forgeagent/core/subagent_runtime.py) | 子 Agent 执行 | `run_configured_sub_agent()`、team 并行 |
| [`forgeagent/core/agent_store.py`](../forgeagent/core/agent_store.py) | 子 Agent 运行记录 | Markdown + JSON 记录写入 |
| [`forgeagent/core/runtime.py`](../forgeagent/core/runtime.py) | 运行时事件记录 | `RuntimeRecorder.append()` |
| [`forgeagent/core/hooks.py`](../forgeagent/core/hooks.py) | Hook 加载和触发 | `emit_hook()` |
| [`forgeagent/core/errors.py`](../forgeagent/core/errors.py) | 内部异常类型 | Provider / Tool / Permission 异常边界 |
| [`forgeagent/core/log.py`](../forgeagent/core/log.py) | 日志配置 | `get_logger()` |
| [`forgeagent/core/mcp/__init__.py`](../forgeagent/core/mcp/__init__.py) | MCP 包初始化 | 通常无业务逻辑 |
| [`forgeagent/core/mcp/config.py`](../forgeagent/core/mcp/config.py) | MCP server 配置解析 | `parse_mcp_servers()` |
| [`forgeagent/core/mcp/stdio.py`](../forgeagent/core/mcp/stdio.py) | MCP stdio transport | AnyIO blocking portal |
| [`forgeagent/core/mcp/protocol.py`](../forgeagent/core/mcp/protocol.py) | MCP client facade | `initialize()`、`list_tools()`、`call_tool()` |
| [`forgeagent/core/mcp/lifecycle.py`](../forgeagent/core/mcp/lifecycle.py) | MCP 生命周期 | 启动 server、注册工具、关闭资源 |
| [`forgeagent/toolkit.py`](../forgeagent/toolkit.py) | 本地工具注册和执行 | `@tool`、`run_one()`、`run_batch()` |
| [`forgeagent/toolkit_schema.py`](../forgeagent/toolkit_schema.py) | 工具参数校验 | `arg_type_error()` |
| [`forgeagent/toolkit_mcp.py`](../forgeagent/toolkit_mcp.py) | MCP 工具转本地工具 | `build_mcp_tool_specs()` |
| [`forgeagent/tools/__init__.py`](../forgeagent/tools/__init__.py) | 导入内置工具并触发注册 | 新工具是否被 import |
| [`forgeagent/tools/paths.py`](../forgeagent/tools/paths.py) | 工具路径解析 | workspace 边界检查 |
| [`forgeagent/tools/reader.py`](../forgeagent/tools/reader.py) | `read_file` | 大小限制、二进制拒绝、行号输出 |
| [`forgeagent/tools/writer.py`](../forgeagent/tools/writer.py) | `write_file` | 父目录创建、memory 索引更新 |
| [`forgeagent/tools/editor.py`](../forgeagent/tools/editor.py) | `edit_file` | 唯一匹配替换、diff 返回 |
| [`forgeagent/tools/finder.py`](../forgeagent/tools/finder.py) | `glob_search` / `grep_search` | `walk_files()` 复用 |
| [`forgeagent/tools/shell.py`](../forgeagent/tools/shell.py) | shell 执行 | 拒绝规则、cwd 跟踪、超时 |
| [`forgeagent/tools/memory.py`](../forgeagent/tools/memory.py) | LLM 可用记忆工具 | save/list/delete 委托 store |
| [`forgeagent/tools/skill.py`](../forgeagent/tools/skill.py) | Skill 调用工具 | inline / fork 分支 |
| [`forgeagent/tools/agent.py`](../forgeagent/tools/agent.py) | 单子 Agent 工具 | `Engine.execute_sub_agent()` |
| [`forgeagent/tools/team.py`](../forgeagent/tools/team.py) | 多子 Agent 工具 | 并发限制和参数校验 |
| [`forgeagent/context/__init__.py`](../forgeagent/context/__init__.py) | context 包初始化 | 通常无业务逻辑 |
| [`forgeagent/context/checkpoint.py`](../forgeagent/context/checkpoint.py) | 会话持久化 | snapshot + JSONL event |
| [`forgeagent/context/compaction.py`](../forgeagent/context/compaction.py) | 压缩总入口 | `maybe_compact()` |
| [`forgeagent/context/compaction_tokens.py`](../forgeagent/context/compaction_tokens.py) | token 估算 | `tiktoken` + fallback |
| [`forgeagent/context/compaction_messages.py`](../forgeagent/context/compaction_messages.py) | message 结构辅助 | `safe_split_point()` |
| [`forgeagent/context/compaction_tool_entries.py`](../forgeagent/context/compaction_tool_entries.py) | 工具结果条目解析 | tool call 和 result 对齐 |
| [`forgeagent/context/compaction_tiers.py`](../forgeagent/context/compaction_tiers.py) | 分层压缩策略 | budget / snip / prune |
| [`forgeagent/context/compaction_autocompact.py`](../forgeagent/context/compaction_autocompact.py) | LLM 摘要压缩 | `_autocompact()` |
| [`forgeagent/context/collapse.py`](../forgeagent/context/collapse.py) | 可逆上下文折叠 | `try_collapse()`、`project_view()` |
| [`forgeagent/context/tool_storage.py`](../forgeagent/context/tool_storage.py) | 大型工具结果落盘 | `persist_if_large()`、`apply_result_budget()` |
| [`forgeagent/memory/__init__.py`](../forgeagent/memory/__init__.py) | memory 包初始化 | 通常无业务逻辑 |
| [`forgeagent/memory/store.py`](../forgeagent/memory/store.py) | 记忆文件存储 | `save_memory()`、`update_index()` |
| [`forgeagent/memory/recall.py`](../forgeagent/memory/recall.py) | LLM 辅助记忆召回 | `select_relevant_memories()` |
| [`forgeagent/memory/prefetch.py`](../forgeagent/memory/prefetch.py) | 异步记忆预取 | `start_memory_prefetch()` |
| [`forgeagent/skills/__init__.py`](../forgeagent/skills/__init__.py) | skills 包初始化 | 通常无业务逻辑 |
| [`forgeagent/skills/playbook.py`](../forgeagent/skills/playbook.py) | Skill 发现和渲染 | `discover()`、`invoke()` |

## 17. 核心代码速查

如果只想快速理解系统能力，优先读下面这些函数。它们连接了大部分模块。

| 问题 | 入口代码 |
|---|---|
| 用户输入怎么进入 Agent？ | `interface/repl.py` 的 `ForgeREPL.default()` |
| Engine 如何开始一轮循环？ | `core/engine.py` 的 `Engine.run()` |
| 一轮 Agent 循环在哪里？ | `core/engine_loop.py` 的 `run_agent_loop()` |
| 每轮发给模型前做了什么？ | `core/engine_loop.py` 的 `prepare_round_inputs()` |
| 系统提示词怎么构建？ | `interface/directive.py` 的 `build()` |
| 工具 schema 怎么生成？ | `toolkit.py` 的 `schemas()` |
| 工具如何注册？ | `toolkit.py` 的 `tool()` 装饰器 |
| 工具如何执行？ | `toolkit.py` 的 `run_one()` 和 `run_batch()` |
| 权限在哪里拦截？ | `core/permissions.py` 的 `PermissionEnforcer.check()` |
| 文件路径在哪里防越界？ | `tools/paths.py` 和 `core/permissions.py` |
| 上下文什么时候压缩？ | `context/compaction.py` 的 `maybe_compact()` |
| 记忆什么时候注入？ | `core/engine_session.py` 的 `inject_recalled_memories()` |
| 子 Agent 如何启动？ | `core/subagent_runtime.py` 的 `run_configured_sub_agent()` |
| MCP 工具如何接进来？ | `core/mcp/lifecycle.py` + `toolkit_mcp.py` |

## 18. 一句话总结各模块

| 模块 | 一句话 |
|---|---|
| `interface` | 把用户输入和 CLI 参数转成 Engine 调用 |
| `core` | Agent 状态、循环、Provider、权限、计划、子 Agent、MCP |
| `toolkit` | 工具注册、schema 生成、参数校验、权限执行 |
| `tools` | 具体工具实现 |
| `context` | transcript 持久化、token 估算、压缩、collapse、大结果存储 |
| `memory` | 跨会话记忆存储、召回、异步预取 |
| `skills` | Markdown skill 发现和渲染 |
| `tests` | 每个模块的行为规格 |

读懂 ForgeAgent 的关键，是把它看成一条流水线：

```text
输入 -> 提示词/记忆/工具 schema -> LLM -> 工具调用 -> 权限 -> 工具执行 -> 结果入上下文 -> 压缩 -> 下一轮
```

只要这条流水线清楚了，每个模块的位置和价值都会变得直观。
