# 配置系统

## 设计理念

ForgeAgent 远程仓库只内置 OpenAI-compatible 协议支持。Provider 不再保存任何平台预设、专用 endpoint、专用请求头或模型名前缀推断规则。

本地要连接 OpenAI 官方或任意兼容端点，只配置三项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | API key | 空 |
| `OPENAI_BASE_URL` | OpenAI-compatible endpoint | `https://api.openai.com/v1` |
| `MODEL` | 模型名，纯透传给 API | `gpt-4o` |

如果要使用私有平台，把私有 endpoint 写在本地 `.env` 或 shell 环境变量里。不要把 endpoint、专用 key 名、专用 header 或 provider preset 写入仓库。

## 配置加载级联

后者覆盖前者：

```text
1. 内置默认值
     ↓
2. ~/.forgeagent/.env（用户级）
     ↓
3. <workspace>/.env（项目级）
     ↓
4. 真实环境变量（始终最高优先级）
```

加载后会同步注入 `os.environ`，确保子进程和第三方库也能读到配置。

## 环境变量清单

### LLM

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI-compatible API key |
| `OPENAI_BASE_URL` | OpenAI-compatible base URL |
| `MODEL` | 模型名 |

### 运行时

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FORGEAGENT_CTX_BUDGET` | 上下文 token 上限 | `128000` |
| `FORGEAGENT_MAX_ROUNDS` | Agent 循环最大轮次 | `60` |
| `FORGEAGENT_PERMISSION_MODE` | 权限模式 | `prompt` |
| `FORGEAGENT_WORKSPACE` | 工作区根目录 | 当前目录 |
| `FORGEAGENT_MEMORY_DIR` | 记忆存储路径（绝对路径覆盖） | 自动推算 |
| `FORGEAGENT_AGENTS_DIR` | 自定义 Agent 目录 | 自动发现 |
| `FORGEAGENT_SESSION_DIR` | 会话检查点和大型工具结果目录 | `~/.forgeagent/sessions` |
| `FORGEAGENT_PLANS_DIR` | 计划模式文件目录 | `~/.forgeagent/plans` |
| `FORGEAGENT_HOOKS` | 本地 Hook 文件列表（用 `:` 或 `,` 分隔） | 空 |
| `FORGEAGENT_PROMPT_CACHE` | 为 system prompt 添加 cache_control 标记 | `false` |
| `FORGEAGENT_MCP_SERVERS` | MCP server JSON 配置（支持 `mcpServers` 包装对象） | 空 |

## `.env` 示例

```bash
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o

FORGEAGENT_PERMISSION_MODE=prompt
FORGEAGENT_CTX_BUDGET=128000
FORGEAGENT_MAX_ROUNDS=60
```

## 子 Agent 级模型选择

`Settings.for_model(model_name)` 会创建一个新配置实例，只替换模型名，复用父 Agent 的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。

```python
main_settings = Settings.resolve()
sub_settings = main_settings.for_model("small-model")
```

`agent` 工具和 `team` 工具都支持 `model` 参数，实现同一对话中主/子 Agent 使用不同模型。

## 常见操作

### 切换模型

1. 编辑 `.env` 中的 `MODEL`
2. 或 REPL 内执行 `/model small-model`

### 切换兼容端点

编辑本地 `.env`：

```bash
OPENAI_API_KEY=sk-local
OPENAI_BASE_URL=https://your-compatible-endpoint.example/v1
MODEL=your-model
```

兼容说明：旧版 `FORGEAGENT_MODEL` 仍可读取，但新配置和文档统一使用行业通用的 `MODEL`。
