# ForgeAgent

ForgeAgent 是一个学习 [claw-code](https://github.com/ultraworkers/claw-code)（Claude Code 的 Rust 实现）的项目，目标是用 Python 一步一步实现 Claude Code 类 Coding Agent 的核心架构。

它通过 OpenAI-compatible Chat Completions API 驱动，内置文件、Shell、记忆、Skill、子 Agent、计划模式、MCP 和上下文压缩能力。项目定位为可阅读、可改造的 Agent 系统实现：代码量保持克制，核心链路清晰，适合学习 Agent 架构，也可以作为本地编码助手继续扩展。

## 能力

| 能力 | 说明 |
|---|---|
| Agent 循环 | Think -> Act -> Observe，多轮工具调用直到模型完成任务 |
| OpenAI-compatible Provider | 只内置 OpenAI 协议；私有平台通过 `OPENAI_BASE_URL` 本地配置 |
| 工具系统 | `@tool` 注册，JSON Schema 参数校验，权限执行 |
| 文件与 Shell 工具 | 读写、替换、搜索、命令执行，带工作区边界保护 |
| 计划模式 | 只读规划，审批后执行 |
| 子 Agent | `agent` / `team` 支持隔离上下文和并行任务 |
| 记忆系统 | Markdown 记忆，跨会话保存、召回、注入 |
| Skill 系统 | Markdown + frontmatter 的提示词模板 |
| 上下文管理 | token 估算、工具结果裁剪、collapse、autocompact |
| MCP | 通过官方 MCP SDK 接入外部工具 |

## 快速开始

要求：

- Python 3.11+
- `uv`

```bash
uv sync
uv run forgeagent
```

配置 API：

```bash
cat > .env <<'EOF'
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o
EOF
```

常用命令：

```bash
uv run forgeagent                         # 交互式 REPL
uv run forgeagent -p "总结这个项目"          # 单次执行
uv run forgeagent -r latest               # 恢复最近会话
uv run python -m forgeagent --version
```

## REPL 命令

| 命令 | 说明 |
|---|---|
| `/help` | 查看命令 |
| `/save` / `/sessions` | 保存和列出会话 |
| `/usage` / `/cost` | 查看 token 用量和估算成本 |
| `/model <name>` | 切换模型，复用当前 endpoint |
| `/compact` | 手动压缩上下文 |
| `/memory` / `/remember <text>` | 查看或保存记忆 |
| `/plan` | 切换计划模式 |
| `/export [file]` | 导出当前对话 |
| `/skill-name` | 调用 Skill |

## 项目结构

```text
forgeagent/
├── interface/       # CLI、REPL、系统提示词、导出
├── core/            # Engine、Provider、权限、计划、子 Agent、MCP
├── tools/           # 内置工具实现
├── context/         # checkpoint、压缩、collapse、工具结果落盘
├── memory/          # 记忆存储、召回、预取
├── skills/          # Skill 发现和渲染
├── toolkit.py       # 工具注册、schema、执行入口
└── frontmatter.py   # Markdown frontmatter 解析
```

主链路：

```text
用户输入
  -> interface.repl
  -> Engine.run()
  -> prepare_round_inputs()
  -> Provider.generate()
  -> toolkit.run_batch()
  -> 工具结果写回 transcript
  -> 下一轮或完成
```

## 配置

远程仓库只保留 OpenAI-compatible 协议配置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | 空 | API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 兼容端点 |
| `MODEL` | `gpt-4o` | 模型名 |
| `FORGEAGENT_CTX_BUDGET` | `128000` | 上下文预算 |
| `FORGEAGENT_MAX_ROUNDS` | `60` | 单次任务最大循环轮次 |
| `FORGEAGENT_PERMISSION_MODE` | `prompt` | `readonly` / `write` / `prompt` / `danger` / `plan` |
| `FORGEAGENT_MCP_SERVERS` | 空 | MCP server JSON |

更多配置见 [docs/configuration.md](docs/configuration.md)。

## 文档

| 文档 | 用途 |
|---|---|
| [architecture-overview.md](docs/architecture-overview.md) | 架构和主链路 |
| [configuration.md](docs/configuration.md) | 环境变量和本地 endpoint 配置 |
| [memory-and-skills.md](docs/memory-and-skills.md) | 记忆与 Skill |
| [sub-agent-system.md](docs/sub-agent-system.md) | 子 Agent 和 team |
| [source-learning-guide.md](docs/source-learning-guide.md) | 面向源码学习的详细逐模块讲解 |
| [conventions/](docs/conventions/) | 代码、测试、工具开发规范 |

## 测试

```bash
uv run python -m compileall -q forgeagent
uv run --extra test python -m pytest -q
```

当前全量测试：`700 passed`。

## License

MIT
