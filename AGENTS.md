# ForgeCC - Agent Context

> 从零构建的 Python Coding Agent，学习 claw-code 核心设计，用 ~9,000 行 Python 复现 Agent Loop + Tool System + Sub-Agent + Memory。仅依赖 openai + rich。

## Quick Start

```bash
uv sync             # 安装依赖（推荐 uv）
uv run forgecc      # 启动 REPL
uv run pytest       # 运行测试（870 用例）
```

传统方式：`pip install -e .` 后直接 `forgecc`。

## Common Workflows

- 日常使用直接 `uv run forgecc`，进入 REPL 后输入自然语言即可。
- REPL 内置命令：`/help`、`/save`、`/usage`、`/plan`、`/model [name]`、`/compact`、`/memory`、`/remember <text>`、`/diff`、`/skills`。
- 技能调用：`/commit`、`/review` 等前缀 `/` 加技能名。
- 切换模型：`/model qwen3.5-flash` 实时切换，Provider 自动推断。
- 计划模式：`/plan` 进入只读规划，生成计划后四选项审批（清空执行/保留执行/逐步审批/继续规划）。
- 测试：`uv run pytest` 全量运行；`uv run pytest tests/core/` 按模块运行。

## Module Map

| 模块 | 职责 | 关键导出 |
|------|------|---------|
| `forgecc/core/` | 核心引擎层：Agent 循环、LLM 调用、配置、权限、Hooks、子 Agent | `Engine`, `Provider`, `Settings`, `PermissionEnforcer` |
| `forgecc/instruments/` | 12 个内置工具实现（shell/读/写/编辑/搜索/agent/team/skill/memory） | 通过 `@instrument()` 装饰器自动注册 |
| `forgecc/interface/` | 用户交互：REPL、CLI 启动校验、系统提示词组装、流式输出 | `Repl`, `Directive.build()`, `Streamer` |
| `forgecc/context/` | 上下文管理：六层压缩管道、投影折叠、会话持久化 | `maybe_compact`, `try_collapse`, `save`, `load` |
| `forgecc/memory/` | 记忆系统：持久化存储、语义召回、异步预取 | `save_memory`, `list_memories`, `format_memories_for_injection` |
| `forgecc/skills/` | 技能系统：Markdown 技能发现与模板解析 | `Playbook`, `discover`, `invoke` |
| `forgecc/toolkit.py` | 装饰器驱动的工具注册表，批量执行（readonly 并发/write 顺序）+ 工具 Hook 事件 | `instrument()`, `catalog()`, `run_batch()` |
| `forgecc/toolkit_mcp.py` | MCP 远端工具桥接到本地工具 spec | `build_mcp_tool_specs()` |
| `forgecc/toolkit_schema.py` | 工具参数 JSON Schema 校验入口 | `arg_type_error()` |
| `forgecc/toolkit_schema_value.py` | 递归 JSON Schema value 校验 | `_schema_value_error()` |

## Tech Stack

Python 3.11+ / openai SDK / Rich（TUI 渲染） / pytest / uv

## Dependency Rules

模块分层，**单向依赖，禁止反向引用**：

```
interface/ ──→ core/ ──→ toolkit.py
    │            │           ↑
    │            │      instruments/
    │            ↓
    │        context/
    │        memory/
    │        skills/
    ↓
  用户
```

- **core/** 不依赖 interface/（引擎与 UI 解耦）
- **instruments/** 只依赖 toolkit.py 的 `@instrument()` 装饰器（工具实现与引擎解耦）
- **context/** / **memory/** / **skills/** 是独立子系统，core/ 单向调用
- **toolkit.py** 是全局工具目录，instruments/ 注册，core/ 查询和执行；schema 校验入口、递归 value 校验和 MCP 桥接分别拆分在 toolkit_schema.py / toolkit_schema_value.py / toolkit_mcp.py

## Code Conventions

核心原则：**简洁优先，最小依赖。定位根因，不做临时修复。**

- 代码纪律（命名、类型、异常处理）：[docs/conventions/code-discipline.md](docs/conventions/code-discipline.md)
- 工具开发规范（如何添加新工具）：[docs/conventions/tool-development.md](docs/conventions/tool-development.md)
- 测试规范（fixture、命名、覆盖范围）：[docs/conventions/testing.md](docs/conventions/testing.md)

代码风格：PEP 8，类型注解，dataclass 优先。两个三方依赖上限（openai + rich）。

## Configuration

Provider/Model 分离架构，5 种预设（qwen/deepseek/openai/azure/gemini）。

- `FORGECC_PROVIDER`：选择服务商（决定 api_key、base_url、客户端类型）
- `FORGECC_MODEL`：指定模型名（纯透传给 API）
- 模型名前缀自动推断 Provider（如 `gpt-4o` → azure，`qwen3.6-plus` → qwen）

配置加载级联（后者覆盖前者）：内置默认 → `~/.forgecc/.env` → `<workspace>/.env` → 真实环境变量。

详细配置说明：[docs/configuration.md](docs/configuration.md)

## Documentation Index

| 类别 | 路径 |
|------|------|
| **架构总览**（模块分层、数据流、Agent 循环） | [docs/architecture-overview.md](docs/architecture-overview.md) |
| **配置系统**（Provider 预设、.env 级联、模型切换） | [docs/configuration.md](docs/configuration.md) |
| **子 Agent 系统**（内置类型、自定义发现、Team 并行） | [docs/sub-agent-system.md](docs/sub-agent-system.md) |
| **记忆与技能**（持久记忆、技能发现、模板解析） | [docs/memory-and-skills.md](docs/memory-and-skills.md) |
| **代码纪律** | [docs/conventions/code-discipline.md](docs/conventions/code-discipline.md) |
| **工具开发规范** | [docs/conventions/tool-development.md](docs/conventions/tool-development.md) |
| **测试规范** | [docs/conventions/testing.md](docs/conventions/testing.md) |

## Key Directories & Paths

| 路径 | 用途 |
|------|------|
| `.forgecc/skills/` | 项目级技能定义（commit、review 等） |
| `.forgecc/agents/` | 项目级自定义 Agent 定义 |
| `~/.forgecc/.env` | 用户级环境配置 |
| `~/.forgecc/agents/` | 用户级自定义 Agent |
| `~/.forgecc/skills/` | 用户级技能 |
| `~/.forgecc/projects/{hash}/memory/` | 项目记忆存储（worktree 共享） |
| `~/.forgecc/plans/` | 计划模式生成的计划文件 |
