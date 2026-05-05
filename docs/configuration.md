# 配置系统

## 设计理念

**Provider 与 Model 分离**：Provider 决定「怎么连」（api_key、base_url、客户端类型），Model 决定「用哪个」（纯透传给 API）。

## Provider 预设

| Provider | base_url | api_key 环境变量 | 默认模型 | 客户端类型 |
|----------|----------|-----------------|---------|-----------|
| qwen | `dashscope.aliyuncs.com/compatible-mode/v1` | `QWEN_API_KEY` | qwen3.6-plus | openai |
| deepseek | `api.deepseek.com` | `DEEPSEEK_API_KEY` | deepseek-chat | openai |
| openai | `api.openai.com/v1` | `OPENAI_API_KEY` | gpt-4o | openai |
| azure | `iai.alibaba-inc.com/azure` | `AZURE_API_KEY` | gpt-4.1-0414 | azure |
| gemini | `iai.alibaba-inc.com/google` | `GEMINI_API_KEY` | google/gemini-3.1-pro-preview | openai |

> azure 和 gemini 使用公司内部代理（`iai.alibaba-inc.com`），需要配置 `FORGECC_EMP_ID`。

## 模型名前缀自动推断

未显式设置 `FORGECC_PROVIDER` 时，从模型名前缀自动推断：

| 前缀 | 推断的 Provider |
|------|----------------|
| `qwen` | qwen |
| `deepseek` | deepseek |
| `gpt` / `o1` / `o3` / `o4` | azure |
| `google/` / `gemini` | gemini |
| 其他 | qwen（默认） |

## 配置加载级联

后者覆盖前者：

```
1. 内置默认值（_PROVIDER_PRESETS）
     ↓
2. ~/.forgecc/.env（用户级）
     ↓
3. <workspace>/.env（项目级）
     ↓
4. 真实环境变量（始终最高优先级）
```

加载时同步注入 `os.environ`，确保子进程和第三方库也能读到配置。

## 环境变量清单

### 核心配置

| 变量 | 说明 | 示例 |
|------|------|------|
| `FORGECC_PROVIDER` | 服务商名 | `qwen` / `azure` / `gemini` |
| `FORGECC_MODEL` | 模型名（纯透传） | `qwen3.6-plus` / `gpt-4.1-0414` |

### API 密钥

| 变量 | 说明 |
|------|------|
| `QWEN_API_KEY` | Qwen（通义千问） |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `OPENAI_API_KEY` | OpenAI 原生 |
| `AZURE_API_KEY` | Azure OpenAI |
| `GEMINI_API_KEY` | Google Gemini |

### Azure 专用

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `AZURE_ENDPOINT` | Azure 端点 | 内置预设 |
| `AZURE_API_VERSION` | API 版本 | `2024-12-01-preview` |

### 公司内部代理

| 变量 | 说明 |
|------|------|
| `FORGECC_EMP_ID` | 工号，注入请求头 `empId`（azure/gemini 通过 `iai.alibaba-inc.com` 代理时必须） |

### 运行时

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FORGECC_CTX_BUDGET` | 上下文 token 上限 | `128000` |
| `FORGECC_MAX_ROUNDS` | Agent 循环最大轮次 | `60` |
| `FORGECC_PERMISSION_MODE` | 权限模式 | `prompt` |
| `FORGECC_MEMORY_DIR` | 记忆存储路径（绝对路径覆盖） | 自动推算 |
| `FORGECC_AGENTS_DIR` | 自定义 Agent 目录 | 自动发现 |
| `FORGECC_SESSION_DIR` | 会话检查点和大型工具结果目录 | `~/.forgecc/sessions` |
| `FORGECC_PLANS_DIR` | 计划模式文件目录 | `~/.forgecc/plans` |
| `FORGECC_HOOKS` | 本地 Hook 文件列表（用 `:` 或 `,` 分隔） | |
| `FORGECC_PROMPT_CACHE` | 为 system prompt 添加 cache_control 标记 | `false` |
| `FORGECC_MCP_SERVERS` | MCP server JSON 配置（支持 `mcpServers` 包装对象） | |

## .env 文件示例

```bash
# === Provider 选择 ===
FORGECC_PROVIDER=qwen
FORGECC_MODEL=qwen3.6-plus

# === API Keys ===
QWEN_API_KEY=sk-xxx

# === 公司内部代理（可选） ===
# FORGECC_EMP_ID=12345

# === 可选：切换到其他 Provider ===
# FORGECC_PROVIDER=azure
# FORGECC_MODEL=gpt-4.1-0414
# AZURE_API_KEY=xxx
```

## 子 Agent 级模型选择

`Settings.for_model(model_name)` 方法创建独立配置实例：

```python
# 主 Agent 用 qwen3.6-plus
main_settings = Settings.resolve()

# 子 Agent 用 qwen3.5-flash（自动推断 Provider 为 qwen）
sub_settings = main_settings.for_model("qwen3.5-flash")

# 甚至可以跨 Provider
gpt_settings = main_settings.for_model("gpt-4o")  # 自动切到 azure
```

`agent` 工具和 `team` 工具都支持 `model` 参数，实现同一对话中主/子 Agent 使用不同模型。

## 常见操作

### 切换 Provider

1. 编辑 `.env` 修改 `FORGECC_PROVIDER` 和 `FORGECC_MODEL`
2. 或 REPL 内 `/model qwen3.5-flash` 实时切换

### 添加新 Provider

在 `forgecc/core/settings_provider.py` 的 `_PROVIDER_PRESETS` 中添加新条目，并在 `_MODEL_PREFIX_MAP` 中注册前缀映射。
